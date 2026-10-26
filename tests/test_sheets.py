import logging

import gspread

from app.integrations.sheets import _get_or_create_worksheet


class _FakeWorksheet:
    def __init__(self, title: str) -> None:
        self.title = title


class _FakeSpreadsheet:
    def __init__(self, existing: dict[str, _FakeWorksheet]) -> None:
        self._worksheets = existing
        self.added: list[str] = []

    def worksheet(self, name: str) -> _FakeWorksheet:
        if name in self._worksheets:
            return self._worksheets[name]
        raise gspread.exceptions.WorksheetNotFound(name)

    def add_worksheet(self, title: str, rows: int, cols: int) -> _FakeWorksheet:
        worksheet = _FakeWorksheet(title)
        self._worksheets[title] = worksheet
        self.added.append(title)
        return worksheet


def test_get_or_create_worksheet_existing() -> None:
    logger = logging.getLogger("test")
    worksheet = _FakeWorksheet("Missing races")
    spreadsheet = _FakeSpreadsheet({"Missing races": worksheet})

    result = _get_or_create_worksheet(spreadsheet, "Missing races", logger)

    assert result is worksheet
    assert spreadsheet.added == []


def test_get_or_create_worksheet_missing() -> None:
    logger = logging.getLogger("test")
    spreadsheet = _FakeSpreadsheet({})

    result = _get_or_create_worksheet(spreadsheet, "Missing races", logger)

    assert result.title == "Missing races"
    assert spreadsheet.added == ["Missing races"]


def test_shared_history_is_scoped_by_country():
    from app.integrations.sheets import filter_country_records
    rows = [{'ID': 'legacy'}, {'ID': 'pt', 'COUNTRY': 'Portugal'},
            {'ID': 'es', 'COUNTRY': 'Spain'}, {'ID': 'unknown', 'COUNTRY': 'France'}]
    assert [row['ID'] for row in filter_country_records(rows, 'pt')] == ['legacy', 'pt']
    assert [row['ID'] for row in filter_country_records(rows, 'es')] == ['es']


def test_variations_inherit_country_but_new_legacy_parent_is_portugal():
    from app.integrations.sheets import filter_country_records
    rows = [{'ID': 'es', 'COUNTRY': 'Spain'}, {'WEBSITE': 'https://example.es/child'},
            {'ID': 'legacy', 'COUNTRY': ''}, {'WEBSITE': 'https://example.pt/child'}]
    assert len(filter_country_records(rows, 'es')) == 2
    assert len(filter_country_records(rows, 'pt')) == 2
    assert filter_country_records(rows, 'es')[1]['COUNTRY'] == 'es'


def test_country_history_preserves_numeric_url_column(monkeypatch):
    from app.integrations import sheets
    class Sheet:
        def get_all_values(self):
            return [['ID', 'COUNTRY', 'Link'], ['1', 'Spain', 'https://event.es']]
    class Book:
        def worksheet(self, name): return Sheet()
    class Client:
        def open_by_key(self, key): return Book()
    monkeypatch.setattr(sheets.Credentials, 'from_service_account_file', lambda *a, **k: None)
    monkeypatch.setattr(sheets.gspread, 'authorize', lambda credentials: Client())
    result = sheets.fetch_country_records('test', 'RACES', 'unused', logging.getLogger('test'), 'es', '3')
    assert result[0]['WEBSITE'] == 'https://event.es'
