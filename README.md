---
title: Секретарь лагеря
emoji: 📋
colorFrom: green
colorTo: blue
sdk: streamlit
sdk_version: 1.39.0
app_file: streamlit_app.py
pinned: false
---

# 📋 Секретарь лагеря (веб-версия)

Веб-копия десктопного секретаря (Tkinter, `app.py`) на Streamlit для бесплатного хостинга Hugging Face Spaces.
Tkinter-версия не тронута: веб — только новые файлы (`streamlit_app.py`, `web_bootstrap.py`).

## Возможности

- Вставка «каши» текстом → разбор (`brain.parse_client_text`) → проверка дублей → сохранение (`storage.upsert`)
- Статус Google (Таблица + Календарь), ссылка на Google-таблицу
- Напоминания о перезвоне (`reminders`), блок «пора перезвонить»
- ИИ-командная строка (`agent.execute`): «перенеси Иванова в Зиму 26», «поставь Иванову Оплачено»
- Голосовой ввод через микрофон браузера (скрывается, если нет модуля/аудио)
- Журнал действий в сессии

## Секреты (Settings → Variables and secrets в Space)

| Имя | Что это |
|---|---|
| `GEMINI_API_KEY` | Ключ Gemini для ИИ-разбора (без него — локальный regex-парсер) |
| `GOOGLE_TOKEN_JSON` | Содержимое `token.json` (OAuth-токен Google) — целиком, как текст |
| `GOOGLE_SHEET_ID` | ID Google-таблицы (как в файле `sheet.id`) |

Без секретов приложение работает в локальном режиме (данные в `clients.xlsx` в рабочей папке Space).

При первом запуске без `clients.xlsx`, но с подключенным Google, данные подтягиваются
из листа «Общая» Google Sheets (`web_bootstrap.pull_google_to_local`).

## Локальный запуск

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```
