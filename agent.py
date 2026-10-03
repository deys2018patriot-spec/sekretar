"""Агент: ИИ выполняет команды по таблицам (править/переносить/удалять/колонки).
Песочница: только папка secretary + Яндекс.Диск. Дальше ноута не лезет.
"""
import os
import re
import json
from datetime import datetime
BASE = os.path.dirname(os.path.abspath(__file__))
RULES_FILE = os.path.join(BASE, 'rules.json')


def get_rules() -> list[str]:
    import json
    if os.path.exists(RULES_FILE):
        try:
            return json.load(open(RULES_FILE, encoding='utf-8'))
        except Exception:
            return []
    return []


def save_rule(text: str) -> int:
    import json
    rules = get_rules()
    text = text.strip()
    if text and text not in rules:
        rules.append(text)
        json.dump(rules, open(RULES_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return len(rules)

AGENT_MODELS = ('gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-flash-latest',
                'gemini-flash-lite-latest')

SYSTEM = """Ты агент-аналитик с ПОЛНЫМ доступом к таблицам лагеря. Верни ТОЛЬКО JSON.
Ты умеешь не только править ячейки, но и развивать структуру: создавать колонки
и новые таблицы-листы, анализировать данные.

Доступные действия (actions - список):
- {"tool":"find","query":"Иванов"} — найти строки
- {"tool":"stats"} — сводка: сколько всего, по сменам и статусам (для вопросов "сколько/анализ/сводка")
- {"tool":"update","query":"Иванов","fields":{"status":"Оплачено"}} — обновить найденные
- {"tool":"update_id","id":"123456","fields":{"shift":"Зима 26"}} — обновить по ID
- {"tool":"bulk_update","query":"Зима 26","fields":{"status":"Оплачено"}} — обновить ВСЕХ найденных разом (больше 10 — откажу и скажу число)
- {"tool":"move","query":"Иванов","shift":"Зима 26"} — перенести в смену
- {"tool":"delete","query":"Иванов"} — удалить найденные
- {"tool":"add_column","name":"аллергия"} — новая колонка во всех листах
- {"tool":"create_table","name":"Должники","header":["ФИО","Сумма"],"rows":[["Иванов",5000]]} — НОВЫЙ лист-таблица (создавай, когда просят "создай таблицу/список/лист" или когда данные не ложатся в клиентов: например отдельный учёт, долги, отчёт)
- {"tool":"remind","query":"Иванов","when":"2026-09-27T15:00:00"} — напоминание на сайте (блок «Пора перезвонить»)
- {"tool":"clear_reminders"} — удалить ВСЕ локальные напоминания
- {"tool":"remember","text":"текст правила"} — запомнить бизнес-правило на будущее
- {"tool":"clarify"} — если из команды непонятно кого/что делать
Поля fields: fio_child,parent_fio,phone,age,shift,status,callback_dt,comment + ЛЮБЫЕ новые (маленькими русскими словами через подчёркивание: аллергия, школа, сумма, источник, ...).
ГЛАВНОЕ ПРАВИЛО СТРУКТУРЫ: новую информацию (аллергия, школа, сумма, скидка, пожелание, размер, адрес — всё что не базовое поле) клади в fields КАК НОВУЮ КОЛОНКУ. Таблица сама создаст колонку. ЗАПРЕЩЕНО сваливать факты в comment одной строкой — comment только короткая суть (до 80 символов), факты живут в отдельных полях.
Если команда звучит как "запиши что у Иванова аллергия на орехи" — это update с полем {"аллергия":"на орехи"}, а НЕ comment.
Если команда просит учёт, которого нет в колонках (долги, отчёт, список) — создавай create_table с понятным header и rows.
Статусы: Новая, Перезвонить, Перезвонил, Думает, Оплачено, Отказ, Приехал. "Перезвонил" = звонок состоялся (напоминание снимается само). Смены строго: Осень 26, Зима 26, Весна 27 (понимай "зимняя смена/зима/защитник зима" как "Зима 26" и т.п.).
ЦЕНЫ (рубли): полная 20000, со скидкой 17000, по рекомендации 15000. В полях extra сумма/скидка/причина_скидки используй их: "со скидкой" без суммы -> сумма "17000"; "по рекомендации" -> сумма "15000" + кто порекомендовал; явная сумма важнее.
НИКОГДА не возвращай пустой actions. Если команда — указание/правило ("сумму пиши до скидки", "запомни что..."), верни {"tool":"remember"}. Если непонятно кого — верни clarify.
Сейчас {now}. Команда: {cmd}
Ответ ТОЛЬКО JSON вида {{"actions":[...]}}."""


def _gemini_plan(cmd: str) -> dict | None:
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        prompt = SYSTEM.replace('{now}', datetime.now().isoformat()).replace('{cmd}', cmd)
        rules = get_rules()
        if rules:
            prompt += '\nЗапомненные правила (учитывай):\n' + '\n'.join(f'- {r}' for r in rules)
        cfg = types.GenerateContentConfig(
            temperature=0.3, response_mime_type='application/json',
            http_options=types.HttpOptions(
                timeout=20000,
                retry_options=types.HttpRetryOptions(attempts=1)))
        last = None
        for model in AGENT_MODELS:
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt, config=cfg)
                raw = (r.text or '').strip().replace('```json', '').replace('```', '').strip()
                data = json.loads(raw)
                # толерантность: принимаем и {"actions":[...]}, и одиночное {"tool":...}, и голый список
                if isinstance(data, list):
                    return {'actions': data}
                if isinstance(data, dict) and 'actions' not in data and 'tool' in data:
                    return {'actions': [data]}
                return data
            except Exception as e:
                last = e
                continue
        print(f'[agent gemini] {last}')
        return None
    except Exception as e:
        print(f'[agent gemini] {e}')
        return None


def _rule_plan(cmd: str) -> dict:
    """Простые команды без нейронки: перенеси/статус/удали/колонка/напомни."""
    t = cmd.lower()
    # имя/запрос: берем слова с заглавной или после ключевых слов, иначе весь текст минус глаголы
    m = re.search(r'(?:перенеси|перемести|поставь|поменяй|обнови|удали|удалить|найди|напомни|запиши|записать|внеси|добавь|измени|изменить)\s+(.+?)(?:\s+во\s|\s+в\s|\s+на\s|\s+статус\s|$)', cmd, re.IGNORECASE)
    query = (m.group(1).strip() if m else '').strip(' "\'')
    # вычищаем служебное из запроса: "Тест Оплачено" -> "Тест"
    query = re.sub(r'\b(оплачено|оплачен|отказ|перезвонить|приехал|думает|новая|статус|смен[ауы]|осень|зиму?|зимняя|зимнюю|весну?|весенняя|защитник|2[67])\b', '', query, flags=re.IGNORECASE).strip()
    acts = []
    if re.search(r'создай\s+(таблиц|лист|список)|нов\w+\s+(таблиц|лист)', t):
        mn = re.search(r'(?:таблиц\w*|лист|список)\s+([а-яёa-z0-9 _-]{2,30})', cmd, re.IGNORECASE)
        name = (mn.group(1).strip().title() if mn else 'Новая таблица')
        name = re.sub(r'\s+с\s+колонками.*$', '', name, flags=re.IGNORECASE).strip() or 'Новая таблица'
        mh = re.search(r'колонк\w*\s*[:\-]?\s*(.+)', cmd, re.IGNORECASE)
        if mh:
            header = [h.strip().title() or f'Кол{i+1}' for i, h in
                      enumerate(re.split(r'[,;]+', mh.group(1).strip())) if h.strip()][:20]
        else:
            header = ['ФИО ребенка', 'Телефон', 'Заметка']
        acts.append({'tool': 'create_table', 'name': name[:30],
                     'header': header or ['Запись'], 'rows': []})
        return {'actions': acts}
    if re.search(r'сколько|статистика|сводка|анализ|посчитай|итог|сосчитай', t):
        acts.append({'tool': 'stats'})
        # "... по сменам/оплачено" — заодно показываем и конкретных людей
        if query and len(query) > 2:
            acts.append({'tool': 'find', 'query': query})
        return {'actions': acts}
    if re.search(r'перенес|перемест', t):
        try:
            from brain import normalize_shift
            shift = normalize_shift(cmd)
        except Exception:
            shift = ''
        st = None
        for s in ['перезвонил', 'оплачено', 'отказ', 'перезвонить', 'приехал', 'думает', 'новая']:
            if s in t:
                st = s.capitalize()
                break
        if shift and query:
            acts.append({'tool': 'move', 'query': query, 'shift': shift})
        if st and query:
            acts.append({'tool': 'bulk_update', 'query': query, 'fields': {'status': st}})
        if not acts and query:
            acts.append({'tool': 'find', 'query': query})
    elif re.search(r'удали', t):
        if re.search(r'напоминани', t):
            acts.append({'tool': 'clear_reminders'})
        elif query:
            acts.append({'tool': 'delete', 'query': query})
    elif re.search(r'колонк', t):
        mn = re.search(r'колонк\w*\s+([а-яёa-z ]+)', t)
        if mn:
            acts.append({'tool': 'add_column', 'name': mn.group(1).strip()})
    elif re.search(r'статус|оплачен|отказ|перезвон|приехал', t):
        st = 'Новая'
        for k, v in {'перезвонил': 'Перезвонил', 'оплачен': 'Оплачено', 'оплат': 'Оплачено', 'отказ': 'Отказ',
                     'перезвон': 'Перезвонить', 'приехал': 'Приехал', 'думает': 'Думает'}.items():
            if k in t:
                st = v
                break
        if query:
            acts.append({'tool': 'bulk_update', 'query': query, 'fields': {'status': st}})
    elif re.search(r'напомни|перезвони', t):
        from brain import parse_callback_datetime
        cb = parse_callback_datetime(cmd)
        if query:
            acts.append({'tool': 'remind', 'query': query,
                         'when': cb.isoformat() if cb else ''})
    elif re.search(r'запомни', t):
        m2 = re.search(r'запомни\s*[:\-]?\s*(.+)', cmd, re.IGNORECASE)
        if m2:
            acts.append({'tool': 'remember', 'text': m2.group(1).strip()})
    elif re.search(r'измени|правил', t):
        # "измени про человека" без конкретики — обновить некого, скажем кого нашли
        if query and len(query) > 2:
            acts.append({'tool': 'find', 'query': query})
        else:
            acts.append({'tool': 'clarify'})
    elif re.search(r'запомни|на будущее|всегда|пиши', t):
        # указание-правило без глагола действия: запоминаем как правило
        acts.append({'tool': 'remember', 'text': cmd.strip()})
    if not acts:
        acts.append({'tool': 'find', 'query': query or cmd.strip()[:60]})
    return {'actions': acts}


def execute(cmd: str) -> str:
    import storage as st
    from brain import fix_layout
    cmd = fix_layout(cmd)
    print(f'[agent] команда: {cmd}')
    plan = _gemini_plan(cmd)
    if plan:
        print(f'[agent] план gemini: {plan}')
    if not plan or not plan.get('actions'):
        # пустой план от модели = откат на правила, а не молчание
        print('[agent] пустой план, иду по правилам')
        plan = _rule_plan(cmd)
    print(f'[agent] выполняю: {plan}')
    log = []
    for a in plan.get('actions', []):
        tool = a.get('tool')
        try:
            if tool == 'find':
                rows = st.find_ids(a.get('query', ''))
                if rows:
                    log.append(f"🔎 {a.get('query')}: {len(rows)} шт. " +
                               '; '.join(f"{r.get('fio_child')} [{r.get('status')}] id={r.get('id')}" for r in rows[:5]))
                else:
                    last = [f"{r.get('fio_child')} [{r.get('status')}]" for r in st.read_all()[-5:]]
                    log.append(f"🔎 «{a.get('query')}» не нашел. Последние в базе: {'; '.join(last) or 'пусто'}")
            elif tool == 'clarify':
                last = [f"{r.get('fio_child')} [{r.get('status')}]" for r in st.read_all()[-5:]]
                log.append('❓ Кого именно изменить? Напиши имя, например: «поставь Иванову Оплачено». В базе: ' + '; '.join(last))
            elif tool == 'remember':
                n = save_rule(a.get('text', ''))
                log.append(f"📝 Запомнил правило №{n}: {a.get('text', '')}")
            elif tool == 'rules':
                rules = get_rules()
                log.append('📝 Правила:\n' + '\n'.join(f'{i+1}. {r}' for i, r in enumerate(rules)) if rules else '📝 Правил пока нет. Скажи: «запомни: ...»')
            elif tool == 'update':
                rows = st.find_ids(a.get('query', ''))
                n = sum(1 for r in rows if st.update_by_id(r['id'], a.get('fields', {})))
                log.append(f'✏️ Обновлено {n}/{len(rows)}: {a.get("fields")}')
            elif tool == 'update_id':
                ok = st.update_by_id(a['id'], a.get('fields', {}))
                log.append(f"✏️ id={a['id']}: {'ок' if ok else 'не найден'}")
            elif tool == 'bulk_update':
                force = 'всё равно' in cmd.lower() or 'все равно' in cmd.lower()
                rows = st.find_ids(a.get('query', ''))
                if len(rows) > 10 and not force:
                    log.append(f"⛔ Групповое задевает {len(rows)} записей — много. Уточни запрос или скажи «примени всё равно».")
                elif not rows:
                    log.append(f"🔎 «{a.get('query')}» не нашел — некого обновлять.")
                else:
                    total, ok = st.bulk_update(a.get('query', ''), a.get('fields', {}), force=force)
                    if total > 10 and not force and ok == 0:
                        log.append(f"⛔ Групповое задевает {total} записей — много. Уточни запрос или скажи «примени всё равно».")
                    else:
                        log.append(f'✏️ Групповое: обновлено {ok}/{total}: {a.get("fields")}')
            elif tool == 'move':
                rows = st.find_ids(a.get('query', ''))
                n = sum(1 for r in rows if st.set_shift(r['id'], a['shift']))
                log.append(f"📦 Перенесено {n} в {a['shift']}")
            elif tool == 'delete':
                rows = st.find_ids(a.get('query', ''))
                q = (a.get('query', '') or '').strip().lower()
                # предохранитель: "удали все/всех" без конкретики — клиентов не трогаем
                if q in ('все', 'всё', 'всех', 'вce', '') or len(rows) > 5:
                    log.append(f"⛔ Не удаляю: запрос «{a.get('query')}» задевает {len(rows)} записей. Уточни имя.")
                else:
                    n = sum(1 for r in rows if st.delete_by_id(r['id']))
                    log.append(f'🗑 Удалено {n}')
            elif tool == 'clear_reminders':
                from reminders import clear_all
                r = clear_all()
                if r['local']:
                    log.append(f"🗑 Удалено локальных напоминаний: {r['local']}")
                else:
                    log.append('✅ Чистить нечего — напоминаний нет')
            elif tool == 'add_column':
                heads = st.add_column(a['name'])
                log.append(f"🆕 Колонка '{a['name']}', всего: {len(heads)}")
            elif tool == 'create_table':
                name = str(a.get('name', 'Новая таблица'))[:30] or 'Новая таблица'
                header = a.get('header') or ['ФИО ребенка', 'Телефон', 'Заметка']
                rows = a.get('rows') or []
                n = st.write_sheet_local(name, header, rows)
                pushed = ' + мастер на Яндекс.Диске'
                log.append(f'📋 Таблица «{name}»: {n} строк{pushed}. Открой вкладку «📊 Таблицы».')
            elif tool == 'stats':
                rows = st.read_all()
                total = len(rows)
                by_shift: dict = {}
                by_status: dict = {}
                for r in rows:
                    by_shift[str(r.get('shift') or '—')] = by_shift.get(str(r.get('shift') or '—'), 0) + 1
                    by_status[str(r.get('status') or '—')] = by_status.get(str(r.get('status') or '—'), 0) + 1
                log.append('📊 Всего: %d. По сменам: %s. По статусам: %s.' % (
                    total,
                    ', '.join(f'{k} — {v}' for k, v in by_shift.items()) or 'пусто',
                    ', '.join(f'{k} — {v}' for k, v in by_status.items()) or 'пусто'))
                try:
                    import re as _re
                    debt_n, debt_s = 0, 0.0
                    for r in rows:
                        if str(r.get('status', '')) in ('Новая', 'Перезвонить', 'Думает'):
                            debt_n += 1
                            try:
                                debt_s += float(_re.sub(r'[^\d.]', '', str(r.get('сумма', '')).replace(',', '.')) or 0)
                            except Exception:
                                pass
                    if debt_n:
                        log.append(f'💰 Не оплатили: {debt_n} (долг {int(debt_s)} ₽). Лист «Долги» — кнопка «Пересчитать отчёты».')
                except Exception:
                    pass
            elif tool == 'remind':
                from reminders import add_local_reminder
                rows = st.find_ids(a.get('query', ''))
                for r in rows[:3]:
                    if a.get('when'):
                        add_local_reminder(r.get('fio_child', ''), a['when'], r.get('phone', ''))
                log.append(f"📅 Напоминание на {a.get('when')} для {len(rows)} шт.")
            else:
                log.append(f'❓ {tool} — не знаю')
        except Exception as e:
            log.append(f'⚠️ {tool}: {e}')
    return '\n'.join(log) if log else 'Ничего не сделал'
