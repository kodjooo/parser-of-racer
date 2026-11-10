"""Общий PT/ES-монитор: изолированный сбор, одна таблица и один дайджест."""
import datetime as dt
import html
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

from app.integrations.matching import KnownIndex, MatchConfig, normalize_event_name
from app.integrations.sheets import filter_country_records, _get_or_create_worksheet
from app.integrations.telegram import send_message
from app.integrations.url_normalize import normalize_url
from app.spain import select_new_events

HEADERS = ['COUNTRY', 'Источник', 'Название', 'Дата', 'Ссылка', 'Координаты', 'Регион', 'Город']
FIELDS = ['country', 'source', 'name', 'date', 'url', 'coords', 'region', 'city']
SOURCES = {
    'pt_calendar': ('Portugal', 'portugalruncalendar.com'),
    'pt_running': ('Portugal', 'portugalrunning.com'),
    'es_life': ('Spain', 'Running.life'),
    'es_rock': ('Spain', 'RockTheSport'),
}


def event_key(event):
    return '|'.join((event['country'], normalize_url(event['url']), event.get('date', '')))


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush(); os.fsync(handle.fileno())
    temporary.replace(path)


def load_state(path):
    if Path(path).exists():
        data = json.loads(Path(path).read_text())
        if data.get('schema') != 1:
            raise ValueError('Неизвестная схема общего состояния')
        return data
    return {'schema': 1, 'notified': {}, 'legacy_notified': {'pt': {}, 'es': {}}, 'sources': {}}


def was_notified(event, state):
    if event_key(event) in state.get('notified', {}):
        return True
    country = 'es' if event['country'] == 'Spain' else 'pt'
    old = state.get('legacy_notified', {}).get(country, {})
    url = normalize_url(event['url'])
    # Старые PT-ключи не содержали даты; сохраняем их прежнюю семантику.
    return url in old or (url + '|' + event.get('date', '')) in old


def collect_worker(source, timeout):
    with tempfile.TemporaryDirectory(prefix='rf-source-') as directory:
        output = Path(directory) / 'events.json'
        process = subprocess.Popen([sys.executable, '-m', 'app.source_worker', source, str(output)],
                                   start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
            raise TimeoutError(f'{SOURCES[source][1]}: превышен лимит {timeout} секунд')
        if code or not output.exists():
            raise RuntimeError(f'{SOURCES[source][1]}: сбор завершился с кодом {code}')
        events = json.loads(output.read_text())
        if not isinstance(events, list):
            raise ValueError('Источник вернул некорректный список')
        for event in events:
            if event.get('country') != SOURCES[source][0] or not str(event.get('url', '')).startswith(('https://', 'http://')):
                raise ValueError('Некорректная страна или URL источника')
        return events


def missing_events(candidates, known_rows, config):
    es = [event for event in candidates if event['country'] == 'Spain']
    out = select_new_events(es, filter_country_records(known_rows, 'es'))
    rows = filter_country_records(known_rows, 'pt')
    index = KnownIndex([r.get('WEBSITE', '') for r in rows], MatchConfig(
        lang_prefixes=config.canonical_lang_prefixes, subpage_segments=config.subpage_segments,
        container_segments=config.container_segments, service_blocklist=config.service_page_blocklist,
        block_homepage=config.block_homepage, block_generic_forms=config.block_generic_forms,
        cross_platform_match=config.cross_platform_match,
        cross_platform_min_slug_len=config.cross_platform_min_slug_len, slug_stoplist=config.slug_stoplist,
        name_match=config.name_match), names=[r.get(k, '') for r in rows for k in config.race_name_columns])
    seen_urls, seen_names = set(), set()
    import re
    for event in candidates:
        if event['country'] != 'Portugal' or index.match(event['url'], event.get('name') or None):
            continue
        url = normalize_url(event['url']); name = event.get('name', '')
        key = normalize_event_name(name) if re.search(r'20\d{2}', name) else ''
        if url in seen_urls or (key and key in seen_names):
            continue
        seen_urls.add(url)
        if key: seen_names.add(key)
        out.append(event)
    return sorted(out, key=lambda e: (e['country'], e.get('date') or '9999', e.get('name', ''), e['url']))


def merge_results(state, collector, now):
    results, errors, counts = {}, {}, {}
    for source in SOURCES:
        try:
            logging.getLogger('race_monitor.unified').info('Сбор источника %s',source)
            events = collector(source)
            if not events and state['sources'].get(source, {}).get('events'):
                raise ValueError('Источник неожиданно вернул пустой список')
            state['sources'][source] = {'events': events, 'last_success': now}
            results[source] = events; counts[source] = len(events)
            logging.getLogger('race_monitor.unified').info('%s: получено %s событий',source,len(events))
        except Exception as exc:
            logging.getLogger('race_monitor.unified').exception('Ошибка источника %s', source)
            errors[source] = str(exc)[:250]
            results[source] = state['sources'].get(source, {}).get('events', [])
            counts[source] = len(results[source])
    # Свежие результаты получают приоритет перед сохранёнными при кросс-дедупликации.
    events = [e for source in SOURCES if source not in errors for e in results[source]]
    events += [e for source in SOURCES if source in errors for e in results[source]]
    events += state.get('legacy_rows', [])
    return events, errors, counts


def write_rows(book, target, events, logger):
    if target == os.getenv('WORKSHEET_NAME', 'RACES'):
        raise ValueError('Сборщик не может записывать основную RACES')
    worksheet = _get_or_create_worksheet(book, target, logger)
    values = [HEADERS] + [[event.get(field, '') for field in FIELDS] for event in events]
    if worksheet.row_count < len(values): worksheet.add_rows(len(values)-worksheet.row_count)
    if worksheet.col_count < len(HEADERS): worksheet.add_cols(len(HEADERS)-worksheet.col_count)
    # Одним запросом заменяем список и очищаем прежний хвост, без clear() перед записью.
    total = max(len(values), len(worksheet.get_all_values()))
    worksheet.update(values=values + [['']*len(HEADERS)]*(total-len(values)), range_name=f'A1:H{total}', value_input_option='RAW')
    return worksheet.id


def digest_message(events, new, errors, link, date):
    lines = [f'<b>RaceFinder — {date}</b>']
    for country, label in [('Portugal','PT'), ('Spain','ES')]:
        lines.append(f'{label}: {sum(e["country"]==country for e in events)} candidates, {sum(e["country"]==country for e in new)} newly detected')
    if errors:
        lines.append('Some sources failed; their previous results were retained:')
        lines.extend('• '+html.escape(SOURCES[s][1])+': '+html.escape(message) for s,message in errors.items())
    else: lines.append('All 4 sources completed successfully.')
    lines.append(f'<a href="{html.escape(link, quote=True)}">View the combined event list</a>')
    return '\n'.join(lines)


def _run_unified(config):
    logger = logging.getLogger('race_monitor.unified')
    if config.worksheet_name == config.missing_worksheet_name:
        raise ValueError('Вход и выход сборщика должны быть разными вкладками')
    timeout = int(os.getenv('SOURCE_TIMEOUT_SEC','1800'))
    if timeout <= 0: raise ValueError('SOURCE_TIMEOUT_SEC должен быть положительным')
    state = load_state(config.state_path)
    credentials = Credentials.from_service_account_file(config.google_credentials_path,
        scopes=['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
    book = gspread.authorize(credentials).open_by_key(config.sheet_id)
    values = book.worksheet(config.worksheet_name).get_all_values()
    if not values or values[0].count('COUNTRY') != 1:
        raise ValueError('В RACES нужна единственная колонка COUNTRY')
    rows = [dict(zip(values[0], row)) for row in values[1:]]
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    candidates, errors, counts = merge_results(state, lambda source: collect_worker(source,timeout), now)
    events = missing_events(candidates, rows, config)
    new = [event for event in events if not was_notified(event,state)]
    report = {'started_at':now, 'sources':counts, 'errors':errors, 'missing':len(events),
              'by_country':{c:sum(e['country']==c for e in events) for c in ('Portugal','Spain')},
              'new_notifications':len(new), 'dry_run':config.dry_run, 'telegram_sent':False}
    if config.dry_run:
        report['events']=events
        report['collected_sources']=state['sources']
        atomic_json(os.getenv('UNIFIED_REPORT_PATH','/app/logs/latest.json'),report)
        logger.info('DRY_RUN: %s', {k:v for k,v in report.items() if k not in ('events','collected_sources')})
        return 1 if errors else 0
    gid = write_rows(book,config.missing_worksheet_name,events,logger)
    state['last_run_at']=now
    atomic_json(config.state_path,state)
    report['sheet_gid']=gid
    local_date=dt.datetime.now(ZoneInfo(os.getenv('TZ','Europe/Moscow'))).date().isoformat()
    enabled=os.getenv('TELEGRAM_NOTIFICATIONS_ENABLED','true').lower()=='true'
    if enabled and state.get('last_digest_date') != local_date:
        try:
            send_message(config.telegram_api_id,config.telegram_api_hash,config.telegram_session_path,
                config.telegram_session_string,config.telegram_target,
                digest_message(events,new,errors,f'https://docs.google.com/spreadsheets/d/{config.sheet_id}/edit#gid={gid}',local_date),logger)
            for event in new: state['notified'][event_key(event)]={'last_notified_at':now,'source':event['source']}
            state['last_digest_date']=local_date
            atomic_json(config.state_path,state);report['telegram_sent']=True
        except Exception:
            report['telegram_error']=True
            atomic_json(os.getenv('UNIFIED_REPORT_PATH','/app/logs/latest.json'),report)
            raise
    atomic_json(os.getenv('UNIFIED_REPORT_PATH','/app/logs/latest.json'),report)
    logger.info('Единый монитор: %s',report)
    return 1 if errors else 0


def run_unified(config):
    import fcntl
    lock=Path(config.state_path+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Общий сборщик уже работает')
        return _run_unified(config)
