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


# Рабочие модели по приоритету: сначала сильные, потом лёгкие.
# (gemini-3.x не существуют — их вызов давал 404 и молча откатывался
# на regex, поэтому ИИ казался "тупым": всё валилось в комментарий.)
MODELS = ('gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-flash-latest',
          'gemini-flash-lite-latest', 'gemini-2.5-flash-lite')

PROMPT = """Ты секретарь-аналитик детского лагеря. Разбери текст в JSON.
Твоя работа — ИЗВЛЕЧЬ ВСЁ полезное в структуру, а не пересказать в комментарий.

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

ГЛАВНОЕ — extra (новые колонки таблицы):
- extra — это НЕ мусорка, а главный результат анализа. Выноси туда КАЖДЫЙ факт,
  который не лёг в базовые поля: аллергия, диагноз, школа, класс, скидка, сумма,
  источник (авито/инста/рекомендация), пожелания, размер_одежды, брат_сестра,
  адрес, кружок, смена_вторая, причина_скидки и ЛЮБОЕ другое полезное.
- Ключ — короткое русское слово маленькими буквами через подчёркивание,
  значение — строка сути (без воды).
- ЗАПРЕЩЕНО пихать факты в comment, если для них есть место в extra.
  comment — только ОДНА короткая фраза-суть (до 80 символов), например
  "хочет в зиму" или "оплата, чек есть". НЕ копируй туда весь входной текст.
- Если фактов много — создай МНОГО ключей extra (3-5 штук нормально),
  лучше лишняя колонка, чем потерянная информация.

ЦЕНЫ (рубли, лагерь Защитник): полная стоимость 20000, со скидкой 17000, по рекомендации 15000.
Правила сумм: если в тексте есть явная сумма — бери ее в extra сумма. Если явной суммы нет: "скидка/со скидкой" -> extra сумма "17000"; "по рекомендации/порекомендовал/рекомендация" -> extra сумма "15000" и extra причина_скидки — кто порекомендовал. Без скидок и сумм extra сумма не ставь.

ФОРМАТ ОТВЕТА (нарушение = брак):
- Ключи JSON СТРОГО английские, ровно эти 9: fio_child, parent_fio, phone,
  age, shift, status, callback_dt, comment, extra. НИКАКИХ русских ключей
  ("телефон", "сдвиг", "статус", "дополнительно" и т.п. — ЗАПРЕЩЕНЫ).
- Значения ФИО — title-case ("Борис", а НЕ "БОРИС" и не "ребёнка Борис"):
  вычищай служебные слова (зовут, ребёнка, мама, сын) из имён.
- "мама Лена" = parent_fio "Лена". "зовут ребёнка Борис" = fio_child "Борис".
  Слова "мама/папа" НИКОГДА не входят в имя; "зовут/ребёнка/сына/дочь"
  НИКОГДА не входят в имя.

Примеры:
Вход: "Позвонила мама Иванова Мария, сын Тимофей Иванов 9 лет, +7 900 123-45-67, хочет в зимнюю смену защитник, аллергия на орехи, учится в 3 классе 12 школы, просила перезвонить завтра в 15:00"
Выход: {{"fio_child":"Тимофей Иванов","parent_fio":"Иванова Мария","phone":"+79001234567","age":"9","shift":"Зима 26","status":"Перезвонить","callback_dt":"2026-09-27T15:00:00","comment":"хочет в зиму","extra":{{"аллергия":"на орехи","школа":"12, 3 класс"}}}}
Вход: "Тимофей Иванов оплатил зиму 15000, чек скинула мама, порекомендовал сосед Петров"
Выход: {{"fio_child":"Тимофей Иванов","parent_fio":"","phone":"","age":"","shift":"Зима 26","status":"Оплачено","callback_dt":"","comment":"оплата, чек есть","extra":{{"сумма":"15000","причина_скидки":"порекомендовал сосед Петров"}}}}
Вход: "ребёнок 10 лет, мама Лена, зовут ребёнка Борис, хотят в осеннюю смену, аллергия на сладкое, он по рекомендации Дамира Гусева, получается скидка должна быть, он из школы 55 Советского района"
Выход: {{"fio_child":"Борис","parent_fio":"Лена","phone":"","age":"10","shift":"Осень 26","status":"Новая","callback_dt":"","comment":"хочет в осень, скидка","extra":{{"аллергия":"на сладкое","школа":"55, Советский район","сумма":"15000","причина_скидки":"Дамир Гусев"}}}}
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
        for model in MODELS:
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
                    if '503' in s or 'UNAVAILABLE' in s or '500' in s \
                            or '504' in s or 'DEADLINE' in s or 'Timeout' in s:
                        time.sleep(2)
                        continue
                    # 404 и всё прочее — не застреваем, пробуем следующую
                    # модель (слабый lite в конце списка — страховка).
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


# Если слабая модель вернула русские ключи ("телефон", "сдвиг",
# "дополнительно") — чиним в канонические английские без потери данных.
KEY_ALIASES = {
    'фио': 'fio_child', 'ребенок': 'fio_child', 'ребёнок': 'fio_child',
    'имя': 'fio_child', 'дитя': 'fio_child', 'fio': 'fio_child',
    'родитель': 'parent_fio', 'мама': 'parent_fio', 'папа': 'parent_fio',
    'отец': 'parent_fio', 'мать': 'parent_fio',
    'телефон': 'phone', 'тел': 'phone',
    'возраст': 'age', 'лет': 'age',
    'сдвиг': 'shift', 'смена': 'shift',
    'статус': 'status',
    'комментарий': 'comment', 'комментар': 'comment',
    'дополнительно': 'extra', 'доп': 'extra', 'прочее': 'extra',
    'дата': 'callback_dt', 'перезвон': 'callback_dt',
}


def _normalize_keys(d: dict) -> dict:
    """Русские ключи модели -> английские. Каноника не затирается."""
    out = dict(d)
    for k in list(out.keys()):
        nk = KEY_ALIASES.get(str(k).strip().lower())
        if nk and nk not in out:
            out[nk] = out.pop(k)
        elif nk:
            out.pop(k, None)
    return out


def _clean_fio_value(v: str) -> str:
    """Вычищает служебные слова из имени: 'зовут ребёнка Борис' -> 'Борис'."""
    words = [w for w in str(v).split()
             if w.lower() not in ('зовут', 'ребенка', 'ребёнка', 'ребенок',
                                  'ребёнок', 'сына', 'дочь', 'дочку', 'мама',
                                  'папа', 'мать', 'отец', 'сын', 'дочка',
                                  'лет', 'год', 'года', 'годик')]
    return titlecase_fio(' '.join(words)) if words else ''


BROKEN_FIO_WORDS = frozenset({
    'лет', 'год', 'года', 'годик', 'зовут', 'мама', 'папа', 'мать', 'отец',
    'ребенка', 'ребёнка', 'ребенок', 'ребёнок', 'сына', 'дочь', 'дочку',
    'дочка', 'сын', 'хотят', 'хочет', 'ребёнок',
})


def backstop_fio(text: str, data: dict) -> dict:
    """Добивка ФИО из текста, если значение пустое или с мусором.

    Хорошие значения модели НЕ трогает — только пустые/сломанные.
    """
    def broken(v: str) -> bool:
        if not str(v or '').strip():
            return True
        toks = [w.lower() for w in str(v).split()]
        return any(w in BROKEN_FIO_WORDS for w in toks) or len(toks) > 3

    if broken(data.get('fio_child', '')):
        m = re.search(
            r'[Зз]овут\s+(?:реб[её]нка|сына|дочь|дочку|девочку|мальчика)\s+'
            r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2})', text)
        if not m:
            m = re.search(
                r'(?:сын|дочь|дочка|реб[её]нок|мальчик|девочка)\s+'
                r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)',
                text)
        if m:
            data['fio_child'] = _clean_fio_value(m.group(1))
    if broken(data.get('parent_fio', '')):
        m = re.search(
            r'(?:[Мм]ама|[Пп]апа|[Мм]ать|[Оо]тец)\s+'
            r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)', text)
        if m:
            cand = _clean_fio_value(m.group(1))
            if cand and cand != data.get('fio_child'):
                data['parent_fio'] = cand
            elif not cand:
                data['parent_fio'] = ''
    # Явные маркеры в тексте — авторитетны и бьют значения модели:
    # "мама Лена" + "зовут ребёнка Борис" дают точную пару, даже если
    # модель всё перепутала ("Лет Мама Лена" / "Зовут Ребёнка Борис").
    m_kid = re.search(
        r'[Зз]овут\s+(?:реб[её]нка|сына|дочь|дочку|девочку|мальчика)\s+'
        r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2})', text)
    m_par = re.search(
        r'(?:[Мм]ама|[Пп]апа|[Мм]ать|[Оо]тец)\s+'
        r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)', text)
    def _same_person(a: str, b: str) -> bool:
        """Одна и та же персона (учитывает падежи: Тимофей/Тимофея)."""
        ta = [w.lower() for w in str(a).split()]
        tb = [w.lower() for w in str(b).split()]
        return any(x[:5] == y[:5] for x in ta if len(x) > 3
                   for y in tb if len(y) > 3)

    if m_kid:
        kid = _clean_fio_value(m_kid.group(1))
        if kid and data.get('fio_child') != kid \
                and not _same_person(data.get('fio_child', ''), kid):
            if data.get('parent_fio') == kid:
                data['parent_fio'] = data['fio_child']  # перестановка
            data['fio_child'] = kid
    if m_par:
        par = _clean_fio_value(m_par.group(1))
        if par and data.get('parent_fio') != par \
                and not _same_person(data.get('parent_fio', ''), par):
            if data.get('fio_child') == par and not m_kid:
                data['fio_child'] = data['parent_fio']  # перестановка
            data['parent_fio'] = par
    return data


def backstop_extra(text: str, data: dict) -> dict:
    """Детерминированный добор фактов в extra, если ИИ их пропустил.

    Явные паттерны текста (аллергия на X, школа N, рекомендация, явная
    сумма) авторитетны и перезаписывают галлюцинации модели — текст
    точнее. Производные дефолты (15000/17000) только заполняют пустоты.
    Значения модели НЕ трогаем там, где текст молчит.
    """
    t = text.lower()
    ex = data.setdefault('extra', {})
    if not isinstance(ex, dict):
        ex = data['extra'] = {}
    has = {k.lower() for k in ex if str(ex[k]).strip()}

    def put(k: str, v: str, force: bool = False):
        if v and str(v).strip() and (force or k not in has):
            ex[k] = str(v).strip()[:200]
            has.add(k)

    m = re.search(r'аллерги[яи]\s+на\s+([а-яёa-z]+(?:\s+[а-яёa-z]+)?)', t)
    if m:
        words = m.group(1).split()
        while words and words[-1] in ('также', 'еще', 'ещё', 'и', 'а', 'но',
                                      'вот', 'же', 'он', 'она', 'есть'):
            words.pop()
        if words:
            put('аллергия', 'на ' + ' '.join(words[:2]), force=True)
    elif re.search(r'\bаллерги[яик]', t):
        put('аллергия', 'есть (уточнить)')
    parts = []
    m = re.search(r'(?:школ[аыи]\s*)(\d{1,3})', t)
    if m:
        parts.append(m.group(1))
    if 'советского района' in t or 'советский район' in t:
        parts.append('Советский район')
    else:
        m = re.search(r'([а-яё]+)\s+район', t)
        if m:
            parts.append(titlecase_fio(m.group(1) + ' район'))
    m = re.search(r'(\d{1,2})\s*класс', t)
    if m:
        parts.append(m.group(1) + ' класс')
    if parts:
        put('школа', ', '.join(parts))
    m = re.search(r'по\s+рекомендации\s+([а-яё]+\s+[а-яё]+(?:\s+[а-яё]+)?)', t)
    if not m:
        m = re.search(r'рекомендаци[яи]\s+([а-яё]+\s+[а-яё]+)', t)
    if not m:
        m = re.search(r'порекомендовал[аи]?\s+([а-яё]+\s+[а-яё]+)', t)
    if m:
        words = m.group(1).split()
        while words and words[-1] in ('получается', 'значит', 'вот', 'типа',
                                      'мол', 'также', 'еще', 'ещё'):
            words.pop()
        if words:
            put('причина_скидки', titlecase_fio(' '.join(words[:2])),
                force=True)
    m = re.search(r'(\d{4,6})\s*(?:руб|р\.|₽|тысяч|т\.р|оплат\w*)', t)
    if not m:
        m = re.search(r'(?:оплат\w*|сумм\w*|цен\w*|итого|всего|скидк\w*)[^\d]{0,10}(\d{4,6})', t)
    if m:
        put('сумма', m.group(1), force=True)
    elif re.search(r'по\s+рекомендации|рекомендаци|порекомендовал', t):
        put('сумма', '15000')
    elif re.search(r'скидк', t):
        put('сумма', '17000')
    return data


# Синонимы extra-ключей: опечатки и варианты ИИ сливаются в канон
# (вместо вечной новой колонки на каждую опечатку). Пробелы→подчёркивание.
EXTRA_SYN = {
    'оплата': 'сумма', 'цена': 'сумма', 'стоимость': 'сумма',
    'ценник': 'сумма', 'сума': 'сумма', 'оплочено': 'сумма',
    'суммма': 'сумма', 'оплачено': 'сумма',
    'скидочка': 'скидка', 'скидон': 'скидка', 'скидки': 'скидка',
    'алергия': 'аллергия', 'алергия': 'аллергия', 'аллергии': 'аллергия',
    'школа_': 'школа', 'класс_': 'класс', 'школу': 'школа',
    'рекомендация': 'причина_скидки',
    'причина скидки': 'причина_скидки', 'причинаскидки': 'причина_скидки',
    'дата перезвона': 'callback_dt', 'телефон': 'phone',
}


def _canon_extra_key(k: str) -> str:
    kk = re.sub(r'\s+', '_', str(k).strip().lower())[:30]
    return EXTRA_SYN.get(kk, kk)


def parse_client_text(text: str) -> dict:
    """Gemini -> локально. Плюс нормализация ключей и добор extra."""
    d = parse_with_gemini(text)
    if d:
        d = _normalize_keys(d)
        # чиним имена: модель иногда кладёт "зовут ребёнка Борис" целиком
        for fk in ('fio_child', 'parent_fio'):
            if d.get(fk):
                fixed = _clean_fio_value(d[fk])
                if fixed:
                    d[fk] = fixed
        for k in CORE_KEYS:
            d.setdefault(k, '')
        d.setdefault('extra', {})
        if not isinstance(d['extra'], dict):
            d['extra'] = {}
        # чистка extra: только строки, короткие ключи + синонимы в канон
        clean = {}
        for k, v in d['extra'].items():
            kk = _canon_extra_key(k)
            if kk and kk not in CORE_KEYS and str(v).strip():
                if kk in clean and clean[kk] != str(v).strip()[:200]:
                    clean[kk] = clean[kk] + '; ' + str(v).strip()[:200]
                else:
                    clean[kk] = str(v).strip()[:200]
        d['extra'] = clean
        d = backstop_extra(text, d)
        d = backstop_fio(text, d)
        if not d.get('comment'):
            d['comment'] = text[:80]
        else:
            # comment — короткая суть, не простыня: режем до 120 символов
            d['comment'] = str(d['comment'])[:120]
        return d
    d = parse_local(text)
    d = backstop_extra(text, d)
    return backstop_fio(text, d)


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
