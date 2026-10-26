"""Испанский мониторинг: отдельный запуск, общая таблица истории, свой список новых."""
import json
import logging
import os
import gspread
from google.oauth2.service_account import Credentials
from app.integrations.matching import KnownIndex, MatchConfig, normalize_event_name
from app.integrations.url_normalize import normalize_url
from app.integrations.sheets import _get_or_create_worksheet
from app.integrations.telegram import send_message
from app.sources.spanish_structured import scrape_source, validate_source


def select_new_events(candidates, known_rows):
    rows = [r for r in known_rows if str(r.get('COUNTRY') or '').strip().casefold()
            in ('es', 'spain', 'españa', 'espana', 'испания')]
    out = []
    seen = set()
    for event in candidates:
        # Совпадения URL проверяются в рамках того же года издания.
        year = event['date'][:4]
        relevant = []
        for row in rows:
            date = str(row.get('EVENT START DATE') or '').strip()
            known_year = date[:4] if len(date) >= 10 and date[4] == '-' else date[-4:]
            if not known_year.isdigit() or known_year == year:
                relevant.append(row)
        index = KnownIndex([r.get('WEBSITE', '') for r in relevant], MatchConfig(),
                           names=[r.get(k, '') for r in relevant for k in ('RACE NAME', 'RACE NAME (ES)')])
        if index.match(event['url'], event['name']):
            continue
        identity = (normalize_event_name(event['name']), event['date'],
                    normalize_event_name(event.get('city', '')))
        url_key = (normalize_url(event['url']), event['date'])
        if identity in seen or url_key in seen:
            continue
        seen.update((identity, url_key))
        out.append(event)
    return out


def run_spain(config):
    logger = logging.getLogger('race_monitor.es')
    sources = json.loads(os.getenv('ES_SOURCES_JSON', '[]'))
    if not isinstance(sources, list) or not sources:
        raise ValueError('ES_SOURCES_JSON пуст: сначала согласуйте источники с Антонио')
    for source in sources:
        validate_source(source)
    target = os.getenv('ES_MISSING_WORKSHEET_NAME', 'Missing races ES')
    if target in (config.worksheet_name, config.missing_worksheet_name):
        raise ValueError('Испанский список новых не должен перезаписывать RACES или Missing races PT')
    credentials = Credentials.from_service_account_file(config.google_credentials_path,
                    scopes=['https://www.googleapis.com/auth/spreadsheets.readonly' if config.dry_run
                            else 'https://www.googleapis.com/auth/spreadsheets'])
    client = gspread.authorize(credentials)
    book = client.open_by_key(config.sheet_id)
    sheet = book.worksheet(config.worksheet_name)
    if 'COUNTRY' not in sheet.row_values(1):
        raise ValueError('В общей таблице нужна колонка COUNTRY; пустые старые строки считаются Португалией')
    known_rows = sheet.get_all_records()
    candidates = []
    # Все источники должны успешно завершиться, прежде чем менять список/отправлять сообщение.
    for source in sources:
        for event in scrape_source(source, logger, max_pages=config.max_pagination_pages):
            candidates.append(dict(event, source=source['name']))
    events = select_new_events(candidates, known_rows)
    if config.dry_run:
        logger.info('DRY_RUN Spain: %s', json.dumps(events, ensure_ascii=False))
        return 0
    output = _get_or_create_worksheet(book, target, logger)
    values = [['Источник', 'Ссылка', 'Координаты', 'COUNTRY', 'Название', 'Дата', 'Регион', 'Город']]
    values.extend([e['source'], e['url'], e['coords'], 'Spain', e['name'], e['date'],
                    e['region'], e['city']] for e in events)
    output.resize(rows=max(len(values), 2), cols=8)
    output.update(values=values, value_input_option='RAW')
    if events:
        send_message(config.telegram_api_id, config.telegram_api_hash, config.telegram_session_path,
                     config.telegram_session_string, config.telegram_target,
                     f'<b>{len(events)}</b> Spanish events are not in our table.\n'
                     f'https://docs.google.com/spreadsheets/d/{config.sheet_id}/edit#gid={output.id}', logger)
    return 0
