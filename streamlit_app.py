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
/* Радужный светящийся ободок, пока сайт думает (виден любой спиннер) */
div[data-testid="stAppViewContainer"]:has(div[data-testid="stSpinner"])::after {
  content: ""; position: fixed; inset: 6px; pointer-events: none; z-index: 9999999;
  border-radius: 18px; padding: 4px;
  background: linear-gradient(60deg,#ff004c,#ff8a00,#ffee00,#00e676,#00b0ff,#a100ff,#ff004c);
  background-size: 300% 300%;
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor; mask-composite: exclude;
  animation: rainbow-flow 2.5s linear infinite;
  filter: drop-shadow(0 0 14px rgba(255,0,220,.55)) drop-shadow(0 0 30px rgba(0,180,255,.35));
}
@keyframes rainbow-flow { to { background-position: 300% 0; } }
</style>''', unsafe_allow_html=True)
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
        # Новая запись тоже обязана улететь в Google (иначе сгорит при редеплое)
        try:
            import google_sync
            if google_sync.get_sheet_id() and os.path.exists(google_sync.TOKEN):
                shift = str(data.get('shift', ''))
                _sheets = ['Общая'] + ([shift] if shift in st_mod.SHEETS[1:] else [])
                with google_sync._API_LOCK:
                    _svc = google_sync._service('sheets', 'v4')
                    google_sync.ensure_sheet_structure(
                        google_sync.get_sheet_id(), heads, _sheets, _svc=_svc)
                    vals = [str(x or '') for x in st_mod._row_dict_to_list(heads, flat)]
                    google_sync.push_row(vals, 'Общая', _svc=_svc)
                    if shift in st_mod.SHEETS[1:]:
                        google_sync.push_row(vals, shift, _svc=_svc)
        except Exception as e:
            print(f'[Sheets] только локально ({e})')
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
                st.session_state['voice_done'] = None
                st.session_state['ta_gen'] = gen + 1
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
    _le = st.session_state.pop('_last_edit', None)
    if _le:
        st.success(_le)
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

    with st.expander('📎 Прикрепить файл таблицы (xlsx, xls, ods, csv, json)', expanded=False):
        st.caption('Файл станет листом здесь и в Google Sheets — там хранится навсегда. '
                   'Оригинал уйдёт на Яндекс.Диск, если задан YANDEX_DISK_TOKEN.')
        upf = st.file_uploader('Файл таблицы', type=['xlsx', 'xlsm', 'xls', 'ods', 'csv', 'tsv', 'txt', 'json'],
                               key='table_file', label_visibility='collapsed')
        if upf is not None and st.button('📥 Импортировать как лист'):
            with st.spinner('Импортирую...'):
                try:
                    header, rows_f = parse_table_file(upf.name, upf.getvalue())
                    if not header:
                        st.error('Файл пустой.')
                        st.stop()
                    base = (upf.name.rsplit('.', 1)[0] if '.' in upf.name else upf.name)
                    base = ''.join(c if (c.isalnum() or c in ' _-') else '_' for c in base).strip()[:30] or 'Лист'
                    import storage as _st2
                    _st2.write_sheet_local(base, header, rows_f)
                    pushed = ''
                    try:
                        import google_sync as _gs
                        if _gs.get_sheet_id():
                            with _gs._API_LOCK:
                                _svc2 = _gs._service('sheets', 'v4')
                                _gs.push_table(base, header, rows_f, _svc=_svc2)
                            pushed = ' + Google Sheets (навсегда)'
                    except Exception as e:
                        pushed = f' (в Google не улетело: {e})'
                    arch = ''
                    tok = os.environ.get('YANDEX_DISK_TOKEN', '').strip()
                    if tok:
                        try:
                            import io as _io
                            import yadisk
                            y = yadisk.YaDisk(token=tok)
                            if not y.exists('disk:/Лагерь/Файлы'):
                                y.mkdir('disk:/Лагерь/Файлы')
                            y.upload(_io.BytesIO(upf.getvalue()),
                                     f'disk:/Лагерь/Файлы/{upf.name}', overwrite=True)
                            arch = ' + оригинал на Яндекс.Диске'
                        except Exception as e:
                            arch = f' (Яндекс: {str(e)[:120]})'
                    st.session_state['_last_edit'] = (
                        f'✅ Лист «{base}»: {len(rows_f)} строк{pushed}{arch}.')
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
            lock = ([heads[0]] if heads else []) + ([heads[1]] if len(heads) > 1 else [])
            edited = st.data_editor(table, use_container_width=True, num_rows='dynamic',
                                    key=f'ed_{name}', hide_index=True, disabled=lock)
            if st.button('💾 Сохранить правки', key=f'sv_{name}'):
                with st.spinner('Сохраняю правки (пишу в Google)...'):
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
                    with st.spinner('Сохраняю (пишу в Google)...'):
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
                    with st.spinner('Удаляю (пишу в Google)...'):
                        try:
                            rep = _st.apply_table_edits(name, heads, rows, base)
                        except Exception as e:
                            st.error(f'Не удалилось: {e}')
                            st.stop()
                    st.session_state['_last_edit'] = '✅ ' + rep
                    st.rerun()
