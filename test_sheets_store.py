import gspread

from src.constants import SHEET_HEADERS
from src.sheets_store import SheetsStore, _cell_value, _column_letter


class FakeWorksheet:
    def __init__(self, spreadsheet, title):
        self.spreadsheet = spreadsheet
        self.title = title
        self.rows = []
        self.frozen = False

    def get_all_values(self):
        return self.rows

    def row_values(self, row):
        return self.rows[row - 1] if len(self.rows) >= row else []

    def update_title(self, title):
        del self.spreadsheet.by_title[self.title]
        self.title = title
        self.spreadsheet.by_title[title] = self

    def append_row(self, values, value_input_option=None):
        self.rows.append(list(values))

    def freeze(self, rows=None, cols=None):
        self.frozen = rows == 1


class FakeSpreadsheet:
    def __init__(self):
        first = FakeWorksheet(self, "工作表1")
        self.by_title = {first.title: first}

    def worksheet(self, title):
        try:
            return self.by_title[title]
        except KeyError as exc:
            raise gspread.WorksheetNotFound from exc

    def worksheets(self):
        return list(self.by_title.values())

    def add_worksheet(self, title, rows, cols):
        worksheet = FakeWorksheet(self, title)
        self.by_title[title] = worksheet
        return worksheet


def test_column_letters():
    assert _column_letter(1) == "A"
    assert _column_letter(26) == "Z"
    assert _column_letter(27) == "AA"


def test_cell_value_serializes_structures_as_json():
    assert _cell_value({"text": "中文"}) == '{"text":"中文"}'


def test_empty_default_sheet_is_reused_and_schema_created():
    store = object.__new__(SheetsStore)
    store.spreadsheet = FakeSpreadsheet()
    store.ensure_schema()

    assert set(store.spreadsheet.by_title) == set(SHEET_HEADERS)
    for name, headers in SHEET_HEADERS.items():
        worksheet = store.spreadsheet.by_title[name]
        assert worksheet.rows[0] == headers
        assert worksheet.frozen is True
