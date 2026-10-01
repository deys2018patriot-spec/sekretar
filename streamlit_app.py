"""Секретарь лагеря — веб-версия (Streamlit) для Render.

Копия app.py (Tkinter) без изменений десктопа: тот же флоу —
статус Google, вставка каши, дедупликация, upsert, напоминания,
ИИ-команды, журнал, голос. Весь UI-текст на русском.
Вкладка «Таблицы» — полная копия Google Sheets (все листы).
"""
import os

import web_bootstrap

BOOT = web_bootstrap.bootstrap()

import streamlit as st

from brain import parse_client_text, find_duplicates, fix_layout
from storage import read_all, upsert, read_all_sheets
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
restore = BOOT.get('restore', {})
if restore.get('ok') and restore.get('rows', -1) >= 0:
    per = restore.get('sheets') or {}
    detail = (', '.join(f'{k}: {v}' for k, v in per.items())) if per else ''
    st.caption(f"📥 {restore.get('reason')}: всего {restore.get('rows')} строк. {detail}")

# --- пора перезвонить ---
due = due_reminders()
if due:
    st.warning('⏰ Пора перезвонить: ' + ', '.join(f"{d['fio']} ({d['callback_dt']})" for d in due[:5]))

tab_req, tab_tbl = st.tabs(['📝 Заявки', '📊 Таблицы'])

with tab_req:
    # отложенная очистка поля (менять ключ виджета после его создания нельзя)
    if st.session_state.pop('_clear_raw', False):
        st.session_state.pop('raw_text', None)
    _last = st.session_state.pop('_last_card', None)
    if _last:
        st.success(_last)
    # --- ввод каши ---
    st.subheader('Что случилось? Вставь кашу текстом или надиктуй:')
    raw_text = st.text_area('Текст заявки', height=150, key='raw_text',
                            placeholder='Например: Позвонила мама Иванова Мария, сын Тимофей Иванов 9 лет, ...')

    # --- голос: микрофон в браузере ИЛИ загрузка голосового файла ---
    def recognize_wav_bytes(raw: bytes) -> str:
        import speech_recognition as sr
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            r = sr.Recognizer()
            with sr.AudioFile(tmp_path) as src:
                data = r.record(src)
            return r.recognize_google(data, language='ru-RU')
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    try:
        import speech_recognition  # noqa: F401
        _sr_ok = True
    except Exception as _e:
        _sr_ok = False
        st.caption(f'🎤 Голосовое распознавание недоступно на сервере ({_e}). Вставь текст вручную.')

    if _sr_ok:
        if hasattr(st, 'audio_input'):
            try:
                st.caption('🎤 Надиктуй в микрофон (ru-RU):')
                audio = st.audio_input('Надиктуй заявку')
            except Exception as e:
                audio = None
                st.caption(f'🎤 Микрофон недоступен ({e}) — загрузи аудиофайл ниже.')
            if audio is not None:
                aid = getattr(audio, 'id', None) or audio.name
                if st.session_state.get('voice_done') != aid:
                    with st.spinner('🎧 Распознаю...'):
                        try:
                            st.session_state['raw_text'] = recognize_wav_bytes(audio.getvalue())
                            st.session_state['voice_done'] = aid
                            st.info('Проверь распознанный текст и жми «Внести».')
                            st.rerun()
                        except Exception as e:
                            st.error(f'Не распознано: {e}. Попробуй ещё раз или загрузи файл.')
        st.caption('...или загрузи голосовое (wav/mp3/ogg/m4a — например, пересланное из мессенджера):')
        up = st.file_uploader('Голосовой файл', type=['wav', 'mp3', 'ogg', 'm4a', 'flac'],
                              key='voice_file', label_visibility='collapsed')
        if up is not None and st.button('🎧 Распознать файл'):
            with st.spinner('🎧 Распознаю файл...'):
                try:
                    st.session_state['raw_text'] = recognize_wav_bytes(up.getvalue())
                    st.info('Проверь распознанный текст и жми «Внести».')
                    st.rerun()
                except Exception as e:
                    st.error(f'Не распознано: {e}. Нужна разборчивая русская речь.')

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
            st.info('Проверь разбор выше и нажми «✅ Подтвердить сохранение» — '
                    'только тогда запись попадёт в таблицы (запись в Google идёт ~20–40 сек).')
            if st.button('✅ Подтвердить сохранение', type='primary'):
                with st.spinner('Сохраняю (пишу в Google, ~20–40 сек)...'):
                    try:
                        card = finalize_save(dict(data), mode)
                    except Exception as e:
                        st.error(f'Не сохранилось: {e}')
                        st.stop()
                st.success(card)
                say(card + f"\nИсходник: {st.session_state.get('pending_raw', '')[:200]}")
                st.session_state['_last_card'] = card
                st.session_state['_clear_raw'] = True
                st.session_state['pending'] = None
                st.session_state['dups'] = []
                st.rerun()

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

with tab_tbl:
    # --- Таблицы: полная копия Google Sheets (все листы) ---
    st.subheader('📊 Таблицы — копия Google Sheets')
    st.caption('Вся таблица копируется из Google при каждом открытии и по кнопке ниже.')
    if st.button('🔄 Обновить из Google', use_container_width=True):
        with st.spinner('Копирую из Google Sheets...'):
            rep = web_bootstrap.pull_google_to_local(force=True)
        if rep.get('ok'):
            per = rep.get('sheets') or {}
            detail = (', '.join(f'{k}: {v}' for k, v in per.items())) if per else ''
            st.success(f"✅ {rep.get('reason')}: всего {rep.get('rows')} строк. {detail}")
        else:
            st.error(f"⚠️ {rep.get('reason')} — показываю локальную копию.")
        st.rerun()
    try:
        all_sheets = read_all_sheets()
    except Exception as e:
        all_sheets = {}
        st.error(f'Не смог прочитать таблицы: {e}')
    if not all_sheets:
        st.info('Таблицы пока пусты.')

    def _norm_cell(v) -> str:
        if v is None:
            return ''
        if isinstance(v, float) and v != v:  # NaN
            return ''
        return str(v)

    def save_table_edits(name: str, heads: list, rows: list, edited) -> str:
        """Правки из data_editor: изменённые ячейки, новые и удалённые строки."""
        import storage as _st
        recs = edited.to_dict('records') if hasattr(edited, 'to_dict') else list(edited)
        key_of = {h: _st.HEADER_TO_KEY.get(h, h.lower()) for h in (heads or [])}
        core_keys = [kk for kk, _ in _st.CORE]
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
                    nv = _norm_cell(rec.get(h))
                    if nv != rows[i].get(k, ''):
                        fields[k] = nv
                if fields and _st.update_by_id(cid, fields):
                    upd += 1
            else:
                d, extra = {}, {}
                for h in (heads or []):
                    v = _norm_cell(rec.get(h))
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
                d['extra'] = extra
                _st.upsert(d)
                new_n += 1
        for r in rows:
            cid = str(r.get('id', ''))
            if cid and cid not in seen_ids and _st.delete_by_id(cid):
                del_n += 1
        return f'Правок: {upd}, новых строк: {new_n}, удалено: {del_n}.'

    for name, (heads, rows) in all_sheets.items():
        # каждая таблица сворачивается (Общая открыта по умолчанию); правится прямо тут
        with st.expander(f'{name} — {len(rows)} строк', expanded=(name == 'Общая')):
            if not rows:
                st.caption('Пусто')
                continue
            # порядок колонок как в шапке листа
            import storage as _st
            table = [{h: r.get(_st.HEADER_TO_KEY.get(h, h.lower()), '') for h in (heads or [])} for r in rows]
            if name != 'Общая':
                st.dataframe(table, use_container_width=True)
                st.caption('Сезонный лист — проекция. Правки: через «Общую» или команду ИИ.')
                continue
            # Общую можно править прямо тут (строки добавляются/удаляются тоже)
            lock = ([heads[0]] if heads else []) + ([heads[1]] if len(heads) > 1 else [])
            edited = st.data_editor(table, use_container_width=True, num_rows='dynamic',
                                    key=f'ed_{name}', hide_index=True, disabled=lock)
            if st.button('💾 Сохранить правки', key=f'sv_{name}'):
                with st.spinner('Сохраняю правки (пишу в Google)...'):
                    try:
                        rep = save_table_edits(name, heads, rows, edited)
                    except Exception as e:
                        st.error(f'Не сохранилось: {e}')
                        st.stop()
                st.success('✅ ' + rep)
                st.rerun()
