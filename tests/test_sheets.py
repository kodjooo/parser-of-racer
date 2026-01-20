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
