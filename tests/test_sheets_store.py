import gspread

from src.constants import SHEET_HEADERS
from src.sheets_store import (
    SheetsStore,
    _cell_value,
    _column_letter,
    _friendly_sheet_error,
    _google_api_detail,
)


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
    assert "ContinuityMemory" in store.spreadsheet.by_title
    assert "StudentRoster" in store.spreadsheet.by_title
    for name, headers in SHEET_HEADERS.items():
        worksheet = store.spreadsheet.by_title[name]
        assert worksheet.rows[0] == headers
        assert worksheet.frozen is True


def test_latest_continuity_returns_latest_ready_or_fallback_row():
    store = object.__new__(SheetsStore)
    store.read_all = lambda _sheet_name: [
        {
            "participant_id": "P001",
            "updated_at": "2026-09-10T10:00:00+08:00",
            "session_number": 1,
            "memory_status": "ready",
            "summary_text": "較早",
        },
        {
            "participant_id": "P001",
            "updated_at": "2026-09-11T10:00:00+08:00",
            "session_number": 2,
            "memory_status": "fallback",
            "summary_text": "最新",
        },
        {
            "participant_id": "P002",
            "updated_at": "2026-09-12T10:00:00+08:00",
            "session_number": 1,
            "memory_status": "ready",
            "summary_text": "其他人",
        },
    ]

    latest = store.latest_continuity("P001")
    assert latest is not None
    assert latest["summary_text"] == "最新"
    assert store.latest_continuity("P999") is None


def test_student_by_email_is_case_insensitive():
    store = object.__new__(SheetsStore)
    store.read_all = lambda _sheet_name: [
        {
            "participant_id": "SABC123",
            "school_email": "student@school.edu.tw",
            "first_verified_at": "2026-09-12T10:00:00+08:00",
        }
    ]

    row = store.student_by_email("STUDENT@SCHOOL.EDU.TW")
    assert row is not None
    assert row["participant_id"] == "SABC123"
    assert store.student_by_email("other@school.edu.tw") is None



class FakeResponse:
    status_code = 403

    def json(self):
        return {
            "error": {
                "code": 403,
                "message": "The caller does not have permission",
                "status": "PERMISSION_DENIED",
                "errors": [{"reason": "forbidden"}],
            }
        }


class FakeGoogleError(Exception):
    def __init__(self):
        super().__init__("APIError: 403")
        self.response = FakeResponse()


def test_google_api_detail_extracts_safe_403_reason():
    detail = _google_api_detail(FakeGoogleError())

    assert "status=PERMISSION_DENIED" in detail
    assert "reason=forbidden" in detail
    assert "The caller does not have permission" in detail


def test_friendly_sheet_error_includes_google_403_diagnostic():
    message = _friendly_sheet_error("寫入 Sessions 失敗", FakeGoogleError())

    assert "Google Sheets 權限驗證失敗（403）" in message
    assert "PERMISSION_DENIED" in message
    assert "The caller does not have permission" in message



def test_recover_and_get_usage_reads_each_sheet_once(monkeypatch):
    """一次快照完成自動補認列，避免每次學生登入重複抓取完整 ChatLogs。"""
    store = object.__new__(SheetsStore)
    session = {
        "session_id": "test-crash-28m",
        "participant_id": "P001",
        "mode": "practice",
        "started_at": "2026-10-18T14:23:58+08:00",
        "ended_at": "",
        "duration_seconds": "",
        "completion_status": "in_progress",
    }
    times = [
        ("student_counselor", "2026-10-18T14:25:46+08:00"),
        ("ai_client", "2026-10-18T14:25:48+08:00"),
        ("student_counselor", "2026-10-18T14:40:41+08:00"),
        ("ai_client", "2026-10-18T14:40:43+08:00"),
        ("student_counselor", "2026-10-18T14:51:28+08:00"),
        ("ai_client", "2026-10-18T14:51:32+08:00"),
    ]
    chat_rows = [
        {
            "turn_id": f"turn-{i}",
            "session_id": "test-crash-28m",
            "speaker_role": role,
            "timestamp": stamp,
        }
        for i, (role, stamp) in enumerate(times)
    ]
    records = {
        "Sessions": [session],
        "ChatLogs": chat_rows,
        "TimeRecoveryLedger": [],
    }
    calls = []
    store.read_all = lambda name: (calls.append(name), list(records[name]))[1]

    def fake_append(sheet_name, event):
        assert sheet_name == "TimeRecoveryLedger"
        records[sheet_name].append(event)

    store.append_record = fake_append

    # 模擬授課期間事後重新登入；不依賴測試機執行時間。
    from datetime import datetime, timezone
    import src.sheets_store as module

    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(module, "datetime", Clock)
    events, summary = store.recover_and_get_usage("P001")

    assert len(events) == 1
    assert summary.total_seconds == 1666
    assert summary.counselor_seconds == 1666
    assert calls == ["Sessions", "ChatLogs", "TimeRecoveryLedger"]

    calls.clear()
    events_again, summary_again = store.recover_and_get_usage("P001")
    assert not events_again
    assert summary_again.total_seconds == 1666
    assert calls == ["Sessions", "ChatLogs", "TimeRecoveryLedger"]
