#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/logs

cat > /etc/cron.d/race-monitor <<'CRON'
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

2 6 * * * root python -m app.main >> /app/logs/cron.log 2>&1
CRON

chmod 0644 /etc/cron.d/race-monitor
crontab /etc/cron.d/race-monitor

cron -f
