#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
  echo ".env не найден. Скопируйте .env.example и заполните значения." >&2
  exit 1
fi

if [ ! -f google-credentials.json ]; then
  echo "google-credentials.json не найден. Добавьте файл сервисного аккаунта." >&2
  exit 1
fi

python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium

python -m app.main
