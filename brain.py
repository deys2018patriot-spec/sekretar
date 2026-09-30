"""Мозг v2: Gemini с few-shot + гибрид с regex. Умеет новые колонки через extra."""
import os
import re
import json
from datetime import datetime, timedelta
from difflib import SequenceMatcher

MONTHS_RU = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
    'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
}
STATUS_KEYWORDS = {
    'перезвонил': 'Перезвонил', 'дозвонился': 'Перезвонил', 'уже позвонил': 'Перезвонил',
    'перезвонить': 'Перезвонить', 'перезвон': 'Перезвонить',
    'набери': 'Перезвонить', 'позвони': 'Перезвонить',
    'отправить инфу': 'Перезвонить', 'отправь инфу': 'Перезвонить', 'скинуть инфу': 'Перезвонить',
    'в течение часа': 'Перезвонить', 'в течении часа': 'Перезвонить',
    'лид': 'Новая',
    'оплатил': 'Оплачено', 'оплата': 'Оплачено', 'оплачен': 'Оплачено', 'чек': 'Оплачено',
    'отказ': 'Отказ', 'отказал': 'Отказ', 'не хочет': 'Отказ', 'не едет': 'Отказ', 'передумал': 'Отказ',
    'приехал': 'Приехал', 'заехал': 'Приехал',
    'думает': 'Думает', 'посоветуется': 'Думает',
}

CORE_KEYS = ['fio_child', 'parent_fio', 'phone', 'age', 'shift', 'status', 'callback_dt', 'comment']

# Канонические смены (вкладки) + все варианты как их могут назвать вслух
SHIFTS = ['Осень 26', 'Зима 26', 'Весна 27']
SHIFT_ALIASES = {
    'Осень 26': ['осень 26', 'защитник осень', 'осенняя смена', 'осеннюю смену', 'осень'],
    'Зима 26': ['зима 26', 'защитник зима', 'зимняя смена', 'зимнюю смену', 'зимняя', 'зиму', 'зима'],
    'Весна 27': ['весна 27', 'защитник весна', 'весенняя смена', 'весеннюю смену', 'весенняя', 'весну', 'весна'],
}


def normalize_shift(text: str) -> str:
    t = text.lower()
    for canon, aliases in SHIFT_ALIASES.items():
        for a in sorted(aliases, key=len, reverse=True):
            if a in t:
                return canon
    return ''


def titlecase_fio(s: str) -> str:
    return ' '.join(w.capitalize() for w in s.strip().split())


# Английская раскладка -> русская (когда напечатали "yflj" вместо "надо")
_LAYOUT = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?",
    "йцукенгшщзхъфывапролджэячсмитьбю.ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,")


def fix_layout(text: str) -> str:
    """Если напечатано в английской раскладке — переводим. Иначе как было."""
    if not text or re.search(r'[а-яёА-ЯЁ]', text):
        return text
    conv = text.translate(_LAYOUT)
    if len(re.findall(r'[а-яёА-ЯЁ]', conv)) >= 3:
        return conv
    return text


def parse_callback_datetime(text: str, now: datetime = None):
    now = now or datetime.now()
    t = text.lower()
    # "в течение/течении часа" -> +1 час; "сегодня" без времени -> +2 часа
    if re.search(r'в\s+течени[еи]\s+часа', t):
        return now + timedelta(hours=1)
    if re.search(r'в\s+течение\s+дня|сегодня', t):
        m2 = re.search(r'(\d{1,2})[:.](\d{2})', t)
        if m2:
            dt = now.replace(hour=int(m2.group(1)), minute=int(m2.group(2)), second=0, microsecond=0)
            return dt if dt > now else dt + timedelta(days=1)
        return now + timedelta(hours=2)
    m = re.search(r'через\s+(\d+)\s*минут', t)
    if m:
        return now + timedelta(minutes=int(m.group(1)))
    m = re.search(r'через\s+(\d+)\s*час', t)
    if m:
        return now + timedelta(hours=int(m.group(1)))
    m = re.search(r'через\s+(\d+)\s*дн', t)
    if m:
        return now + timedelta(days=int(m.group(1)))
    m = re.search(r'через\s+(\d+)\s*недел', t)
    if m:
        return now + timedelta(weeks=int(m.group(1)))
    m = re.search(r'(завтра|послезавтра)?\s*(?:в|к)\s*(\d{1,2})[:.\s](\d{2})', t)
    if m:
        day_word, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
        base = now + timedelta(days=1) if day_word == 'завтра' else (now + timedelta(days=2) if day_word == 'послезавтра' else now)
        dt = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not day_word and dt <= now:
            dt += timedelta(days=1)
        return dt
    m = re.search(r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)', t)
    if m:
        day, month = int(m.group(1)), MONTHS_RU[m.group(2)]
        tm = re.search(r'(\d{1,2})[:.](\d{2})', t)
        hh, mm = (int(tm.group(1)), int(tm.group(2))) if tm else (12, 0)
        try:
            dt = datetime(now.year, month, day, hh, mm)
            if dt < now:
                dt = datetime(now.year + 1, month, day, hh, mm)
            return dt
        except ValueError:
            pass
    return None


def extract_phone(text: str) -> str:
    phones = re.findall(r'\+?\d[\d\s\-\(\)]{9,}\d', text)
    if not phones:
        return ''
    p = re.sub(r'[\s\-\(\)]', '', phones[0])
    # нормализация RU: 8... / 9... -> +7...
    d = re.sub(r'\D', '', p)
    if len(d) == 11 and d[0] in '78':
        return '+7' + d[1:]
    if len(d) == 10:
        return '+7' + d
    return p if p.startswith('+') else '+' + d if d else ''


def parse_local(text: str) -> dict:
    now = datetime.now()
    phone = extract_phone(text)
    fio, parent_fio = '', ''
    # регистронезависимый поиск: "мальчик вася пупкин" тоже находим
    m_child = re.search(r'(?:сын|дочь|дочка|реб[её]нок|мальчик|девочка)\s+([А-Яа-яЁё]+\s+[А-Яа-яЁё]+(?:\s+[А-Яа-яЁё]+)?)', text, re.IGNORECASE)
    if m_child:
        fio = titlecase_fio(m_child.group(1))
    all_fios = re.findall(r'[А-Яа-яЁё]+\s+[А-Яа-яЁё]+(?:\s+[А-Яа-яЁё]+)?', text)
    # чистим мусор: отбрасываем совпадения со служебными/ролевыми словами
    STOP = {'отправить', 'отправь', 'скинуть', 'сегодня', 'течении', 'течение', 'часа', 'инфу', 'инфо', 'лид'}
    ROLE = {'мальчик', 'девочка', 'сын', 'дочь', 'дочка', 'ребенок', 'мама', 'мать', 'папа', 'отец', 'бабушка', 'дедушка'}
    VERBS = {'оплатил', 'оплатила', 'оплачено', 'оплата', 'отказался', 'отказалась', 'отказ',
             'приехал', 'приехала', 'заехал', 'заехала', 'думает', 'перезвонить', 'перезвони',
             'позвонила', 'позвонил', 'позвоните', 'набери', 'позвони', 'хочет', 'хотят',
             'едет', 'не', 'просила', 'просил', 'чек', 'скинула', 'скинул',
             'запиши', 'записать', 'внеси', 'внести', 'добавь', 'добавить', 'перенеси', 'перенести'}
    SEASON = {'осень', 'осенью', 'осенняя', 'осеннюю', 'зима', 'зиму', 'зимой', 'зимняя', 'зимнюю',
              'весна', 'весну', 'весной', 'весенняя', 'весеннюю', 'смена', 'смену', 'смены',
              'защитник', '26', '27', 'в'}
    JUNK = STOP | ROLE | VERBS | SEASON
    clean = []
    for c in all_fios:
        words = c.lower().split()
        # срезаем служебные слова по краям: "Тимофей Иванов оплатил" -> "Тимофей Иванов"
        while words and words[0] in JUNK:
            words.pop(0)
        while words and words[-1] in JUNK:
            words.pop()
        if len(words) < 2:
            continue
        clean.append(titlecase_fio(' '.join(words[:3])))
    all_fios = clean
    if not fio and all_fios:
        fio = all_fios[0]
    if not fio:
        # одиночное имя в начале ("Дамир, 11 лет..."): первое слово не мусор -> имя ребенка
        m1 = re.match(r'\s*([А-Яа-яЁё]+)', text)
        if m1 and m1.group(1).lower() not in JUNK:
            fio = titlecase_fio(m1.group(1))
    if len(all_fios) >= 2 and fio:
        for cand in all_fios:
            if cand != fio:
                parent_fio = cand
                break
    m_mama = re.search(r'(?:мама|мать)\s+([А-Яа-яЁё]+\s+[А-Яа-яЁё]+)', text, re.IGNORECASE)
    if m_mama and not parent_fio:
        cand = titlecase_fio(m_mama.group(1))
        if cand != fio:
            parent_fio = cand
    # "ольга мама" (имя перед словом мама): "X мама" -> родитель X
    if not parent_fio:
        m_rev = re.search(r'([А-Яа-яЁё]+)\s+мама', text, re.IGNORECASE)
        if m_rev:
            parent_fio = titlecase_fio(m_rev.group(1))
            # если fio случайно схватил "Ольга Мама" - сбрасываем, ребенок отдельно
            if fio.lower().endswith('мама'):
                fio = ''
    # "мама Гульнара" (одно имя после мама) -> родитель
    if not parent_fio:
        m1 = re.search(r'(?:мама|мать|папа)\s+([А-Яа-яЁё]+)', text, re.IGNORECASE)
        if m1:
            parent_fio = titlecase_fio(m1.group(1))
    age = ''
    m = re.search(r'(\d{1,2})\s*(лет|год|г\.)', text.lower())
    if m:
        age = m.group(1)
    shift = normalize_shift(text)
    status = 'Новая'
    for kw, st in STATUS_KEYWORDS.items():
        if kw in text.lower():
            status = st
            break
    cb = parse_callback_datetime(text, now)
    if cb and status == 'Новая':
        status = 'Перезвонить'
    return {'fio_child': fio, 'phone': phone, 'age': age, 'shift': shift,
            'status': status, 'callback_dt': cb.isoformat() if cb else '',
            'comment': text.strip()[:500], 'parent_fio': parent_fio, 'extra': {}}


PROMPT = """Ты секретарь детского лагеря. Разбери текст в JSON.

СТРОГОЕ правило ФИО:
- fio_child = РЕБЕНОК. Ищи после слов сын/дочь/дочка/ребенок/мальчик/девочка. Пример: "сын Тимофей Иванов" -> fio_child="Тимофей Иванов".
- parent_fio = родитель. Ищи после слов мама/папа/мать/отец/позвонила. Пример: "Позвонила мама Иванова Мария" -> parent_fio="Иванова Мария".
- Если в тексте одно ФИО и рядом "мама/папа" — это родитель, а ребенка тогда оставь пустым, НЕ дублируй.
- Никогда не ставь маму в fio_child если есть отдельный ребенок.

Телефон: нормализуй к +7XXXXXXXXXX (10 цифр после +7).

Смена (строго одно из): "Осень 26", "Зима 26", "Весна 27", иначе "".
Соответствия: "осенняя/осень/защитник осень" -> "Осень 26"; "зимняя смена/зима/защитник зима" -> "Зима 26"; "весенняя/весна/защитник весна" -> "Весна 27".

Статус (одно): Новая, Перезвонить, Перезвонил, Думает, Оплачено, Отказ, Приехал.
- "перезвони/набери/завтра в" -> Перезвонить
- "уже перезвонил/дозвонился/поговорил" -> Перезвонил (звонок состоялся, напоминание не нужно)
- "оплатил/чек/внес" -> Оплачено
- "отказ/не едет/передумал" -> Отказ

callback_dt: дата-время перезвона в ISO (YYYY-MM-DDTHH:MM:SS) или "". Сейчас {now}.
Примеры: "завтра в 15:00" при now 2026-09-26 -> "2026-09-27T15:00:00". "через 2 часа" -> now+2ч.

extra: ВСЕ остальное полезное как новые колонки: аллергия, диагноз, школа, скидка, сумма, источник (авито/инста), пожелания, размер одежды и т.п. Ключ - короткое русское слово маленькими буквами, значение - строка. Если ничего нет -> {{}}.

ЦЕНЫ (рубли, лагерь Защитник): полная стоимость 20000, со скидкой 17000, по рекомендации 15000.
Правила сумм: если в тексте есть явная сумма — бери ее в extra сумма. Если явной суммы нет: "скидка/со скидкой" -> extra сумма "17000"; "по рекомендации/порекомендовал/рекомендация" -> extra сумма "15000" и extra причина_скидки — кто порекомендовал. Без скидок и сумм extra сумма не ставь.

Примеры:
Вход: "Позвонила мама Иванова Мария, сын Тимофей Иванов 9 лет, +7 900 123-45-67, хочет в зимнюю смену защитник, аллергия на орехи, просила перезвонить завтра в 15:00"
Выход: {{"fio_child":"Тимофей Иванов","parent_fio":"Иванова Мария","phone":"+79001234567","age":"9","shift":"Зима 26","status":"Перезвонить","callback_dt":"2026-09-27T15:00:00","comment":"хочет в зимнюю смену","extra":{{"аллергия":"на орехи"}}}}
Вход: "Тимофей Иванов оплатил зиму 15000, чек скинула мама"
Выход: {{"fio_child":"Тимофей Иванов","parent_fio":"","phone":"","age":"","shift":"Зима 26","status":"Оплачено","callback_dt":"","comment":"оплата 15000, чек есть","extra":{{"сумма":"15000"}}}}
Вход: {text}
Сейчас: {now}
Ответь ТОЛЬКО JSON.
"""


def parse_with_gemini(text: str) -> dict | None:
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        return None
    try:
        import time
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        prompt = PROMPT.format(text=text, now=datetime.now().isoformat())
        cfg = types.GenerateContentConfig(
            temperature=0.1, response_mime_type='application/json',
            http_options=types.HttpOptions(
                timeout=20000,
                retry_options=types.HttpRetryOptions(attempts=1)))
        resp = None
        last_err = None
        for model in ('gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-flash-lite-latest', 'gemini-3.1-flash-lite'):
            for attempt in range(2):
                try:
                    resp = client.models.generate_content(
                        model=model, contents=prompt, config=cfg)
                    break
                except Exception as e:
                    last_err = e
                    s = str(e)
                    if '429' in s or 'RESOURCE_EXHAUSTED' in s or 'quota' in s.lower():
                        break  # квота на сегодня — сразу офлайн, без ожидания
                    if '503' in s or 'UNAVAILABLE' in s or '500' in s:
                        time.sleep(2)
                        continue
                    if '404' not in s and 'NOT_FOUND' not in s:
                        raise
                    break
            if resp is not None:
                break
        if resp is None:
            raise last_err or RuntimeError('no model')
        raw = (resp.text or '').strip().replace('```json', '').replace('```', '').strip()
        data = json.loads(raw)
        # гибрид: добиваем телефон и дату regex-ом если ИИ пропустил
        if not data.get('phone'):
            ph = extract_phone(text)
            if ph:
                data['phone'] = ph
        if not data.get('callback_dt'):
            cb = parse_callback_datetime(text)
            if cb:
                data['callback_dt'] = cb.isoformat()
                if data.get('status', 'Новая') == 'Новая':
                    data['status'] = 'Перезвонить'
        return data
    except Exception as e:
        print(f'[Gemini] fallback: {e}')
        return None


def parse_client_text(text: str) -> dict:
    """Gemini -> локально."""
    d = parse_with_gemini(text)
    if d:
        for k in CORE_KEYS:
            d.setdefault(k, '')
        d.setdefault('extra', {})
        if not isinstance(d['extra'], dict):
            d['extra'] = {}
        # чистка extra: только строки, короткие ключи
        clean = {}
        for k, v in d['extra'].items():
            kk = str(k).strip().lower()[:30]
            if kk and kk not in CORE_KEYS and str(v).strip():
                clean[kk] = str(v).strip()[:200]
        d['extra'] = clean
        if not d.get('comment'):
            d['comment'] = text[:300]
        return d
    return parse_local(text)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def fio_tokens(s: str) -> set:
    return set(s.lower().strip().split())


def fio_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    ta, tb = fio_tokens(a), fio_tokens(b)
    if not ta or not tb:
        return False
    if {w for w in ta & tb if len(w) > 2}:
        return True
    return similarity(a, b) > 0.75


def find_duplicates(new: dict, rows: list[dict]) -> list[dict]:
    out = []
    new_phone = re.sub(r'\D', '', new.get('phone', ''))
    new_fio = new.get('fio_child', '')
    for r in rows:
        r_phone = re.sub(r'\D', '', r.get('phone', ''))
        if new_phone and r_phone and new_phone[-7:] == r_phone[-7:]:
            out.append((1.0, r))
        elif new_fio and r.get('fio_child') and fio_match(new_fio, r['fio_child']):
            out.append((0.9, r))
    out.sort(reverse=True, key=lambda x: x[0])
    return [r for _, r in out]
