"""Секретарь лагеря — веб-версия (Streamlit) для Hugging Face Spaces.

Копия app.py (Tkinter) без изменений десктопа: тот же флоу —
статус Google, вставка каши, дедупликация, upsert, напоминания,
ИИ-команды, журнал, голос. Весь UI-текст на русском.
"""
import os

import web_bootstrap

BOOT = web_bootstrap.bootstrap()

import streamlit as st

from brain import parse_client_text, find_duplicates, fix_layout
from storage import read_all, upsert
from reminders import add_local_reminder, due_reminders

st.set_page_config(page_title='Секретарь лагеря', page_icon='📋', layout='centered')
st.title('📋 Секретарь лагеря')


def gstatus():
    try:
        import google_sync
        s = google_sync.status()
        ok = bool(s['token'] and s['sheet_id'])
        link = f"https://docs.google.com/spreadsheets/d/{s['sheet_id']}/edit" if s['sheet_id'] else ''
        return ok, link
    except Exception:
        return False, ''


def say(s: str):
    st.session_state.setdefault('log', []).append(s)


# --- статус Google (как в app.py: таблица + календарь) ---
ok, link = gstatus()
if ok:
    st.success('🟢 Google подключен: Таблица + Календарь')
    if link:
        st.markdown(f'[Открыть Google-таблицу]({link})')
else:
    st.error('🔴 Google не подключен (работаю локально)')
if BOOT.get('restore', {}).get('rows', -1) >= 0 and BOOT['restore'].get('ok'):
    st.caption(f"📥 {BOOT['restore'].get('reason')}: {BOOT['restore'].get('rows')} строк.")

# --- пора перезвонить ---
due = due_reminders()
if due:
    st.warning('⏰ Пора перезвонить: ' + ', '.join(f"{d['fio']} ({d['callback_dt']})" for d in due[:5]))

# --- ввод каши ---
st.subheader('Что случилось? Вставь кашу текстом или надиктуй:')
raw_text = st.text_area('Текст заявки', height=150, key='raw_text',
                        placeholder='Например: Позвонила мама Иванова Мария, сын Тимофей Иванов 9 лет, ...')

# --- голос (скрыть блок если модуля/аудио нет — без падения) ---
try:
    import speech_recognition as sr  # noqa: F401
    _sr_ok = True
except Exception:
    _sr_ok = False

if _sr_ok and hasattr(st, 'audio_input'):
    try:
        st.caption('🎤 Голосовой ввод (распознавание ru-RU через Google):')
        audio = st.audio_input('Надиктуй заявку')
    except Exception as e:
        audio = None
        st.caption(f'🎤 Голосовой ввод недоступен на сервере ({e}). Вставь текст вручную.')
    if audio is not None:
        try:
            import speech_recognition as sr
            import tempfile
            suffix = '.wav'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(audio.getvalue())
                tmp_path = tmp.name
            try:
                r = sr.Recognizer()
                with sr.AudioFile(tmp_path) as src:
                    data = r.record(src)
                text = r.recognize_google(data, language='ru-RU')
                st.session_state['raw_text'] = text
                st.info('Проверь распознанный текст и жми «Внести».')
                st.rerun()
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        except Exception as e:
            st.error(f'Не распознано: {e}')

# --- разбор и сохранение ---
st.session_state.setdefault('pending', None)
st.session_state.setdefault('pending_raw', '')
st.session_state.setdefault('dups', [])


def force_new_record(data: dict):
    """Принудительно новая строка (как ветка _force_new в app.py)."""
    import storage as st_mod
    from datetime import datetime
    wb = st_mod._ensure_wb()
    ws = wb['Общая']
    heads = [str(c.value or '').strip() for c in next(ws.iter_rows(min_row=1, max_row=1))]
    flat = {k: data.get(k, '') for k, _ in st_mod.CORE}
    for k, v in (data.get('extra', {}) or {}).items():
        flat[k] = v
    cid = str(int(datetime.now().timestamp()))[-6:]
    flat['id'], flat['created'] = cid, datetime.now().strftime('%d.%m.%Y %H:%M')
    ws.append(st_mod._row_dict_to_list(heads, flat))
    wb.save(st_mod.FILE)
    return cid


def finalize_save(data: dict, mode: str):
    if mode == 'new':
        cid = force_new_record(data)
        action, new_cols, removed = 'добавлен (как новый)', list((data.get('extra', {}) or {}).keys()), None
    else:
        res = upsert(data)
        action, cid, new_cols = res[0], res[1], res[2]
        removed = res[3] if len(res) > 3 else None
        if removed and (removed.get('local') or removed.get('calendar')):
            action += f" (напоминания сняты: {removed['local'] + removed['calendar']})"
    extra_txt = ''
    if data.get('callback_dt'):
        try:
            add_local_reminder(data.get('fio_child', ''), data['callback_dt'], data.get('phone', ''))
            extra_txt += f"\n📅 Напоминание: {data['callback_dt']} (улетело в Google Calendar)"
        except Exception as e:
            extra_txt += f'\n⚠️ Напоминание только локально не записалось: {e}'
    if new_cols:
        extra_txt += f"\n🆕 Новые колонки от ИИ: {', '.join(new_cols)}"
    card = (f"✅ {data.get('fio_child') or '?'} — {action}\n"
            f"Родитель: {data.get('parent_fio') or '—'} | Тел: {data.get('phone') or '—'}\n"
            f"Смена: {data.get('shift') or '—'} | Статус: {data.get('status')}"
            + (f" | Доп: {data.get('extra')}" if data.get('extra') else '') + extra_txt)
    return card


col1, col2 = st.columns([1, 1])
with col1:
    btn_save = st.button('💾 Внести', type='primary', use_container_width=True)
with col2:
    if st.button('🧹 Очистить', use_container_width=True):
        st.session_state['pending'] = None
        st.session_state['dups'] = []
        st.session_state['raw_text'] = ''
        st.rerun()

if btn_save:
    raw = fix_layout((st.session_state.get('raw_text') or '').strip())
    if not raw:
        st.warning('Вставь текст заявки.')
    else:
        with st.spinner('⏳ Думаю...'):
            data = parse_client_text(raw)
        st.session_state['pending'] = data
        st.session_state['pending_raw'] = raw
        st.session_state['dups'] = find_duplicates(data, read_all())
        st.session_state['confirm_new_empty'] = False
        st.rerun()

pending = st.session_state.get('pending')
if pending:
    data = pending
    dups = st.session_state.get('dups') or []
    st.divider()
    st.subheader('Карточка разбора')
    st.json({k: v for k, v in data.items()})
    needs_confirm_empty = not data.get('fio_child') and not data.get('phone')
    proceed = True
    mode = 'upsert'
    if needs_confirm_empty:
        st.warning(f"Не понял заявку. Нашел так — вносить?\n{data}")
        ok_empty = st.checkbox('Да, внести как есть', key='confirm_new_empty')
        proceed = ok_empty
    if dups and proceed:
        names = '\n'.join(f"{r.get('fio_child')} {r.get('phone')} [{r.get('status')}]" for r in dups[:3])
        st.warning(f'Похож на уже записанного:\n{names}')
        choice = st.radio('Что делать?', ('Обновить его', 'Новая запись'), key='dup_choice')
        mode = 'upsert' if choice == 'Обновить его' else 'new'
    if proceed:
        if st.button('✅ Подтвердить сохранение', type='primary'):
            with st.spinner('Сохраняю...'):
                card = finalize_save(dict(data), mode)
            st.success(card)
            say(card + f"\nИсходник: {st.session_state.get('pending_raw', '')[:200]}")
            st.session_state['pending'] = None
            st.session_state['dups'] = []
            st.session_state['raw_text'] = ''

# --- ИИ-командная строка ---
st.divider()
st.subheader('🤖 Команда ИИ правит таблицы')
st.caption('Примеры: перенеси Иванова в Зиму 26 | поставь Иванову Оплачено | удали Пупкина | добавь колонку аллергия')
with st.form('ai_form', clear_on_submit=True):
    cmd = st.text_input('Команда', placeholder='Напиши команду и нажми Enter')
    submitted = st.form_submit_button('▶ Выполнить')
if submitted and cmd and cmd.strip():
    say(f'🤖 Команда: {cmd.strip()}')
    try:
        import agent
        res = agent.execute(cmd.strip())
    except Exception as e:
        res = f'⚠️ {e}'
    say(res)
    st.rerun()

# --- журнал в st-сессии ---
st.divider()
st.subheader('Журнал')
for entry in reversed(st.session_state.get('log', [])):
    st.text(entry + '\n---')
