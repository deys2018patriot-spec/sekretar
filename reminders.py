"""Напоминания: локально бесплатно + Google Calendar."""
import json
import os
from datetime import datetime

FILE = os.path.join(os.path.dirname(__file__), 'reminders.json')


def _load() -> list:
    if not os.path.exists(FILE):
        return []
    try:
        return json.load(open(FILE, encoding='utf-8'))
    except Exception:
        return []


def _save(data: list):
    json.dump(data, open(FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def add_local_reminder(fio: str, callback_iso: str, phone: str = ''):
    if not callback_iso:
        return None
    data = _load()
    item = {'fio': fio, 'callback_dt': callback_iso, 'phone': phone,
            'created': datetime.now().isoformat()}
    # пробуем Google Calendar (если настроен) - не роняем если нет
    try:
        from google_sync import create_calendar_event
        ev = create_calendar_event(f'Перезвонить: {fio} {phone}', callback_iso, f'Клиент лагеря: {fio}, тел {phone}')
        item['event_id'] = ev.get('id', '')
    except Exception as e:
        print(f'[Calendar] только локально ({e})')
    data.append(item)
    _save(data)
    return item


def clear_all() -> dict:
    """Сносит ВСЕ напоминания: локальные + события в Google Calendar. Возвращает счетчики."""
    data = _load()
    n_local = len(data)
    n_cal = 0
    ids = [d.get('event_id') for d in data if d.get('event_id')]
    if ids:
        try:
            import google_sync
            svc = google_sync._service('calendar', 'v3')
            for eid in ids:
                try:
                    svc.events().delete(calendarId='primary', eventId=eid).execute()
                    n_cal += 1
                except Exception:
                    pass
        except Exception as e:
            print(f'[Calendar clear] {e}')
    # старые события без сохраненного ID — ищем по названию и сносим
    try:
        import google_sync
        n_cal += google_sync.delete_events_by_text('Перезвонить')
    except Exception as e:
        print(f'[Calendar sweep] {e}')
    # Google Задачи про перезвон
    n_tasks, tasks_err = 0, ''
    try:
        import google_sync
        ok, err = google_sync._tasks_ok()
        if ok:
            n_tasks = google_sync.delete_call_tasks()
        else:
            tasks_err = err
    except Exception as e:
        tasks_err = str(e)[:200]
    _save([])
    return {'local': n_local, 'calendar': n_cal, 'tasks': n_tasks,
            'no_event_id': n_local - len(ids), 'tasks_err': tasks_err}


def due_reminders():
    now = datetime.now()
    out = []
    for d in _load():
        try:
            if datetime.fromisoformat(d['callback_dt']) <= now:
                out.append(d)
        except Exception:
            pass
    return out


def remove_for(fio: str = '', phone: str = '') -> dict:
    """Снимает напоминания человека: локальные + события Calendar. Возвращает счетчики."""
    import re
    data = _load()
    ph = re.sub(r'\D', '', phone or '')
    keep, gone = [], []
    for d in data:
        dph = re.sub(r'\D', '', d.get('phone', ''))
        hit = (ph and dph and ph[-7:] == dph[-7:])
        if not hit and fio:
            from difflib import SequenceMatcher
            a, b = fio.lower().strip(), str(d.get('fio', '')).lower().strip()
            hit = bool(a and b) and (a in b or b in a or SequenceMatcher(None, a, b).ratio() > 0.75)
        (gone if hit else keep).append(d)
    n_cal = 0
    eids = [d.get('event_id') for d in gone if d.get('event_id')]
    try:
        import google_sync
        if eids:
            svc = google_sync._service('calendar', 'v3')
            for eid in eids:
                try:
                    svc.events().delete(calendarId='primary', eventId=eid).execute()
                    n_cal += 1
                except Exception:
                    pass
        elif gone and fio:
            # без сохраненных ID — ищем событие по имени
            svc = google_sync._service('calendar', 'v3')
            from datetime import timedelta, timezone
            now = datetime.now(timezone.utc)
            page = None
            while True:
                res = svc.events().list(calendarId='primary', q=fio,
                    timeMin=(now - timedelta(days=730)).isoformat(),
                    timeMax=(now + timedelta(days=730)).isoformat(),
                    singleEvents=True, maxResults=50, pageToken=page).execute()
                for ev in res.get('items', []):
                    if 'Клиент лагеря:' in str(ev.get('description', '')) and fio.lower().split()[0] in str(ev.get('summary', '')).lower():
                        try:
                            svc.events().delete(calendarId='primary', eventId=ev['id']).execute()
                            n_cal += 1
                        except Exception:
                            pass
                page = res.get('nextPageToken')
                if not page:
                    break
    except Exception as e:
        print(f'[Calendar remove] {e}')
    _save(keep)
    return {'local': len(gone), 'calendar': n_cal}
