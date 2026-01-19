Архитектура Race Monitor (Portugal)

Общая идея
- Один контейнер запускает Python-скрипт по требованию или по расписанию на сервере, также доступен локальный запуск.
- Скрипт парсит два источника, сравнивает ссылки с Google Sheets и отправляет новые ссылки в Telegram.
- Для защиты от спама используется локальное хранилище состояния в JSON.

Компоненты
- app/main.py: оркестрация пайплайна, логирование, обработка ошибок, выходной код.
- app/config.py: загрузка и валидация конфигурации из .env.
- app/sources/: парсинг источников с Playwright (две независимые реализации), для portugalruncalendar.com основной сценарий — клик по кнопке Próxima (SOURCE1_NEXT_BUTTON_SELECTOR с фильтром :not([disabled]) и debug-лог маркеров/состояния кнопки, количества ссылок в DOM, добавленных уникальных и дубликатов), остановка по неизменному маркеру списка; для portugalrunning.com обход ссылок месяца и заход в карточки, ожидание смены месяца по #evcal_cur (polling 10 секунд, ретраи с паузой 10 секунд, debug-лог маркеров и новых итоговых ссылок) с fallback на изменение списка ссылок.
- app/integrations/sheets.py: чтение URL из Google Sheets через gspread.
- app/integrations/telegram.py: формирование и отправка уведомлений с чанками через Telethon (поддержка @username и числовых id групп/супергрупп).
- app/integrations/state.py: хранение notified_store в JSON и очистка.
- app/integrations/url_normalize.py: нормализация URL для дедупликации.
- app/utils/retry.py: ретраи сетевых операций.

Поток данных
1) Загрузка конфигурации и логгеров.
2) Чтение известных URL из Google Sheets -> known_urls.
3) Загрузка notified_store -> notified_set.
4) Парсинг источников -> карты {normalized: original}.
5) Вычисление to_notify по каждому источнику.
6) Очистка листа Missing races и запись ссылок, отсутствующих в таблице (до анти-спама).
7) Формирование сообщения и отправка в Telegram (Telethon, или DRY_RUN).
8) Обновление notified_store и очистка известных URL (используется только для истории).

Хранилище состояния
- Файл JSON по пути STATE_PATH (по умолчанию ./data/notified.json).
- Ключи: нормализованные URL, значения: метаданные времени и источника.

Нормализация URL
- Удаляем протокол (http/https) и префикс www для повышения совпадений.

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
