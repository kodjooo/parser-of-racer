# Race Monitor (Portugal)

Скрипт мониторинга новых ссылок на соревнования из двух источников с уведомлением в Telegram.

## Структура проекта

- `app/` — исходный код приложения (точка входа `app/main.py`).
- `tests/` — минимальные тесты.
- `requirements.txt` — зависимости Python.
- `Dockerfile` — инструкция для сборки контейнера.
- `docker-compose.yml` — запуск через Docker Desktop.
- `.env.example` — пример конфигурации.

## Запуск через Docker Desktop

```bash
docker compose build
docker compose run --rm race-monitor
```

## Локальный запуск (без Docker)

```bash
./run_local.sh
```

## Развертывание на сервере

1. Установить Docker и Docker Compose на сервер.
2. Склонировать репозиторий и подготовить `.env` и `google-credentials.json`.
3. Запустить контейнер: `docker compose run --rm race-monitor`.
4. Для расписания настроить cron на сервере, который будет выполнять команду из пункта 3 каждые 2 дня.
