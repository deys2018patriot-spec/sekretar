"""Хранилище v2: динамические колонки (ИИ может создавать новые) + локальный Excel + Google Sheets."""
import os
from datetime import datetime
from openpyxl import Workbook, load_workbook

FILE = os.path.join(os.path.dirname(__file__), 'clients.xlsx')

# (внутренний ключ, заголовок)
CORE = [('id', 'ID'), ('created', 'Дата'), ('fio_child', 'ФИО ребенка'),
        ('age', 'Возраст'), ('parent_fio', 'ФИО родителя'), ('phone', 'Телефон'),
        ('shift', 'Смена'), ('status', 'Статус'), ('callback_dt', 'Дата перезвона'),
        ('comment', 'Комментарий')]
CORE_KEYS = [k for k, _ in CORE]
HEADER_TO_KEY = {h: k for k, h in CORE}
KEY_TO_HEADER = {k: h for k, h in CORE}
SHEETS = ['Общая', 'Осень 26', 'Зима 26', 'Весна 27']
OLD_SHEETS = ['Смена 1', 'Смена 2', 'Смена 3', 'Смена 4']


def _ensure_wb():
    if os.path.exists(FILE):
        wb = load_workbook(FILE)
    else:
        wb = Workbook()
        wb.active.title = 'Общая'
        wb.active.append([h for _, h in CORE])
        for s in SHEETS[1:]:
            wb.create_sheet(s).append([h for _, h in CORE])
        wb.save(FILE)
        return wb
    for s in SHEETS:
        if s not in wb.sheetnames:
            wb.create_sheet(s).append([h for _, h in CORE])
    # сносим старые вкладки Смена 1..4 (заменены сезонами)
    dropped = [s for s in OLD_SHEETS if s in wb.sheetnames]
    for s in dropped:
        del wb[s]
    if dropped:
        wb.save(FILE)
    return wb


def _headers(ws) -> list:
    return [str(c.value or '').strip() for c in next(ws.iter_rows(min_row=1, max_row=1))]


def _ensure_columns(wb, extra_keys: list[str]):
    """Добавляет новые колонки во все листы. Возвращает итоговые заголовки Общей."""
    ws0 = wb['Общая']
    heads = _headers(ws0)
    added = False
    for k in extra_keys:
        h = KEY_TO_HEADER.get(k, k[:30])
        if h not in heads:
            heads.append(h)
            added = True
    if not added:
        return heads
    for s in SHEETS:
        ws = wb[s]
        cur = _headers(ws)
        for h in heads:
            if h not in cur:
                ws.cell(row=1, column=len(_headers(ws)) + 1).value = h
    return heads


def read_all() -> list[dict]:
    return read_sheet('Общая')[1]


def read_sheet(name: str) -> tuple[list, list[dict]]:
    """Чтение любого листа: возвращает (заголовки, строки-словари)."""
    wb = _ensure_wb()
    if name not in wb.sheetnames:
        return [], []
    ws = wb[name]
    heads = _headers(ws)
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not any(r):
            continue
        d = {}
        for h, v in zip(heads, r):
            key = HEADER_TO_KEY.get(h, h.lower())
            d[key] = '' if v is None else str(v)
        for k, _ in CORE:
            d.setdefault(k, '')
        rows.append(d)
    return heads, rows


def read_all_sheets() -> dict:
    """Все листы книги: {имя: (заголовки, строки)}. Для вкладки Таблицы."""
    wb = _ensure_wb()
    return {s: read_sheet(s) for s in wb.sheetnames}


def write_sheet_local(sheet: str, header: list, rows: list) -> int:
    """Полностью заменяет/создаёт лист локально (для импорта файлов).

    Возвращает число записанных строк.
    """
    from openpyxl import Workbook
    if os.path.exists(FILE):
        wb = load_workbook(FILE)
    else:
        wb = Workbook()
    if sheet in wb.sheetnames:
        ws = wb[sheet]
        if ws.max_row >= 1:
            ws.delete_rows(1, ws.max_row)
        if ws.max_column >= 1:
            ws.delete_cols(1, ws.max_column)
    else:
        ws = wb.create_sheet(sheet)
    header = [str(h or '') for h in header] or ['A']
    ws.append(header)
    width = max([len(header)] + [len(r) for r in rows] + [1])
    for r in rows:
        ws.append([str(x or '') for x in list(r)] + [''] * (width - len(r)))
    for s in SHEETS:
        if s not in wb.sheetnames:
            wb.create_sheet(s).append([h for _, h in CORE])
    # убрать служебный пустой лист openpyxl, если остался
    for sn in list(wb.sheetnames):
        ws0 = wb[sn]
        if ws0.max_row == 1 and ws0.max_column == 1 and not ws0['A1'].value and sn != sheet:
            if len(wb.sheetnames) > 1:
                del wb[sn]
    wb.save(FILE)
    return len(rows)


def _row_dict_to_list(heads: list, d: dict) -> list:
    out = []
    for h in heads:
        key = HEADER_TO_KEY.get(h, h.lower())
        out.append(d.get(key, ''))
    return out


def upsert(data: dict) -> tuple[str, str, list[str]]:
    """Возвращает (действие, id, новые_колонки)."""
    from brain import fio_match
    import re
    extra = data.get('extra', {}) or {}
    new_cols = [k for k in extra if k not in CORE_KEYS]

    wb = _ensure_wb()
    heads = _ensure_columns(wb, new_cols)
    ws = wb['Общая']

    # flat-запись: extra поднимаем наверх
    flat = {k: data.get(k, '') for k, _ in CORE}
    for k, v in extra.items():
        flat[k] = v

    new_ph = re.sub(r'\D', '', str(data.get('phone', '')))
    new_fio = str(data.get('fio_child', ''))
    target = None
    for idx, r in enumerate(list(ws.iter_rows(min_row=2)), start=2):
        vals = {HEADER_TO_KEY.get(h, h.lower()): (str(c.value or '')) for h, c in zip(heads, r)}
        ph = re.sub(r'\D', '', vals.get('phone', ''))
        if new_ph and ph and new_ph[-7:] == ph[-7:]:
            target = idx
            break
        if new_fio and vals.get('fio_child') and fio_match(new_fio, vals['fio_child']):
            target = idx
            break

    now_s = datetime.now().strftime('%d.%m.%Y %H:%M')
    if target:
        for col_i, h in enumerate(heads, start=1):
            key = HEADER_TO_KEY.get(h, h.lower())
            if key in ('id', 'created'):
                continue
            v = flat.get(key, '')
            cell = ws.cell(target, col_i)
            if key in ('status', 'shift', 'callback_dt'):
                if v:
                    cell.value = v
            elif key == 'comment':
                if v and v not in str(cell.value or ''):
                    cell.value = (str(cell.value or '') + ' | ' + v).strip(' |')[:2000]
            elif key in extra:
                if v and not cell.value:
                    cell.value = v
                elif v and v not in str(cell.value or ''):
                    cell.value = str(cell.value or '') + '; ' + v
            else:
                if v and not cell.value:
                    cell.value = v
        cid = str(ws.cell(target, 1).value)
        action = 'обновлён'
    else:
        cid = str(int(datetime.now().timestamp()))[-6:]
        flat['id'], flat['created'] = cid, now_s
        if not flat.get('status'):
            flat['status'] = 'Новая'
        ws.append(_row_dict_to_list(heads, flat))
        action = 'добавлен'

    shift = str(data.get('shift', ''))
    if shift in wb.sheetnames:
        ws2 = wb[shift]
        for idx, r in enumerate(list(ws2.iter_rows(min_row=2)), start=2):
            if str(r[0].value or '') == cid:
                ws2.delete_rows(idx)
                break
        for r in ws.iter_rows(min_row=2, values_only=True):
            if str(r[0]) == cid:
                vals = list(r) + [''] * (len(heads) - len(r))
                ws2.append(vals[:len(heads)])
                break
    wb.save(FILE)

    # Google Sheets (не роняем локалку; один клиент на всю операцию — память 512МБ)
    try:
        import google_sync
        if google_sync.get_sheet_id() and os.path.exists(google_sync.TOKEN):
            _sheets = ['Общая'] + ([shift] if shift in SHEETS[1:] else [])
            with google_sync._API_LOCK:
                _svc = google_sync._service('sheets', 'v4')
                google_sync.ensure_sheet_structure(google_sync.get_sheet_id(), heads, _sheets, _svc=_svc)
                for r in ws.iter_rows(min_row=2, values_only=True):
                    if str(r[0]) == cid:
                        vals = [str(x or '') for x in r] + [''] * (len(heads) - len(r))
                        google_sync.push_row(vals[:len(heads)], 'Общая', _svc=_svc)
                        if shift in SHEETS[1:]:
                            google_sync.push_row(vals[:len(heads)], shift, _svc=_svc)
                        break
    except Exception as e:
        print(f'[Sheets] только локально ({e})')
    created = [k for k in new_cols if k not in [h.lower() for h in _headers(wb["Общая"])[:-len(new_cols)]]] if new_cols else []
    # Яндекс Диск: зеркало файла (не роняем локалку)
    try:
        import yandex_sync
        if yandex_sync.get_token():
            r = yandex_sync.sync_excel()
            if not r['ok']:
                print(f"[Yandex] {r['err']}")
    except Exception as e:
        print(f'[Yandex] только локально ({e})')
    # звонок состоялся — снимаем напоминания человека
    removed = {'local': 0, 'calendar': 0}
    if str(flat.get('status', '')) == 'Перезвонил':
        try:
            from reminders import remove_for
            removed = remove_for(str(flat.get('fio_child', '')), str(flat.get('phone', '')))
        except Exception as e:
            print(f'[reminders] {e}')
    return action, cid, new_cols, removed


# ===== Агент: полный доступ ИИ к таблицам =====

def _sync_row_to_google(wb, heads, cid: str, shift: str = ''):
    try:
        import google_sync
        if google_sync.get_sheet_id() and os.path.exists(google_sync.TOKEN):
            _sheets = ['Общая'] + ([shift] if shift in SHEETS[1:] else [])
            with google_sync._API_LOCK:
                _svc = google_sync._service('sheets', 'v4')
                google_sync.ensure_sheet_structure(google_sync.get_sheet_id(), heads, _sheets, _svc=_svc)
                ws = wb['Общая']
                for r in ws.iter_rows(min_row=2, values_only=True):
                    if str(r[0]) == cid:
                        vals = [str(x or '') for x in r] + [''] * (len(heads) - len(r))
                        google_sync.push_row(vals[:len(heads)], 'Общая', _svc=_svc)
                        if shift in SHEETS[1:]:
                            google_sync.push_row(vals[:len(heads)], shift, _svc=_svc)
                        break
    except Exception as e:
        print(f'[Sheets] {e}')


def find_ids(query: str) -> list[dict]:
    """Поиск строк по ФИО/телефону/ID. Понимает словоформы: 'Дамира' найдет 'Дамир'."""
    import re
    q = query.strip().lower()
    q_digits = re.sub(r'\D', '', q)
    q_words = [w for w in re.findall(r'[а-яёa-z]+', q) if len(w) > 3]

    def stem_hit(hay: str) -> bool:
        hw = re.findall(r'[а-яёa-z]+', hay.lower())
        for w in q_words:
            for h in hw:
                if len(h) > 3 and (h.startswith(w[:5]) or w.startswith(h[:5])):
                    return True
        return False

    out = []
    for r in read_all():
        hay = ' '.join(str(v) for v in r.values()).lower()
        ph = re.sub(r'\D', '', r.get('phone', ''))
        if q in hay or (q_digits and len(q_digits) >= 4 and q_digits in ph) \
                or q == r.get('id', '').lower() or stem_hit(hay):
            out.append(r)
    return out


def update_by_id(cid: str, fields: dict) -> bool:
    wb = _ensure_wb()
    extra_keys = [k for k in fields if k not in CORE_KEYS]
    heads = _ensure_columns(wb, extra_keys)
    ws = wb['Общая']
    for idx, r in enumerate(list(ws.iter_rows(min_row=2)), start=2):
        if str(r[0].value or '') == str(cid):
            for col_i, h in enumerate(heads, start=1):
                key = HEADER_TO_KEY.get(h, h.lower())
                if key in fields and fields[key] not in (None, ''):
                    if key == 'comment' and ws.cell(idx, col_i).value:
                        old = str(ws.cell(idx, col_i).value)
                        if fields[key] not in old:
                            ws.cell(idx, col_i).value = old + ' | ' + str(fields[key])
                    else:
                        ws.cell(idx, col_i).value = str(fields[key])
            wb.save(FILE)
            shift = str(fields.get('shift', '') or ws.cell(idx, heads.index(KEY_TO_HEADER['shift']) + 1).value or '')
            if shift in wb.sheetnames:
                ws2 = wb[shift]
                for j, r2 in enumerate(list(ws2.iter_rows(min_row=2)), start=2):
                    if str(r2[0].value or '') == str(cid):
                        ws2.delete_rows(j)
                        break
                for r3 in ws.iter_rows(min_row=2, values_only=True):
                    if str(r3[0]) == str(cid):
                        ws2.append(list(r3)[:len(heads)])
                        break
                wb.save(FILE)
            _sync_row_to_google(wb, heads, str(cid), shift)
            if str(fields.get('status', '')) == 'Перезвонил':
                try:
                    from reminders import remove_for
                    fio_i = heads.index(KEY_TO_HEADER['fio_child'])
                    ph_i = heads.index(KEY_TO_HEADER['phone'])
                    remove_for(str(ws.cell(idx, fio_i + 1).value or ''),
                               str(ws.cell(idx, ph_i + 1).value or ''))
                except Exception as e:
                    print(f'[reminders] {e}')
            return True
    return False


def delete_by_id(cid: str) -> bool:
    wb = _ensure_wb()
    found = False
    for s in wb.sheetnames:
        ws = wb[s]
        for idx, r in enumerate(list(ws.iter_rows(min_row=2)), start=2):
            if str(r[0].value or '') == str(cid):
                ws.delete_rows(idx)
                found = True
                break
    if found:
        wb.save(FILE)
        try:
            import google_sync
            if google_sync.get_sheet_id() and os.path.exists(google_sync.TOKEN):
                with google_sync._API_LOCK:
                    svc = google_sync._service('sheets', 'v4')
                    sid = google_sync.get_sheet_id()
                    for s in google_sync.list_sheets(sid, _svc=svc):
                        cur = svc.spreadsheets().values().get(spreadsheetId=sid, range=f'{s}!A:A').execute().get('values', [])
                        for i, r in enumerate(cur, start=1):
                            if r and str(r[0]) == str(cid) and i > 1:
                                svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={
                                    'requests': [{'deleteDimension': {
                                        'range': {'sheetId': _sheet_gid(svc, sid, s),
                                                  'dimension': 'ROWS', 'startIndex': i - 1, 'endIndex': i}}}]})\
                                    .execute()
                                break
        except Exception as e:
            print(f'[Sheets delete] {e}')
    return found


def _sheet_gid(svc, sid: str, title: str) -> int:
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    for s in meta.get('sheets', []):
        if s['properties']['title'] == title:
            return s['properties']['sheetId']
    return 0


def update_in_sheet(sheet: str, cid: str, fields: dict) -> bool:
    """Правит ячейки строки напрямую в указанном листе (без зеркалирования).

    Используется для сезонных листов: зеркало в Общую + Google делает вызывающий
    код через update_by_id. Возвращает True если строка найдена.
    """
    wb = _ensure_wb()
    if sheet not in wb.sheetnames:
        return False
    heads = _headers(wb[sheet])
    ws = wb[sheet]
    for idx, r in enumerate(list(ws.iter_rows(min_row=2)), start=2):
        if str(r[0].value or '') == str(cid):
            for col_i, h in enumerate(heads, start=1):
                key = HEADER_TO_KEY.get(h, h.lower())
                if key in fields and fields[key] not in (None, ''):
                    ws.cell(idx, col_i).value = str(fields[key])
            wb.save(FILE)
            return True
    return False


def apply_table_edits(sheet: str, heads: list, rows: list, recs: list) -> str:
    """Применяет правки таблицы: изменённые ячейки, новые и удалённые строки.

    sheet — 'Общая' или сезон ('Осень 26'...). Правки сезона пишутся и в сезонный
    лист, и в Общую (через update_by_id, он же пушит в Google). Удаление — везде.
    recs — записи вида {заголовок: значение} (уже без DataFrame).
    Возвращает сводку 'Правок: N, новых строк: M, удалено: K.'
    """
    key_of = {h: HEADER_TO_KEY.get(h, h.lower()) for h in (heads or [])}
    core_keys = [kk for kk, _ in CORE]

    def norm(v) -> str:
        if v is None:
            return ''
        if isinstance(v, float) and v != v:  # NaN
            return ''
        return str(v)

    n_old = len(rows)
    upd, new_n, del_n = 0, 0, 0
    seen_ids = set()
    for i, rec in enumerate(recs):
        if i < n_old:
            cid = str(rows[i].get('id', ''))
            if not cid:
                continue
            seen_ids.add(cid)
            fields = {}
            for h in (heads or []):
                k = key_of[h]
                if k in ('id', 'created'):
                    continue
                nv = norm(rec.get(h))
                if nv != rows[i].get(k, ''):
                    fields[k] = nv
            if not fields:
                continue
            if sheet == 'Общая':
                if update_by_id(cid, fields):
                    upd += 1
            elif update_in_sheet(sheet, cid, fields) and update_by_id(cid, fields):
                upd += 1
        else:
            d, extra = {}, {}
            for h in (heads or []):
                v = norm(rec.get(h))
                if not v:
                    continue
                k = key_of[h]
                if k in core_keys:
                    d[k] = v
                elif k not in ('id', 'created'):
                    extra[k] = v
            if not any(d.values()) and not extra:
                continue
            d.setdefault('status', 'Новая')
            if sheet != 'Общая':
                d.setdefault('shift', sheet)
            d['extra'] = extra
            upsert(d)
            new_n += 1
    for r in rows:
        cid = str(r.get('id', ''))
        if cid and cid not in seen_ids and delete_by_id(cid):
            del_n += 1
    return f'Правок: {upd}, новых строк: {new_n}, удалено: {del_n}.'


def set_shift(cid: str, shift: str) -> bool:
    return update_by_id(cid, {'shift': shift})


def add_column(name: str) -> list:
    wb = _ensure_wb()
    heads = _ensure_columns(wb, [name.strip().lower()[:30]])
    wb.save(FILE)
    try:
        import google_sync
        if google_sync.get_sheet_id() and os.path.exists(google_sync.TOKEN):
            google_sync.ensure_sheet_structure(google_sync.get_sheet_id(), heads)
    except Exception as e:
        print(f'[Sheets] {e}')
    return heads
