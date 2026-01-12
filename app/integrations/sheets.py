import logging
from typing import cast

import gspread
from google.oauth2.service_account import Credentials

from app.integrations.url_normalize import normalize_url
from app.utils.retry import run_with_retries


def _get_column_index(header: list[str], column_name: str) -> int:
    for idx, value in enumerate(header, start=1):
        if value.strip() == column_name:
            return idx
    raise ValueError(f"Колонка '{column_name}' не найдена в заголовках")


def fetch_known_urls(
    sheet_id: str,
    worksheet_name: str,
    url_column: str,
    credentials_path: str,
    logger: logging.Logger,
) -> set[str]:
    def _action() -> set[str]:
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

        normalized = {
            normalize_url(value)
            for value in values
            if value and value.strip()
        }
        return cast(set[str], normalized)

    return run_with_retries(_action, logger=logger, action_name="чтение Google Sheets")
