"""Расписание общего сборщика с сохранением дня завершённого прохода."""
import datetime as dt
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from zoneinfo import ZoneInfo
from app.unified import atomic_json


def next_due(now, hour, minute, last_date, startup=False):
    target=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if startup:return now
    if last_date==now.date().isoformat():return target+dt.timedelta(days=1)
    if last_date is None:
        return target if target>now else target+dt.timedelta(days=1)
    if last_date!=now.date().isoformat() and now>=target:return now
    return target if target>now else target+dt.timedelta(days=1)


def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    zone=ZoneInfo(os.getenv('TZ','Europe/Moscow'));hour=int(os.getenv('SCHEDULED_HOUR','0'));minute=int(os.getenv('SCHEDULED_MINUTE','15'))
    if not 0<=hour<24 or not 0<=minute<60:raise ValueError('Некорректное расписание')
    path=Path(os.getenv('STATE_PATH','/app/data/unified.json')).with_name('schedule.json')
    startup=os.getenv('RUN_SMOKE_ON_START','false').lower()=='true';job=None
    def stop(signum,frame):
        if job and job.poll() is None:
            os.killpg(job.pid,signal.SIGTERM)
            try:job.wait(timeout=20)
            except subprocess.TimeoutExpired:os.killpg(job.pid,signal.SIGKILL);job.wait()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while True:
        previous=json.loads(path.read_text()).get('completed_date') if path.exists() else None
        now=dt.datetime.now(zone);due=next_due(now,hour,minute,previous,startup)
        logging.info('Следующий общий сбор: %s; TZ=%s',due.isoformat(),zone.key)
        while dt.datetime.now(zone)<due:time.sleep(min(20,max(.1,(due-dt.datetime.now(zone)).total_seconds())))
        startup=False
        job=subprocess.Popen([sys.executable,'-m','app.main'],start_new_session=True)
        code=job.wait();job=None
        atomic_json(path,{'completed_date':dt.datetime.now(zone).date().isoformat(),'exit_code':code})
        logging.info('Общий сбор завершён: код=%s',code)


if __name__=='__main__':main()
