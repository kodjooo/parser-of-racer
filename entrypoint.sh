#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/logs

target_hour=6
target_minute=2
run_startup="${RUN_SMOKE_ON_START:-true}"

if [ "$run_startup" = "true" ]; then
  echo "$(date -Is) Тестовый запуск при старте контейнера" >> /app/logs/cron.log
  python -m app.main >> /app/logs/cron.log 2>&1 || true
fi

while true; do
  now_date=$(date +%F)
  now_time=$(date +%H:%M)
  target_time=$(printf "%02d:%02d" "$target_hour" "$target_minute")

  if [ "$now_time" = "$target_time" ]; then
    echo "$(date -Is) Запуск по расписанию ${now_date} ${now_time}" >> /app/logs/cron.log
    python -m app.main >> /app/logs/cron.log 2>&1 || true
    sleep 60
  else
    sleep 20
  fi
done
