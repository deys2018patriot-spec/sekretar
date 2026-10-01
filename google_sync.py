"""Google-интеграция (Calendar + Sheets). Все вызовы бесплатны в пределах квот Google.
Файлы рядом с этим модулем:
  client_secret.json - скачать из Google Cloud Console (OAuth Desktop)
  token.json - создается один раз через auth_google.py
  sheet.id - ID гугл-таблицы (создается в auth_google.py или вручную)
"""
import os
import threading
import time

# Один переиспользуемый API-клиент: discovery.build() парсит многомегабайтную
# схему и на 512МБ инстансе (Render Free) роняет процесс при частых вызовах.
# Плюс RLock — httplib2 не потокобезопасен, а Streamlit гоняет скрипт в потоках.
_API_LOCK = threading.RLock()
_SVC_CACHE: dict = {}
_SVC_TTL = 3000  # секунд (токен живёт ~час)

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.path.join(BASE, 'token.json')
SECRET = os.path.join(BASE, 'client_secret.json')
SHEET_ID_FILE = os.path.join(BASE, 'sheet.id')

SCOPES = ['https://www.googleapis.com/auth/calendar',
          'https://www.googleapis.com/auth/spreadsheets',
          'https://www.googleapis.com/auth/tasks']


def _env_token_present() -> bool:
    return bool(os.environ.get('GOOGLE_TOKEN_JSON', '').strip())


def _ensure_token_file_from_env() -> None:
    """Cloud-фолбэк: материализует token.json из env GOOGLE_TOKEN_JSON."""
    content = os.environ.get('GOOGLE_TOKEN_JSON', '').strip()
    if content and not os.path.exists(TOKEN):
        try:
            with open(TOKEN, 'w', encoding='utf-8') as f:
                f.write(content.strip())
        except Exception:
            pass


def status() -> dict:
    return {
        'client_secret': os.path.exists(SECRET),
        'token': os.path.exists(TOKEN) or _env_token_present(),
        'sheet_id': get_sheet_id(),
    }


def get_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    _ensure_token_file_from_env()
    if not os.path.exists(TOKEN):
        raise RuntimeError('Нет token.json - запусти: python auth_google.py')
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        open(TOKEN, 'w').write(creds.to_json())
    return creds


def _service(api: str, ver: str):
    from googleapiclient.discovery import build
    with _API_LOCK:
        hit = _SVC_CACHE.get((api, ver))
        if hit and time.time() - hit[1] < _SVC_TTL:
            return hit[0]
        try:
            from httplib2 import Http
            svc = build(api, ver, credentials=get_creds(), http=Http(timeout=25))
        except Exception:
            svc = build(api, ver, credentials=get_creds())
        _SVC_CACHE[(api, ver)] = (svc, time.time())
        return svc


def _drop_service(api: str, ver: str) -> None:
    with _API_LOCK:
        _SVC_CACHE.pop((api, ver), None)


def create_calendar_event(title: str, iso_dt: str, desc: str = ''):
    """Создает событие 'Перезвонить' с напоминанием за 15 мин."""
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(iso_dt)
    svc = _service('calendar', 'v3')
    ev = {'summary': title, 'description': desc,
          'start': {'dateTime': dt.isoformat(), 'timeZone': 'Europe/Moscow'},
          'end': {'dateTime': (dt + timedelta(minutes=15)).isoformat(), 'timeZone': 'Europe/Moscow'},
          'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 15}]},
          }
    return svc.events().insert(calendarId='primary', body=ev).execute()


def get_sheet_id() -> str:
    env_sid = os.environ.get('GOOGLE_SHEET_ID', '').strip()
    if env_sid:
        return env_sid
    if os.path.exists(SHEET_ID_FILE):
        return open(SHEET_ID_FILE, encoding='utf-8').read().strip()
    return os.environ.get('SPREADSHEET_ID', '').strip()


def ensure_sheet_structure(spreadsheet_id: str, headers: list | None = None, sheets: list | None = None,
                           _svc=None):
    """Создает листы Общая + сезоны и шапку (с учетом новых колонок ИИ)."""
    sheets = sheets or ['Общая', 'Осень 26', 'Зима 26', 'Весна 27']
    svc = _svc or _service('sheets', 'v4')
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    have = {s['properties']['title'] for s in meta.get('sheets', [])}
    need = sheets
    reqs = []
    for n in need:
        if n not in have:
            reqs.append({'addSheet': {'properties': {'title': n}}})
    if reqs:
        svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={'requests': reqs}).execute()
    headers = headers or ['ID', 'Дата', 'ФИО ребенка', 'Возраст', 'ФИО родителя', 'Телефон',
                'Смена', 'Статус', 'Дата перезвона', 'Комментарий']
    for n in need:
        try:
            cur = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f'{n}!A1:A1').execute()
            # сверяем шапку: если в Google меньше колонок - дописываем
            cur_vals = svc.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=f'{n}!1:1').execute().get('values', [[]])[0]
            if len(cur_vals) < len(headers):
                svc.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=f'{n}!1:1',
                    valueInputOption='USER_ENTERED', body={'values': [headers]}).execute()
            elif not cur_vals:
                svc.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=f'{n}!1:1',
                    valueInputOption='USER_ENTERED', body={'values': [headers]}).execute()
        except Exception:
            pass


def delete_sheets(spreadsheet_id: str, titles: list):
    """Удаляет вкладки по названиям (для сноса старых Смена 1..4)."""
    svc = _service('sheets', 'v4')
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    reqs = []
    for s in meta.get('sheets', []):
        if s['properties']['title'] in titles:
            reqs.append({'deleteSheet': {'sheetId': s['properties']['sheetId']}})
    if reqs:
        svc.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={'requests': reqs}).execute()
    return len(reqs)


SELF_MARK = 'Клиент лагеря:'


def delete_events_by_text(text: str = 'Перезвонить', past_days: int = 730, future_days: int = 730) -> int:
    """Удаляет ВСЕ события про перезвон (свои и чужие): совпадение 'перезвон'/'прозвон'
    в названии в любом падеже. Сканирует весь календарь."""
    from datetime import datetime, timedelta, timezone
    svc = _service('calendar', 'v3')
    now = datetime.now(timezone.utc)
    seen = {}

    def hit(summary: str) -> bool:
        s = summary.lower()
        return 'перезвон' in s or 'прозвон' in s

    for q in ('перезвон', 'перезвонить', 'прозвон'):
        page = None
        while True:
            res = svc.events().list(calendarId='primary', q=q,
                timeMin=(now - timedelta(days=past_days)).isoformat(),
                timeMax=(now + timedelta(days=future_days)).isoformat(),
                singleEvents=True, maxResults=100, pageToken=page).execute()
            for e in res.get('items', []):
                seen[e['id']] = e
            page = res.get('nextPageToken')
            if not page:
                break
    n = 0
    deleted = []
    for eid, ev in seen.items():
        if hit(str(ev.get('summary', ''))):
            try:
                svc.events().delete(calendarId='primary', eventId=eid).execute()
                n += 1
                deleted.append(str(ev.get('summary', '')))
            except Exception:
                pass
    open(os.path.join(BASE, 'deleted_log.txt'), 'a', encoding='utf-8').write(
        datetime.now().isoformat() + ' DELETED: ' + ' | '.join(deleted) + '\n')
    return n


def list_own_events(text: str = 'Перезвонить') -> list:
    from datetime import datetime, timedelta, timezone
    svc = _service('calendar', 'v3')
    now = datetime.now(timezone.utc)
    items = []
    page = None
    while True:
        res = svc.events().list(calendarId='primary', q=text,
            timeMin=(now - timedelta(days=730)).isoformat(),
            timeMax=(now + timedelta(days=730)).isoformat(),
            singleEvents=True, maxResults=100, pageToken=page).execute()
        items += res.get('items', [])
        page = res.get('nextPageToken')
        if not page:
            break
    return [{'summary': e.get('summary', ''), 'start': (e.get('start') or {}).get('dateTime', ''),
             'own': SELF_MARK in str(e.get('description', ''))} for e in items]


def push_row(row: list, sheet: str = 'Общая', _svc=None):
    """Upsert по ID (колонка A): обновляет если ID уже есть, иначе добавляет."""
    sid = get_sheet_id()
    if not sid:
        raise RuntimeError('Нет ID таблицы')
    svc = _svc or _service('sheets', 'v4')
    cid = str(row[0])
    try:
        cur = svc.spreadsheets().values().get(spreadsheetId=sid, range=f'{sheet}!A:A').execute().get('values', [])
        for i, r in enumerate(cur, start=1):
            if r and str(r[0]) == cid and i > 1:
                svc.spreadsheets().values().update(spreadsheetId=sid, range=f'{sheet}!{i}:{i}',
                    valueInputOption='USER_ENTERED', body={'values': [row]}).execute()
                return {'updated': True, 'row': i}
    except Exception:
        pass
    return svc.spreadsheets().values().append(
        spreadsheetId=sid, range=f'{sheet}!A:ZZ',
        valueInputOption='USER_ENTERED', body={'values': [row]}).execute()


# старое имя для совместимости
def push_to_sheet(spreadsheet_id: str, row: list):
    svc = _service('sheets', 'v4')
    return svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range='Общая!A:J',
        valueInputOption='USER_ENTERED', body={'values': [row]}).execute()


# ===== Google Задачи (Tasks) =====

def _tasks_ok() -> tuple[bool, str]:
    """Проверяет доступ к Tasks (нужны включенный API + scope)."""
    try:
        svc = _service('tasks', 'v1')
        svc.tasklists().list(maxResults=1).execute()
        return True, ''
    except Exception as e:
        return False, str(e)[:200]


def list_call_tasks() -> list:
    """Все незавершенные задачи про перезвон во всех списках."""
    svc = _service('tasks', 'v1')
    out = []
    tls = svc.tasklists().list().execute().get('items', [])
    for tl in tls:
        page = None
        while True:
            res = svc.tasks().list(tasklist=tl['id'], showCompleted=False,
                maxResults=100, pageToken=page).execute()
            for t in res.get('items', []):
                title = str(t.get('title', ''))
                if 'перезвон' in title.lower() or 'прозвон' in title.lower():
                    out.append({'list': tl.get('title', ''), 'list_id': tl['id'],
                                'id': t['id'], 'title': title})
            page = res.get('nextPageToken')
            if not page:
                break
    return out


def delete_call_tasks() -> int:
    """Удаляет задачи про перезвон. Возвращает число."""
    svc = _service('tasks', 'v1')
    n = 0
    for t in list_call_tasks():
        try:
            svc.tasks().delete(tasklist=t['list_id'], task=t['id']).execute()
            n += 1
        except Exception:
            pass
    return n
