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
st.markdown('''<style>
/* Убрать стандартную серую дымку спиннера */
[data-testid="stSpinner"] { visibility: hidden !important; height: 0 !important; }
/* Фон-микросхема: лежит ПОД контентом (z-index 0), контент поднят выше
   с прозрачным фоном — дорожки видны только в просветах между формами,
   целиком не видны никогда. Ток — отдельный слой поверх (только точки). */
.circuit-board {
  position: fixed; inset: 0; pointer-events: none; z-index: 0;
  opacity: .55;
  /* центр под контентом выцветает: плата живёт по краям и в просветах,
     целиком не видна никогда */
  -webkit-mask-image: radial-gradient(ellipse 95% 85% at 50% 38%, transparent 52%, black 100%);
  mask-image: radial-gradient(ellipse 95% 85% at 50% 38%, transparent 52%, black 100%);
}
[data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stHeader"], [data-testid="stBottom"] {
  position: relative; z-index: 1; background: transparent !important;
}
[data-testid="stVerticalBlock"] { background: transparent !important; }
.circuit-current {
  position: fixed; inset: 0; pointer-events: none; z-index: 9999999;
  opacity: 0; transition: opacity .5s ease;
}
body:has(div[data-testid="stSpinner"]) .circuit-current { opacity: 1; }
/* На телефоне — тише, чтобы не рябило */
@media (max-width: 640px) {
  .circuit-board { opacity: .35; }
}
</style><div class="circuit-board"><svg width="100%" height="100%" preserveAspectRatio="xMidYMid slice" viewBox="0 0 1200 800">
<g stroke="#9db4d4" stroke-width="1.6" fill="none" opacity=".8">
<path d="M-20,80 H280 L340,140 H640 L700,200 H1220"/>
<path d="M-20,160 H200 L260,220 H520 L580,280 H900 L960,340 H1220"/>
<path d="M-20,300 H140 L200,360 H420 L480,420 H760 L820,480 H1220"/>
<path d="M-20,420 H180 L240,480 H560 L620,540 H1220"/>
<path d="M-20,540 H260 L320,600 H600 L660,660 H1000 L1060,720 H1220"/>
<path d="M-20,680 H420 L480,620 H900 L960,560 H1220"/>
<path d="M-20,740 H340 L400,680 H700 L760,740 H1220"/>
<path d="M120,-20 V160 L180,220 V400 L240,460 V820"/>
<path d="M300,-20 V100 L360,160 V360 L420,420 V700 L480,760 V820"/>
<path d="M520,-20 V220 L580,280 V480 L640,540 V820"/>
<path d="M720,-20 V120 L780,180 V380 L840,440 V700 L900,760 V820"/>
<path d="M920,-20 V240 L980,300 V520 L1040,580 V820"/>
<path d="M1080,-20 V340 L1140,400 V620 L1100,680 V820"/>
<path d="M-20,240 H100 L150,290 H300 L350,340 H480"/>
<path d="M700,-20 V60 L750,110 H980 L1030,160 H1220"/>
<path d="M460,820 V720 L520,660 H760"/>
<path d="M820,320 H980 L1040,380 H1220"/>
<path d="M80,480 H240 L300,540 H480"/>
<path d="M620,640 H800 L860,700 H1040"/>
</g>
<g fill="#9db4d4" stroke="none" opacity=".8">
<circle cx="280" cy="80" r="4"/><circle cx="640" cy="140" r="4"/>
<circle cx="200" cy="160" r="4"/><circle cx="520" cy="220" r="4"/><circle cx="900" cy="280" r="4"/>
<circle cx="140" cy="300" r="4"/><circle cx="420" cy="360" r="4"/><circle cx="760" cy="420" r="4"/>
<circle cx="180" cy="420" r="4"/><circle cx="560" cy="480" r="4"/>
<circle cx="260" cy="540" r="4"/><circle cx="600" cy="600" r="4"/><circle cx="1000" cy="660" r="4"/>
<circle cx="420" cy="680" r="4"/><circle cx="900" cy="620" r="4"/>
<circle cx="340" cy="740" r="4"/><circle cx="700" cy="680" r="4"/>
<circle cx="120" cy="160" r="4"/><circle cx="240" cy="460" r="4"/>
<circle cx="300" cy="100" r="4"/><circle cx="420" cy="420" r="4"/><circle cx="480" cy="760" r="4"/>
<circle cx="520" cy="220" r="4"/><circle cx="640" cy="540" r="4"/>
<circle cx="720" cy="120" r="4"/><circle cx="840" cy="440" r="4"/><circle cx="900" cy="760" r="4"/>
<circle cx="920" cy="240" r="4"/><circle cx="1040" cy="580" r="4"/>
<circle cx="1080" cy="340" r="4"/><circle cx="1100" cy="680" r="4"/>
<circle cx="100" cy="240" r="4"/><circle cx="350" cy="340" r="4"/>
<circle cx="750" cy="110" r="4"/><circle cx="1030" cy="160" r="4"/>
<circle cx="520" cy="660" r="4"/><circle cx="980" cy="320" r="4"/><circle cx="1040" cy="380" r="4"/>
<circle cx="80" cy="480" r="4"/><circle cx="300" cy="540" r="4"/>
<circle cx="620" cy="640" r="4"/><circle cx="860" cy="700" r="4"/>
</g>
</svg></div><div class="circuit-current"><svg width="100%" height="100%" preserveAspectRatio="xMidYMid slice" viewBox="0 0 1200 800">
<g fill="#2f7bff">
<circle r="6"><animateMotion dur="2.8s" repeatCount="indefinite" path="M-20,80 H280 L340,140 H640 L700,200 H1220"/></circle>
<circle r="6" fill="#22b8d4"><animateMotion dur="3.6s" repeatCount="indefinite" path="M-20,420 H180 L240,480 H560 L620,540 H1220"/></circle>
<circle r="6"><animateMotion dur="3.1s" repeatCount="indefinite" path="M-20,680 H420 L480,620 H900 L960,560 H1220"/></circle>
<circle r="5" fill="#22b8d4"><animateMotion dur="2.4s" repeatCount="indefinite" path="M120,-20 V160 L180,220 V400 L240,460 V820"/></circle>
<circle r="5"><animateMotion dur="3.9s" repeatCount="indefinite" path="M520,-20 V220 L580,280 V480 L640,540 V820"/></circle>
<circle r="5" fill="#22b8d4"><animateMotion dur="2.9s" repeatCount="indefinite" path="M920,-20 V240 L980,300 V520 L1040,580 V820"/></circle>
<circle r="5"><animateMotion dur="3.3s" repeatCount="indefinite" path="M-20,540 H260 L320,600 H600 L660,660 H1000 L1060,720 H1220"/></circle>
<circle r="5" fill="#22b8d4"><animateMotion dur="2.6s" repeatCount="indefinite" path="M720,-20 V120 L780,180 V380 L840,440 V700 L900,760 V820"/></circle>
</g>
</svg></div>''', unsafe_allow_html=True)
st.title('📋 Секретарь лагеря')


def gstatus():
    try:
        import yandex_store
        s = yandex_store.status()
        return bool(s['token']), 'https://disk.yandex.ru'
    except Exception:
        return False, ''


def say(s: str):
    st.session_state.setdefault('log', []).append(s)


# --- статус Google (как в app.py: таблица + календарь) ---
ok, link = gstatus()
if ok:
    st.success('🟢 Яндекс.Диск подключён: таблицы + архив')
    if link:
        st.markdown(f'[Открыть Яндекс.Диск]({link})')
else:
    st.error('🔴 Яндекс.Диск не подключён (работаю локально)')
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
    # Ключи поля/аудио с поколением: сброс = новый ключ (фронт 1.64 игнорит
    # удаление значения, а новый виджет всегда стартует чистым).
    gen = st.session_state.get('ta_gen', 0)
    RK, VK, FK = f'raw_text_{gen}', f'voice_rec_{gen}', f'voice_file_{gen}'
    _last = st.session_state.pop('_last_card', None)
    if _last:
        st.success(_last)
    if st.session_state.pop('_voice_info', False):
        st.info('Проверь распознанный текст и жми «Внести».')
    # --- ввод каши ---
    st.subheader('Что случилось? Вставь кашу текстом или надиктуй:')
    raw_text = st.text_area('Текст заявки', height=150, key=RK,
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
                audio = st.audio_input('Надиктуй заявку', key=VK)
            except Exception as e:
                audio = None
                st.caption(f'🎤 Микрофон недоступен ({e}) — загрузи аудиофайл ниже.')
            if audio is not None:
                aid = getattr(audio, 'id', None) or audio.name
                if st.session_state.get('voice_done') != aid:
                    with st.spinner('🎧 Распознаю...'):
                        try:
                            text = recognize_wav_bytes(audio.getvalue())
                        except Exception as e:
                            text = ''
                            st.error(f'Не распознано: {e}. Попробуй ещё раз или загрузи файл.')
                    st.session_state['voice_done'] = aid
                    if text:
                        st.session_state['ta_gen'] = gen + 1
                        st.session_state[f'raw_text_{gen + 1}'] = text
                        st.session_state['_voice_info'] = True
                        st.rerun()
        st.caption('...или загрузи голосовое (wav/mp3/ogg/m4a — например, пересланное из мессенджера):')
        up = st.file_uploader('Голосовой файл', type=['wav', 'mp3', 'ogg', 'm4a', 'flac'],
                              key=FK, label_visibility='collapsed')
        if up is not None and st.button('🎧 Распознать файл'):
            with st.spinner('🎧 Распознаю файл...'):
                try:
                    text = recognize_wav_bytes(up.getvalue())
                except Exception as e:
                    text = ''
                    st.error(f'Не распознано: {e}. Нужна разборчивая русская речь.')
            if text:
                st.session_state['ta_gen'] = gen + 1
                st.session_state[f'raw_text_{gen + 1}'] = text
                st.session_state['_voice_info'] = True
                st.rerun()

    # --- разбор и сохранение ---
    st.session_state.setdefault('pending', None)
    st.session_state.setdefault('pending_raw', '')
    st.session_state.setdefault('dups', [])


    def force_new_record(data: dict):
        """Принудительно новая строка (как ветка _force_new в app.py).
        Возвращает (cid, sync_res): extra-колонки создаются, сейв атомарный."""
        import storage as st_mod
        import uuid as _uuid
        from datetime import datetime
        wb = st_mod._ensure_wb()
        ws = wb['Общая']
        heads = st_mod._ensure_columns(wb, [k for k in (data.get('extra', {}) or {})])
        flat = {k: data.get(k, '') for k, _ in st_mod.CORE}
        for k, v in (data.get('extra', {}) or {}).items():
            flat[k] = v
        cid = _uuid.uuid4().hex[:8]
        try:
            taken = {str(r[0].value or '') for r in ws.iter_rows(min_row=2)}
            while cid in taken:
                cid = _uuid.uuid4().hex[:8]
        except Exception:
            pass
        flat['id'], flat['created'] = cid, datetime.now().strftime('%d.%m.%Y %H:%M')
        ws.append(st_mod._row_dict_to_list(heads, flat))
        st_mod._save_wb(wb)
        # Новая запись тоже обязана улететь на Диск (иначе сгорит при редеплое)
        try:
            import yandex_store
            sres = yandex_store.sync_after_change('новая запись')
        except Exception as e:
            print(f'[Yandex] только локально ({e})')
            sres = {'ok': False, 'reason': f'только локально ({e})'}
        return cid, sres


    def finalize_save(data: dict, mode: str):
        if mode == 'new':
            cid, sres = force_new_record(data)
            action = 'добавлен (как новый)'
            new_cols = [k for k in (data.get('extra', {}) or {})]
            removed = None
        else:
            res = upsert(data)
            action, cid, new_cols = res[0], res[1], res[2]
            removed = res[3] if len(res) > 3 else None
            sres = None  # для upsert статус берём из last_status ниже
            if removed and removed.get('local'):
                action += f" (напоминания сняты: {removed['local']})"
        extra_txt = ''
        if data.get('callback_dt'):
            try:
                add_local_reminder(data.get('fio_child', ''), data['callback_dt'], data.get('phone', ''))
                extra_txt += f"\n📅 Напоминание: {data['callback_dt']} (на сайте, в блоке «Пора перезвонить»)"
            except Exception as e:
                extra_txt += f'\n⚠️ Напоминание только локально не записалось: {e}'
        if new_cols:
            extra_txt += f"\n🆕 Новые колонки от ИИ: {', '.join(new_cols)}"
        try:
            import yandex_store as _ys3
            _ls = sres if mode == 'new' else _ys3.last_status()
            if _ls.get('ok'):
                extra_txt += '\n☁️ Синхронизировано с Диском'
            elif _ls.get('ok') is None:
                extra_txt += f"\n⏳ {_ls.get('reason', 'статус Диска неизвестен')[:80]}"
            else:
                extra_txt += f"\n⚠️ Только локально ({_ls.get('reason', '')[:80]})"
        except Exception:
            extra_txt += '\n⏳ Статус Диска неизвестен (только локально?)'
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
            st.session_state['voice_done'] = None
            st.session_state['ta_gen'] = gen + 1
            st.rerun()

    if btn_save:
        raw = fix_layout((st.session_state.get(RK) or '').strip())
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
                    'только тогда запись попадёт в таблицы (запись на Диск идёт ~10–20 сек).')
            if st.button('✅ Подтвердить сохранение', type='primary'):
                with st.spinner('Сохраняю (пишу на Диск, ~10–20 сек)...'):
                    try:
                        card = finalize_save(dict(data), mode)
                    except Exception as e:
                        st.error(f'Не сохранилось: {e}')
                        st.stop()
                st.success(card)
                say(card + f"\nИсходник: {st.session_state.get('pending_raw', '')[:200]}")
                st.session_state['_last_card'] = card
                st.session_state['voice_done'] = None
                st.session_state['ta_gen'] = gen + 1
                st.session_state['pending'] = None
                st.session_state['dups'] = []
                st.rerun()

    # --- ИИ-командная строка: понял → «правильно?» → Да → доклад ---
    st.divider()
    st.subheader('🤖 Команда ИИ правит таблицы')
    st.caption('Примеры: перенеси Иванова в Зиму 26 | поставь Иванову Оплачено | удали Пупкина | добавь колонку аллергия')
    st.session_state.setdefault('agent_pending', None)
    with st.form('ai_form', clear_on_submit=True):
        cmd = st.text_input('Команда', placeholder='Напиши команду и нажми Enter')
        submitted = st.form_submit_button('▶ Выполнить')
    if submitted and cmd and cmd.strip():
        try:
            import agent
            plan = agent.make_plan(cmd.strip())
            desc = agent.describe_plan(plan)
        except Exception as e:
            plan, desc = None, f'⚠️ Не понял: {e}'
        st.session_state['agent_pending'] = {'cmd': cmd.strip(), 'plan': plan,
                                             'desc': desc}
        st.rerun()
    pend = st.session_state.get('agent_pending')
    if pend:
        st.info(f"🤖 Команда: {pend['cmd']}\n\nЯ правильно понял?\n{pend['desc']}")
        c_yes, c_no = st.columns(2)
        with c_yes:
            if st.button('✅ Да, выполняй', type='primary', use_container_width=True):
                try:
                    import agent
                    res = agent.execute_plan(pend['plan']) if pend['plan'] else 'Ничего делать не буду.'
                except Exception as e:
                    res = f'⚠️ {e}'
                say(f"🤖 Команда: {pend['cmd']}\n✅ Сделано:\n{res}")
                st.session_state['agent_pending'] = None
                st.rerun()
        with c_no:
            if st.button('❌ Нет, отмена', use_container_width=True):
                say(f"🤖 Команда: {pend['cmd']}\n❌ Отменено, ничего не делал.")
                st.session_state['agent_pending'] = None
                st.rerun()

    # --- журнал в st-сессии ---
    st.divider()
    st.subheader('Журнал')
    for entry in reversed(st.session_state.get('log', [])):
        st.text(entry + '\n---')

with tab_tbl:
    # --- Таблицы: копия мастер-файла с Яндекс.Диска (все листы) ---
    _le = st.session_state.pop('_last_edit', None)
    if _le:
        st.success(_le)
    st.subheader('📊 Таблицы — копия Яндекс.Диска')
    st.caption('Вся таблица копируется с Диска при каждом открытии и по кнопке ниже.')
    try:
        import yandex_store as _ys7
        _lst = _ys7.last_status()
        if _lst.get('ts'):
            _ok = _lst.get('ok')
            _mark = '☁️' if _ok else ('⏳' if _ok is None else '⚠️')
            st.caption(f"{_mark} Последняя заливка: {_lst['ts'][:16].replace('T', ' ')} ({_lst.get('reason', '')[:80]})")
    except Exception:
        pass
    if st.button('🔄 Обновить с Диска', use_container_width=True):
        with st.spinner('Копирую с Яндекс.Диска...'):
            rep = web_bootstrap.pull_google_to_local(force=True)
        if rep.get('ok'):
            per = rep.get('sheets') or {}
            detail = (', '.join(f'{k}: {v}' for k, v in per.items())) if per else ''
            st.success(f"✅ {rep.get('reason')}: всего {rep.get('rows')} строк. {detail}")
        else:
            st.error(f"⚠️ {rep.get('reason')} — показываю локальную копию.")
        st.rerun()
    with st.expander('📥 Переехать с Google Sheets (разово)', expanded=False):
        st.caption('Соберёт все листы из Google-таблицы в один файл и зальёт мастер на Яндекс.Диск. Кнопка нужна один раз.')
        try:
            import yandex_store as _ys6
            _master_here = _ys6.remote_exists()
        except Exception:
            _master_here = False
        if _master_here:
            st.info('Мастер уже на Диске — повторный переезд перезапишет его. Для повтора удали файл на Диске вручную.')
        if st.button('📥 Переехать с Google', use_container_width=True):
            with st.spinner('Переезжаю с Google на Диск...'):
                try:
                    import yandex_store
                    rep = yandex_store.migrate_from_google()
                except Exception as e:
                    rep = {'ok': False, 'reason': f'не переехалось: {e}'}
            if rep.get('ok'):
                st.session_state['_last_edit'] = '✅ ' + rep.get('reason', '')
            else:
                st.error(f"⚠️ {rep.get('reason')}")
            st.rerun()
    c_rep, c_rbk = st.columns(2)
    with c_rep:
        if st.button('📊 Пересчитать отчёты', use_container_width=True):
            with st.spinner('Считаю Долги и Отчёт...'):
                try:
                    import storage as _st3
                    rep = _st3.build_reports()
                    st.session_state['_last_edit'] = (
                        f"✅ Отчёты пересчитаны: должников {rep['должников']}, смен {rep['смен']}.")
                except Exception as e:
                    st.error(f'Не посчиталось: {e}')
            st.rerun()
    with c_rbk:
        if st.button('📸 Снапшот', use_container_width=True):
            try:
                import yandex_store as _ys4
                rep = _ys4.snapshot('ручной')
                st.session_state['_last_edit'] = '✅ Снапшот: ' + rep.get('reason', '')
            except Exception as e:
                st.error(f'Не сохранилось: {e}')
            st.rerun()
    with st.expander('⏪ Откат к бэкапу', expanded=False):
        st.caption('Восстановление заменяет текущий мастер. Перед откатом делается автоснапшот.')
        try:
            import yandex_store as _ys5
            backs = _ys5.list_backups()
        except Exception:
            backs = []
        if not backs:
            st.caption('Бэкапов на Диске пока нет.')
        else:
            _sel = st.selectbox('Бэкап', backs, key='rb_sel')
            _understand = st.checkbox('Понимаю: текущий мастер будет заменён', key='rb_ok')
            if st.button('⏪ Восстановить выбранный', use_container_width=True):
                if not _understand:
                    st.warning('Поставь галочку «Понимаю» — откат необратим без неё.')
                    st.stop()
                with st.spinner('Восстанавливаю...'):
                    rep = _ys5.restore_backup(_sel)
                st.session_state['_last_edit'] = ('✅ ' if rep.get('ok') else '⚠️ ') + rep.get('reason', '')
                st.rerun()
    try:
        all_sheets = read_all_sheets()
    except Exception as e:
        all_sheets = {}
        st.error(f'Не смог прочитать таблицы: {e}')
    if not all_sheets:
        st.info('Таблицы пока пусты.')

    def _num(v) -> str:
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v if v is not None else '')

    def parse_table_file(fname: str, raw: bytes) -> tuple:
        """Любой табличный файл → (шапка, строки). xlsx/xls/ods/csv/json."""
        import io
        ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
        if ext in ('xlsx', 'xlsm'):
            from openpyxl import load_workbook
            ws = load_workbook(io.BytesIO(raw), data_only=True).active
            vals = list(ws.iter_rows(values_only=True))
            vals = [r for r in vals if any(v not in (None, '') for v in (r or ()))]
            if not vals:
                return [], []
            header = [str(x or '').strip() or f'col{i + 1}' for i, x in enumerate(vals[0])]
            return header, [[_num(x) for x in r] + [''] * max(0, len(header) - len(r)) for r in vals[1:]]
        if ext == 'xls':
            import xlrd
            sh = xlrd.open_workbook(file_contents=raw).sheet_by_index(0)
            vals = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
            vals = [r for r in vals if any(str(v).strip() for v in r)]
            if not vals:
                return [], []
            header = [str(x or '').strip() or f'col{i + 1}' for i, x in enumerate(vals[0])]
            return header, [[_num(x) for x in r] + [''] * max(0, len(header) - len(r)) for r in vals[1:]]
        if ext == 'ods':
            from odf.opendocument import load as odf_load
            from odf.table import table as odf_table, table_row
            from odf.text import p as odf_p
            doc = odf_load(io.BytesIO(raw))
            tabs = doc.getElementsByType(odf_table)
            if not tabs:
                return [], []
            grid: list = []
            for row in tabs[0].getElementsByType(table_row):
                rep = int(row.getAttribute('numberrowsrepeated') or 1)
                cells: list = []
                for cell in row.childNodes:
                    tag = getattr(cell, 'tagName', '')
                    if tag == 'table:covered-table-cell':
                        cells.append('')
                    elif tag == 'table:table-cell':
                        crep = int(cell.getAttribute('numbercolumnsrepeated') or 1)
                        txt = ''.join(n.data for p in cell.getElementsByType(odf_p)
                                      for n in p.childNodes if n.nodeType == n.TEXT_NODE)
                        cells.extend([txt] * crep)
                grid.extend([list(cells) for _ in range(rep)])
            grid = [r for r in grid if any(str(v).strip() for v in r)]
            if not grid:
                return [], []
            header = [str(x or '').strip() or f'col{i + 1}' for i, x in enumerate(grid[0])]
            return header, [[str(x or '') for x in r] + [''] * max(0, len(header) - len(r)) for r in grid[1:]]
        if ext in ('csv', 'tsv', 'txt'):
            import csv
            text = None
            for enc in ('utf-8-sig', 'cp1251'):
                try:
                    text = raw.decode(enc)
                    break
                except Exception:
                    continue
            if text is None:
                raise ValueError('не смог прочитать кодировку (нужны UTF-8 или CP1251)')
            sample = text[:2000]
            if ext == 'tsv':
                delim = '\t'
            else:
                delim = ';' if sample.count(';') >= sample.count(',') else ','
                if delim == ',' and ',' not in sample and '\t' in sample:
                    delim = '\t'
            vals = [r for r in csv.reader(io.StringIO(text), delimiter=delim)
                    if any(c.strip() for c in r)]
            if not vals:
                return [], []
            header = [c.strip() or f'col{i + 1}' for i, c in enumerate(vals[0])]
            return header, [list(r) + [''] * max(0, len(header) - len(r)) for r in vals[1:]]
        if ext == 'json':
            import json
            obj = json.loads(raw.decode('utf-8-sig'))
            lst = obj if isinstance(obj, list) else (obj.get('rows') or obj.get('data') or [])
            if not lst:
                return [], []
            keys: list = []
            for d in lst:
                for k in (d or {}).keys():
                    if k not in keys:
                        keys.append(str(k))
            return keys, [[str((d or {}).get(k, '')) for k in keys] for d in lst]
        raise ValueError(f'формат .{ext or "?"} не поддерживаю (xlsx, xls, ods, csv, json)')

    def clean_sheet_name(raw: str, taken: set) -> str:
        """Имя листа для Excel: без : \\ / ? * [ ], до 31 символа, уникальное."""
        base = ''.join(c if (c.isalnum() or c in ' _-') else '_' for c in (raw or '')).strip()[:31] or 'Лист'
        name, i = base, 2
        while name in taken:
            suffix = f'_{i}'
            name, i = base[:31 - len(suffix)] + suffix, i + 1
        taken.add(name)
        return name

    def parse_table_file_all(fname: str, raw: bytes) -> list:
        """Все листы xlsx/xlsm → [(имя, шапка, строки)]. Остальные форматы — один лист."""
        import io
        ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
        if ext in ('xlsx', 'xlsm'):
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(raw), data_only=True)
            out = []
            for ws in wb.worksheets[:300]:
                if ws.sheet_state != 'visible':
                    continue
                vals = [r for r in ws.iter_rows(values_only=True)
                        if any(v not in (None, '') for v in (r or ()))]
                if not vals:
                    continue
                header = [str(x or '').strip() or f'col{i + 1}' for i, x in enumerate(vals[0])]
                out.append((ws.title, header,
                            [[_num(x) for x in r] + [''] * max(0, len(header) - len(r)) for r in vals[1:]]))
            return out
        header, rows = parse_table_file(fname, raw)
        return [(None, header, rows)] if header else []

    with st.expander('📎 Прикрепить файл таблицы (xlsx, xls, ods, csv, json)', expanded=False):
        st.caption('Каждый лист файла станет листом здесь и в мастере на Яндекс.Диске — там хранится навсегда. '
                   'Оригинал тоже уйдёт на Яндекс.Диск.')
        upf = st.file_uploader('Файл таблицы', type=['xlsx', 'xlsm', 'xls', 'ods', 'csv', 'tsv', 'txt', 'json'],
                               key='table_file', label_visibility='collapsed')
        if upf is not None and st.button('📥 Импортировать (все листы)'):
            with st.spinner('Импортирую...'):
                try:
                    parts = parse_table_file_all(upf.name, upf.getvalue())
                    if not parts:
                        st.error('Файл пустой.')
                        st.stop()
                    import storage as _st2
                    taken = set(_st2.read_all_sheets().keys())
                    done, skipped, total = [], [], 0
                    try:
                        import yandex_store as _ysd
                        _ysd.defer(True)
                    except Exception:
                        pass
                    try:
                        for nm, header, rows_f in parts:
                            try:
                                if not nm:
                                    nm = (upf.name.rsplit('.', 1)[0] if '.' in upf.name else upf.name)
                                nm = clean_sheet_name(nm, taken)
                                _st2.write_sheet_local(nm, header, rows_f)
                                done.append(f'«{nm}»: {len(rows_f)}')
                                total += len(rows_f)
                            except Exception as e:
                                skipped.append(f'{nm or "?"}: {str(e)[:80]}')
                    finally:
                        try:
                            import yandex_store as _ysd2
                            _ysd2.defer(False)
                        except Exception:
                            pass
                    try:
                        import yandex_store as _ys8
                        _ls8 = _ys8.last_status()
                        if _ls8.get('ok'):
                            pushed = ' + мастер на Яндекс.Диске (навсегда)'
                        elif _ls8.get('ok') is None:
                            pushed = f" + ⏳ ({_ls8.get('reason', '')[:80]})"
                        else:
                            pushed = f" + ⚠️ только локально ({_ls8.get('reason', '')[:80]})"
                    except Exception:
                        pushed = ' + ⏳ статус Диска неизвестен'
                    arch = ''
                    tok = os.environ.get('YANDEX_DISK_TOKEN', '').strip()
                    if tok:
                        try:
                            import io as _io
                            import yadisk
                            y = yadisk.YaDisk(token=tok)
                            for _d in ('disk:/Лагерь', 'disk:/Лагерь/Файлы'):
                                if not y.exists(_d):
                                    y.mkdir(_d)
                            y.upload(_io.BytesIO(upf.getvalue()),
                                     f'disk:/Лагерь/Файлы/{upf.name}', overwrite=True)
                            arch = ' + оригинал на Яндекс.Диске'
                        except Exception as e:
                            arch = f' (Яндекс-архив: {str(e)[:120]})'
                    st.session_state['_last_edit'] = (
                        f'✅ Импорт: листов {len(done)} ({", ".join(done)[:200]}), строк всего {total}{pushed}{arch}'
                        + (f'. Пропущено: {"; ".join(skipped)[:200]}' if skipped else '') + '.')
                    st.rerun()
                except Exception as e:
                    st.error(f'Не импортировалось: {e}')

    for name, (heads, rows) in all_sheets.items():
        # каждая таблица сворачивается (Общая открыта по умолчанию); все правятся прямо тут
        with st.expander(f'{name} — {len(rows)} строк', expanded=(name == 'Общая')):
            if not rows:
                st.caption('Пусто')
                continue
            # порядок колонок как в шапке листа
            import storage as _st
            table = [{h: r.get(_st.HEADER_TO_KEY.get(h, h.lower()), '') for h in (heads or [])} for r in rows]
            st.caption('Двойной клик по ячейке — править, Enter — готово. Потом «Сохранить правки».'
                       + ('' if name == 'Общая' else ' Правки сезона уходят и в «Общую»; удалённое здесь удаляется везде.'))
            try:
                _csv_name, _csv_bytes = _st.export_csv(name)
                st.download_button('⬇ Скачать CSV', data=_csv_bytes,
                                   file_name=_csv_name, mime='text/csv',
                                   key=f'csv_{name}')
            except Exception as e:
                st.caption(f'CSV не собрался: {e}')
            lock = ([heads[0]] if heads else []) + ([heads[1]] if len(heads) > 1 else [])
            edited = st.data_editor(table, use_container_width=True, num_rows='dynamic',
                                    key=f'ed_{name}', hide_index=True, disabled=lock)
            if st.button('💾 Сохранить правки', key=f'sv_{name}'):
                with st.spinner('Сохраняю правки (пишу на Диск)...'):
                    try:
                        recs_ed = edited.to_dict('records') if hasattr(edited, 'to_dict') else list(edited)
                        rep = _st.apply_table_edits(name, heads, rows, recs_ed)
                    except Exception as e:
                        st.error(f'Не сохранилось: {e}')
                        st.stop()
                st.session_state['_last_edit'] = '✅ ' + rep
                st.rerun()
            st.divider()
            st.caption('✏️ Или правим запись вручную (без таблицы):')
            opts = []
            for i, r in enumerate(rows):
                preview = ' | '.join(str(r.get(_st.HEADER_TO_KEY.get(h, h.lower()), ''))
                                     for h in (heads or [])[:3])
                opts.append(f'{i + 1}. ' + (preview.strip(' |')[:60] or '(пустая строка)'))
            _fxk = f'fx_{name}'
            _cur = st.session_state.get(_fxk, 0)
            if not isinstance(_cur, int) or _cur < 0 or _cur >= len(rows):
                _cur = 0
                st.session_state[_fxk] = 0
            bc1, bc2, bc3 = st.columns([1, 1, 4])
            with bc1:
                if st.button('◀', key=f'fxp_{name}', use_container_width=True):
                    st.session_state[_fxk] = max(0, _cur - 1)
                    st.rerun()
            with bc2:
                if st.button('▶', key=f'fxn_{name}', use_container_width=True):
                    st.session_state[_fxk] = min(len(rows) - 1, _cur + 1)
                    st.rerun()
            with bc3:
                st.caption(f"Строка {_cur + 1} из {len(rows)}")
            sel = max(0, min(st.session_state.get(_fxk, 0), len(rows) - 1))
            st.caption(opts[sel] if sel < len(opts) else '')
            cur = rows[sel]
            if cur.get('id'):
                st.caption(f"ID: {cur.get('id')} (не меняется)")
            vals = {}
            for ci, h in enumerate(heads or []):
                k = _st.HEADER_TO_KEY.get(h, h.lower())
                if k == 'id':
                    continue
                vals[h] = st.text_input(h, value=str(cur.get(k, '')), key=f'fx_{name}_{sel}_{ci}')
            c1, c2 = st.columns(2)
            with c1:
                if st.button('💾 Сохранить запись', key=f'fxs_{name}'):
                    base = [{h: r.get(_st.HEADER_TO_KEY.get(h, h.lower()), '') for h in (heads or [])}
                            for r in rows]
                    base[sel] = {h: vals.get(h, base[sel][h]) for h in (heads or [])}
                    with st.spinner('Сохраняю (пишу на Диск)...'):
                        try:
                            rep = _st.apply_table_edits(name, heads, rows, base)
                        except Exception as e:
                            st.error(f'Не сохранилось: {e}')
                            st.stop()
                    st.session_state['_last_edit'] = '✅ ' + rep
                    st.rerun()
            with c2:
                if st.button('🗑 Удалить строку', key=f'fxd_{name}'):
                    base = [{h: r.get(_st.HEADER_TO_KEY.get(h, h.lower()), '') for h in (heads or [])}
                            for r in rows]
                    del base[sel]
                    with st.spinner('Удаляю (пишу на Диск)...'):
                        try:
                            rep = _st.apply_table_edits(name, heads, rows, base)
                        except Exception as e:
                            st.error(f'Не удалилось: {e}')
                            st.stop()
                    st.session_state['_last_edit'] = '✅ ' + rep
                    st.rerun()
