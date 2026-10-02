"""Хранилище v2: динамические колонки (ИИ может создавать новые) + локальный Excel + Google Sheets."""
import os
import re
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
    try:
        import yandex_store
        yandex_store.sync_after_change('импорт ' + sheet)
    except Exception as e:
        print(f'[Yandex] только локально ({e})')
    return len(rows)


def _row_dict_to_list(heads: list, d: dict) -> list:
    out = []
    for h in heads:
        key = HEADER_TO_KEY.get(h, h.lower())
        out.append(d.get(key, ''))
    return out


GENERATED = ['Долги', 'Отчёт']


def validate_row(data: dict) -> dict:
    """Чинит поля записи: телефон, возраст, смена, статус, дата.

    Невалидное не удаляет — правит к канону, а факт правки кладёт
    в extra 'нужна_проверка'. Никогда не роняет.
    """
    try:
        from brain import extract_phone, normalize_shift
        d = dict(data)
        fixed = []
        ph = extract_phone(str(d.get('phone', '')))
        if ph != str(d.get('phone', '')):
            d['phone'] = ph
            if ph:
                fixed.append('телефон')
        age = re.sub(r'\D', '', str(d.get('age', '')))[:2]
        if age and not (6 <= int(age) <= 17):
            age = ''
            fixed.append('возраст')
        d['age'] = age
        sh = normalize_shift(str(d.get('shift', '')))
        if sh != str(d.get('shift', '')) and str(d.get('shift', '')):
            fixed.append('смена')
            d['shift'] = sh
        st = str(d.get('status', '') or 'Новая').strip().capitalize()
        canon = {'Новая': 'Новая', 'Перезвонить': 'Перезвонить',
                 'Перезвонил': 'Перезвонил', 'Думает': 'Думает',
                 'Оплачено': 'Оплачено', 'Отказ': 'Отказ',
                 'Приехал': 'Приехал', 'Оплачен': 'Оплачено',
                 'Оплачена': 'Оплачено', 'Оплатить': 'Оплачено'}
        if st not in ('Новая', 'Перезвонить', 'Перезвонил', 'Думает',
                      'Оплачено', 'Отказ', 'Приехал'):
            st = canon.get(st, 'Новая')
            fixed.append('статус')
        d['status'] = st
        cb = str(d.get('callback_dt', '') or '').strip()
        if cb:
            try:
                datetime.fromisoformat(cb)
            except Exception:
                d['callback_dt'] = ''
                fixed.append('дата')
        if fixed:
            ex = dict(d.get('extra', {}) or {})
            ex.setdefault('нужна_проверка', ', '.join(fixed))
            d['extra'] = ex
        return d
    except Exception as e:
        print(f'[validate] {e}')
        return data


def bulk_update(query: str, fields: dict) -> tuple[int, int]:
    """Групповое обновление: всем найденным — поля. Возвращает (всего, ок).

    Одна заливка на Диск в конце + автоснапшот до старта.
    """
    import re
    rows = find_ids(query)
    if not rows:
        return 0, 0
    try:
        import yandex_store
        yandex_store.snapshot('bulk: ' + query[:40])
        yandex_store.defer(True)
    except Exception:
        pass
    ok = 0
    try:
        fields = dict(fields or {})
        fields['обновлено'] = datetime.now().strftime('%d.%m.%Y %H:%M')
        for r in rows:
            try:
                if update_by_id(r['id'], fields):
                    ok += 1
            except Exception:
                pass
    finally:
        try:
            import yandex_store
            yandex_store.defer(False)
        except Exception:
            pass
    return len(rows), ok


def export_csv(sheet: str) -> tuple[str, bytes]:
    """Лист → CSV-байты (UTF-8 с BOM для Excel). Возвращает (имя, байты)."""
    import csv
    import io
    heads, rows = read_sheet(sheet)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(heads)
    for r in rows:
        w.writerow([r.get(HEADER_TO_KEY.get(h, h.lower()), '') for h in heads])
    data = '\ufeff' + buf.getvalue()
    return f'{sheet}.csv', data.encode('utf-8')


def _sum_val(v) -> float:
    try:
        return float(re.sub(r'[^\d.]', '', str(v).replace(',', '.')) or 0)
    except Exception:
        return 0.0


def build_reports() -> dict:
    """Пересчитывает generated-листы Долги и Отчёт из Общей. Возвращает сводку."""
    rows = read_all()
    unpaid = [r for r in rows if str(r.get('status', '')) in
              ('Новая', 'Перезвонить', 'Думает')]
    d_heads = ['ФИО ребенка', 'Телефон', 'Смена', 'Статус', 'Сумма', 'Дата перезвона']
    d_rows = [[r.get('fio_child', ''), r.get('phone', ''), r.get('shift', ''),
               r.get('status', ''), r.get('сумма', ''), r.get('callback_dt', '')]
              for r in unpaid]
    write_sheet_local('Долги', d_heads, d_rows)
    by_shift: dict = {}
    for r in rows:
        sh = str(r.get('shift', '') or '—')
        s = by_shift.setdefault(sh, {'всего': 0, 'оплачено': 0, 'долг': 0.0,
                                    'собрано': 0.0})
        s['всего'] += 1
        if str(r.get('status', '')) == 'Оплачено':
            s['оплачено'] += 1
            s['собрано'] += _sum_val(r.get('сумма', ''))
        elif str(r.get('status', '')) in ('Новая', 'Перезвонить', 'Думает'):
            s['долг'] += _sum_val(r.get('сумма', ''))
    o_heads = ['Смена', 'Всего', 'Оплачено', 'Должников', 'Собрано', 'Долг']
    o_rows = []
    for sh, s in by_shift.items():
        debtors = s['всего'] - s['оплачено']
        o_rows.append([sh, s['всего'], s['оплачено'], debtors,
                       int(s['собрано']), int(s['долг'])])
    write_sheet_local('Отчёт', o_heads, o_rows)
    return {'должников': len(d_rows), 'смен': len(o_rows)}


def upsert(data: dict) -> tuple[str, str, list[str]]:
    """Возвращает (действие, id, новые_колонки)."""
    from brain import fio_match
    import re
    data = validate_row(data)
    extra = data.get('extra', {}) or {}
    extra['обновлено'] = datetime.now().strftime('%d.%m.%Y %H:%M')
    data['extra'] = extra
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

    # Яндекс.Диск — источник правды: заливаем ВЕСЬ файл (дешево, ~9КБ).
    # Перед заливкой текущий remote уходит в бэкап (см. yandex_store).
    try:
        import yandex_store
        yandex_store.sync_after_change('upsert')
    except Exception as e:
        print(f'[Yandex] только локально ({e})')
    created = [k for k in new_cols if k not in [h.lower() for h in _headers(wb["Общая"])[:-len(new_cols)]]] if new_cols else []
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
    """Оставлено для совместимости: теперь заливает весь файл на Диск."""
    try:
        import yandex_store
        yandex_store.sync_after_change('update')
    except Exception as e:
        print(f'[Yandex] {e}')


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
    fields = dict(fields or {})
    fields['обновлено'] = datetime.now().strftime('%d.%m.%Y %H:%M')
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
            import yandex_store
            yandex_store.sync_after_change('delete')
        except Exception as e:
            print(f'[Yandex delete] {e}')
    return found


def delete_row_at(sheet: str, row1: int) -> bool:
    """Удаляет строку по номеру (1-based, шапка = 1) локально + заливка на Диск.

    Для строк-фрагментов без ID (ручное удаление через сайт).
    """
    wb = _ensure_wb()
    if sheet not in wb.sheetnames:
        return False
    ws = wb[sheet]
    if row1 < 2 or row1 > ws.max_row:
        return False
    ws.delete_rows(row1)
    wb.save(FILE)
    try:
        import yandex_store
        yandex_store.sync_after_change('delete-at')
    except Exception as e:
        print(f'[Yandex delete-at] {e}')
    return True


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


def _norm_cell(v) -> str:
    if v is None:
        return ''
    if isinstance(v, float) and v != v:  # NaN
        return ''
    return str(v)


def _google_write_row(sheet: str, row1: int, vals: list) -> None:
    """Оставлено для совместимости: построчные записи не нужны —
    весь файл заливается на Диск разом (см. конец apply_*)."""
    return None


def _google_append_row(sheet: str, vals: list) -> None:
    """Оставлено для совместимости: см. _google_write_row."""
    return None


def _google_ok() -> bool:
    return False


def apply_table_edits(sheet: str, heads: list, rows: list, recs: list) -> str:
    """Применяет правки таблицы: изменённые ячейки, новые и удалённые строки.

    Системные листы (Общая + сезоны) — по ID с зеркалированием в Общую и Google.
    Вольные листы (импорты) — чисто позиционно. Строки-фрагменты без ID —
    позиционно (правка/удаление) в любом листе.
    recs — записи вида {заголовок: значение} (уже без DataFrame).
    Возвращает сводку 'Правок: N, новых строк: M, удалено: K.'
    Generated-листы (Долги/Отчёт) только читаются — их пересчитывает кнопка.
    """
    if sheet in GENERATED:
        return 'лист generated — жми «📊 Пересчитать отчёты».'
    try:
        import yandex_store
        yandex_store.defer(True)
    except Exception:
        pass
    try:
        if sheet in SHEETS:
            rep = _apply_core_edits(sheet, heads, rows, recs)
        else:
            rep = _apply_free_edits(sheet, heads, rows, recs)
    finally:
        try:
            import yandex_store
            yandex_store.defer(False)
        except Exception:
            pass
    return rep


def _apply_core_edits(sheet: str, heads: list, rows: list, recs: list) -> str:
    key_of = {h: HEADER_TO_KEY.get(h, h.lower()) for h in (heads or [])}
    core_keys = [kk for kk, _ in CORE]
    norm = _norm_cell
    n_old = len(rows)
    upd, new_n, del_n = 0, 0, 0
    seen_ids = set()
    for i, rec in enumerate(recs):
        if i < n_old:
            cid = str(rows[i].get('id', ''))
            if not cid:
                continue  # фрагменты без ID — отдельным проходом ниже
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
    # фрагменты без ID — отдельным проходом по исходным строкам:
    # правка пишется позиционно, пропавшая строка удаляется позиционно.
    # Выполняем снизу вверх, чтобы удаления не сдвигали цели.
    frag_ops: list = []
    for j, r in enumerate(rows):
        if str(r.get('id', '')):
            continue
        old_sig = tuple(r.get(key_of[h], '') for h in (heads or []))
        if j < len(recs) and tuple(norm(recs[j].get(h)) for h in (heads or [])) == old_sig:
            continue
        if j < len(recs) and any(norm(recs[j].get(h)) for h in (heads or [])):
            frag_ops.append((j, 'upd', [norm(recs[j].get(h)) for h in (heads or [])]))
        else:
            frag_ops.append((j, 'del', []))
    for j, op, vals in sorted(frag_ops, reverse=True):
        if op == 'upd':
            wb = _ensure_wb()
            if sheet in wb.sheetnames:
                ws = wb[sheet]
                for col_i, v in enumerate(vals, start=1):
                    ws.cell(j + 2, col_i).value = v
                wb.save(FILE)
            if _google_ok():
                try:
                    _google_write_row(sheet, j + 2, vals)
                except Exception as e:
                    print(f'[Sheets write-at] {e}')
            upd += 1
        elif delete_row_at(sheet, j + 2):
            del_n += 1
    for r in rows:
        cid = str(r.get('id', ''))
        if cid and cid not in seen_ids and delete_by_id(cid):
            del_n += 1
    return f'Правок: {upd}, новых строк: {new_n}, удалено: {del_n}.'


def _apply_free_edits(sheet: str, heads: list, rows: list, recs: list) -> str:
    """Вольный лист (импорт): всё позиционно, без ID и зеркал."""
    norm = _norm_cell
    key_of = {h: HEADER_TO_KEY.get(h, h.lower()) for h in (heads or [])}
    data_recs = [rec for rec in recs if any(norm(rec.get(h)) for h in (heads or []))]
    n_old, m = len(rows), len(data_recs)
    upd, new_n, del_n = 0, 0, 0
    wb = _ensure_wb()
    if sheet not in wb.sheetnames:
        return 'Лист пропал локально — обнови из Google.'
    ws = wb[sheet]
    for i in range(min(n_old, m)):
        old = [rows[i].get(key_of[h], '') for h in (heads or [])]
        new = [norm(data_recs[i].get(h)) for h in (heads or [])]
        if new == old:
            continue
        for col_i, v in enumerate(new, start=1):
            ws.cell(i + 2, col_i).value = v
        wb.save(FILE)
        if _google_ok():
            try:
                _google_write_row(sheet, i + 2, new)
            except Exception as e:
                print(f'[Sheets write-at] {e}')
        upd += 1
    for j in range(n_old, m):
        vals = [norm(data_recs[j].get(h)) for h in (heads or [])]
        ws.append(vals)
        wb.save(FILE)
        if _google_ok():
            try:
                _google_append_row(sheet, vals)
            except Exception as e:
                print(f'[Sheets append] {e}')
        new_n += 1
    for k in range(n_old, m, -1):
        if delete_row_at(sheet, k + 1):
            del_n += 1
    return f'Правок: {upd}, новых строк: {new_n}, удалено: {del_n}.'


def set_shift(cid: str, shift: str) -> bool:
    return update_by_id(cid, {'shift': shift})


def add_column(name: str) -> list:
    wb = _ensure_wb()
    heads = _ensure_columns(wb, [name.strip().lower()[:30]])
    wb.save(FILE)
    try:
        import yandex_store
        yandex_store.sync_after_change('колонка')
    except Exception as e:
        print(f'[Yandex] {e}')
    return heads
