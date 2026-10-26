import logging
from typing import cast

import gspread
from google.oauth2.service_account import Credentials

from app.utils.retry import run_with_retries


def _get_column_index(header: list[str], column_name: str) -> int:
    for idx, value in enumerate(header, start=1):
        if value.strip() == column_name:
            return idx
    raise ValueError(f"Колонка '{column_name}' не найдена в заголовках")


def _get_or_create_worksheet(
    spreadsheet: gspread.Spreadsheet,
    worksheet_name: str,
    logger: logging.Logger,
) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        logger.info("Лист '%s' не найден, создаем новый", worksheet_name)
        return spreadsheet.add_worksheet(title=worksheet_name, rows=1, cols=2)


def write_missing_races(
    sheet_id: str,
    worksheet_name: str,
    rows: list[tuple[str, str, str]],
    credentials_path: str,
    logger: logging.Logger,
) -> int:
    def _action() -> int:
        credentials = Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = _get_or_create_worksheet(spreadsheet, worksheet_name, logger)

        worksheet.clear()
        if not rows:
            logger.info("Лист Missing races очищен, новых ссылок нет")
            return worksheet.id

        values = [["Источник", "Ссылка", "Координаты"]]
        values.extend([[source, url, coords] for source, url, coords in rows])
        worksheet.update(values, value_input_option="RAW")
        return worksheet.id

    return run_with_retries(_action, logger=logger, action_name="запись Missing races")


def fetch_known_websites(
    sheet_id: str,
    worksheet_name: str,
    url_column: str,
    credentials_path: str,
    logger: logging.Logger,
) -> list[str]:
    """Возвращает сырые значения колонки WEBSITE (без заголовка, без пустых).

    Сырые URL нужны для построения индекса сопоставления (host/path), а не
    только множества нормализованных строк.
    """

    def _action() -> list[str]:
        credentials = Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        client = gspread.authorize(credentials)
        worksheet = client.open_by_key(sheet_id).worksheet(worksheet_name)

        column_index: int
        if url_column.isdigit():
            column_index = int(url_column)
        else:
            header = worksheet.row_values(1)
            column_index = _get_column_index(header, url_column)

        values = worksheet.col_values(column_index)
        if values:
            values = values[1:]

        websites = [value.strip() for value in values if value and value.strip()]
        return cast(list[str], websites)

    return run_with_retries(_action, logger=logger, action_name="чтение Google Sheets")


def fetch_known_names(
    sheet_id: str,
    worksheet_name: str,
    name_columns: tuple[str, ...],
    credentials_path: str,
    logger: logging.Logger,
) -> list[str]:
    """Возвращает названия трасс из указанных колонок (RACE NAME, RACE NAME (PT))."""

    def _action() -> list[str]:
        credentials = Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        client = gspread.authorize(credentials)
        worksheet = client.open_by_key(sheet_id).worksheet(worksheet_name)
        header = worksheet.row_values(1)

        names: list[str] = []
        for column_name in name_columns:
            try:
                column_index = _get_column_index(header, column_name)
            except ValueError:
                logger.warning("Колонка названия '%s' не найдена, пропуск", column_name)
                continue
            values = worksheet.col_values(column_index)[1:]
            names.extend(value.strip() for value in values if value and value.strip())
        return cast(list[str], names)

    return run_with_retries(_action, logger=logger, action_name="чтение названий RACES")


def fetch_worksheet_gid(
    sheet_id: str,
    worksheet_name: str,
    credentials_path: str,
    logger: logging.Logger,
) -> int:
    def _action() -> int:
        credentials = Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = _get_or_create_worksheet(spreadsheet, worksheet_name, logger)
        return worksheet.id

    return run_with_retries(_action, logger=logger, action_name="чтение gid листа")


def filter_country_records(rows, country):
    """Пустая страна старых строк — Portugal; другие страны не входят в историю."""
    aliases = {'': 'pt', 'pt': 'pt', 'portugal': 'pt', 'португалия': 'pt',
               'es': 'es', 'spain': 'es', 'españa': 'es', 'espana': 'es', 'испания': 'es'}
    selected = []
    inherited = 'pt'
    for row in rows:
        raw = str(row.get('COUNTRY') or '').strip().casefold()
        if raw or row.get('ID') or row.get('STATUS'):
            inherited = aliases.get(raw)
        if inherited == country:
            selected.append(dict(row, COUNTRY=inherited))
    return selected


def fetch_country_records(sheet_id, worksheet_name, credentials_path, logger, country, url_column="WEBSITE"):
    def action():
        credentials = Credentials.from_service_account_file(
            credentials_path, scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
        sheet = gspread.authorize(credentials).open_by_key(sheet_id).worksheet(worksheet_name)
        values = sheet.get_all_values()
        if not values:
            return []
        headers = values[0]
        if country == 'es' and 'COUNTRY' not in headers:
            raise ValueError('В общей таблице нужна колонка COUNTRY')
        if headers.count('COUNTRY') > 1:
            raise ValueError('Колонка COUNTRY не должна повторяться')
        if str(url_column).isdigit():
            index = int(url_column) - 1
            if not 0 <= index < len(headers):
                raise ValueError('Некорректный номер URL_COLUMN')
            url_name = headers[index]
        else:
            url_name = url_column
            if url_name not in headers:
                raise ValueError(f'Колонка {url_name!r} не найдена')
        rows = [dict(zip(headers, values_row)) for values_row in values[1:]]
        for row in rows:
            row['WEBSITE'] = row.get(url_name, '')
        return filter_country_records(rows, country)
    return run_with_retries(action, logger=logger, action_name='чтение истории страны')
