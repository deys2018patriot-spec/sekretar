"""Веб-запуск: секреты из env + восстановление clients.xlsx из Google Sheets.

Вызывается ПЕРВЫМ из streamlit_app.py (до brain/storage/agent).
Ничего в существующих .py не меняет, только читает их публичные функции.
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def _write_if_missing(path: str, content: str) -> bool:
    if os.path.exists(path):
        return False
    if not content:
        return False
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content.strip())
    return True


def load_secrets() -> dict:
    """Секреты из окружения (Hugging Face Spaces) в файлы/переменные.

    Возвращает словарь с именами ключей (НЕ значениями) для диагностики.
    """
    done = {'gemini_key': False, 'token_json': False, 'sheet_id': False}

    gemini_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if gemini_key:
        os.environ['GEMINI_API_KEY'] = gemini_key
        done['gemini_key'] = True
    else:
        local_key = os.path.join(BASE, 'gemini.key')
        if os.path.exists(local_key):
            try:
                os.environ['GEMINI_API_KEY'] = open(local_key, encoding='utf-8').read().strip()
                done['gemini_key'] = True
            except Exception:
                pass

    token_json = os.environ.get('GOOGLE_TOKEN_JSON', '').strip()
    if token_json:
        done['token_json'] = _write_if_missing(os.path.join(BASE, 'token.json'), token_json)
        # token.json уже мог существовать (локальный режим) — это тоже ок
        if os.path.exists(os.path.join(BASE, 'token.json')):
            done['token_json'] = True
    elif os.path.exists(os.path.join(BASE, 'token.json')):
        done['token_json'] = True

    sheet_id = os.environ.get('GOOGLE_SHEET_ID', '').strip()
    if sheet_id:
        done['sheet_id'] = _write_if_missing(os.path.join(BASE, 'sheet.id'), sheet_id)
        if os.path.exists(os.path.join(BASE, 'sheet.id')):
            done['sheet_id'] = True
    elif os.path.exists(os.path.join(BASE, 'sheet.id')):
        done['sheet_id'] = True

    return done


def pull_google_to_local() -> dict:
    """Если clients.xlsx отсутствует, а Google подключен — скачать 'Общая' локально.

    Использует только чтение Google Sheets API + запись через openpyxl
    (минимум дублированной логики, storage.py не трогаем).
    Возвращает {'ok': bool, 'rows': int, 'reason': str}.
    """
    import storage

    xlsx = os.path.join(BASE, 'clients.xlsx')
    if os.path.exists(xlsx) and os.path.getsize(xlsx) > 0:
        return {'ok': True, 'rows': -1, 'reason': 'локальный файл уже есть'}
    try:
        import google_sync
    except Exception as e:
        return {'ok': False, 'rows': 0, 'reason': f'нет google_sync: {e}'}
    try:
        sid = google_sync.get_sheet_id()
    except Exception as e:
        return {'ok': False, 'rows': 0, 'reason': f'нет sheet id: {e}'}
    if not sid:
        return {'ok': False, 'rows': 0, 'reason': 'нет GOOGLE_SHEET_ID'}
    if not os.path.exists(os.path.join(BASE, 'token.json')) and not os.environ.get('GOOGLE_TOKEN_JSON', '').strip():
        return {'ok': False, 'rows': 0, 'reason': 'нет token.json'}

    try:
        svc = google_sync._service('sheets', 'v4')
        res = svc.spreadsheets().values().get(
            spreadsheetId=sid, range='Общая!A:ZZ').execute()
        values = res.get('values', [])
    except Exception as e:
        return {'ok': False, 'rows': 0, 'reason': f'ошибка чтения Sheets: {e}'}
    if not values:
        return {'ok': False, 'rows': 0, 'reason': 'лист Общая пуст'}

    header = [str(x or '').strip() for x in values[0]]
    data_rows = [r for r in values[1:] if any(r)]
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = 'Общая'
        ws.append(header if header else [h for _, h in storage.CORE])
        for r in data_rows:
            ws.append(list(r) + [''] * max(0, len(ws[1]) - len(r)))
        for s in storage.SHEETS[1:]:
            if s not in wb.sheetnames:
                wb.create_sheet(s).append(list(ws[1][c].value for c in range(len(ws[1]))))
        wb.save(xlsx)
    except Exception as e:
        return {'ok': False, 'rows': 0, 'reason': f'ошибка записи xlsx: {e}'}
    return {'ok': True, 'rows': len(data_rows), 'reason': 'восстановлено из Google Sheets'}


def bootstrap() -> dict:
    """Одна точка входа для streamlit_app.py. Возвращает отчет (без секретов)."""
    secrets = load_secrets()
    restore = pull_google_to_local()
    return {'secrets': secrets, 'restore': restore}
