Архитектура Race Monitor (Portugal)

Общая идея
- Один контейнер запускает Python-скрипт по требованию или по расписанию на сервере, также доступен локальный запуск.
- Скрипт парсит два источника, сравнивает ссылки с Google Sheets и отправляет новые ссылки в Telegram.
- Для защиты от спама используется локальное хранилище состояния в JSON.

Компоненты
- app/main.py: оркестрация пайплайна, логирование, обработка ошибок, выходной код.
- app/config.py: загрузка и валидация конфигурации из .env.
- app/sources/: парсинг источников с Playwright (две независимые реализации), ожидание смены месяца по #evcal_cur (таймаут 10 секунд, ретраи с паузой 10 секунд, debug-лог маркеров) с fallback на изменение списка ссылок.
- app/integrations/sheets.py: чтение URL из Google Sheets через gspread.
- app/integrations/telegram.py: формирование и отправка уведомлений с чанками через Telethon.
- app/integrations/state.py: хранение notified_store в JSON и очистка.
- app/integrations/url_normalize.py: нормализация URL для дедупликации.
- app/utils/retry.py: ретраи сетевых операций.

Поток данных
1) Загрузка конфигурации и логгеров.
2) Чтение известных URL из Google Sheets -> known_urls.
3) Загрузка notified_store -> notified_set.
4) Парсинг источников -> карты {normalized: original}.
5) Вычисление to_notify по каждому источнику.
6) Формирование сообщений и отправка в Telegram (Telethon, или DRY_RUN).
7) Обновление notified_store и очистка известных URL.

Хранилище состояния
- Файл JSON по пути STATE_PATH (по умолчанию ./data/notified.json).
- Ключи: нормализованные URL, значения: метаданные времени и источника.

Docker
- Один сервис race-monitor в docker-compose.yml.
- Тома для data/ и logs/ подключаются как volume.
- google-credentials.json монтируется read-only.
- Базовый образ Docker: mcr.microsoft.com/playwright/python:v1.46.0-jammy (включает Chromium).
- В образ копируются тесты для запуска pytest внутри контейнера.

Локальный запуск
- Используется virtualenv, зависимости из requirements.txt.
- Требуется установить Chromium через Playwright.
- Для запуска предусмотрен скрипт run_local.sh.
