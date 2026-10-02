"""Напоминания: только локально (reminders.json).

Раньше дублировались в Google Calendar — после переезда на Яндекс.Диск
календаря-провайдера нет, поэтому всё живёт в локальном файле.
Показываются на сайте блоком «⏰ Пора перезвонить».
"""
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
    data.append(item)
    _save(data)
    return item


def clear_all() -> dict:
    """Сносит ВСЕ локальные напоминания. Возвращает счетчики."""
    data = _load()
    n_local = len(data)
    _save([])
    return {'local': n_local, 'calendar': 0, 'tasks': 0,
            'no_event_id': 0, 'tasks_err': ''}


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
    """Снимает локальные напоминания человека. Возвращает счетчики."""
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
    _save(keep)
    return {'local': len(gone), 'calendar': 0}
