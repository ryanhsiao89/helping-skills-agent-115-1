"""Google Sheets 持久化層。

使用一份試算表中的 Sessions、ChatLogs、SkillEvents、Assessments 四個工作表。
所有寫入採 RAW，避免學生輸入被 Google Sheets 解讀為公式。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from .constants import SHEET_HEADERS

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)


class SheetsStoreError(RuntimeError):
    pass


def _cell_value(value: Any) -> str | int | float | bool:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _column_letter(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


@dataclass(frozen=True)
class UsageSummary:
    started: int = 0
    completed: int = 0


class NullStore:
    """僅供 UI 本機預覽；研究部署時應將 REQUIRE_SHEETS 設為 true。"""

    enabled = False

    def ensure_schema(self) -> None:
        return None

    def append_record(self, sheet_name: str, record: dict[str, Any]) -> None:
        return None

    def update_session(self, session_id: str, record: dict[str, Any]) -> None:
        return None

    def usage_summary(self, participant_id: str) -> UsageSummary:
        return UsageSummary()

    def read_all(self, sheet_name: str) -> list[dict[str, Any]]:
        return []


class SheetsStore:
    enabled = True

    def __init__(self, service_account_info: dict[str, Any], spreadsheet_id: str):
        try:
            credentials = Credentials.from_service_account_info(
                service_account_info,
                scopes=SCOPES,
            )
            client = gspread.authorize(credentials)
            self.spreadsheet = client.open_by_key(spreadsheet_id)
        except Exception as exc:
            raise SheetsStoreError(
                "無法連線 Google Sheets；請檢查試算表 ID、服務帳戶 JSON，以及試算表是否已分享給服務帳戶。"
            ) from exc

    def ensure_schema(self) -> None:
        for name, headers in SHEET_HEADERS.items():
            try:
                worksheet = self.spreadsheet.worksheet(name)
            except gspread.WorksheetNotFound:
                existing = self.spreadsheet.worksheets()
                if name == "Sessions" and len(existing) == 1 and not existing[0].get_all_values():
                    # 新試算表通常自帶一張空白工作表，直接沿用可避免留下多餘分頁。
                    worksheet = existing[0]
                    worksheet.update_title(name)
                else:
                    worksheet = self.spreadsheet.add_worksheet(
                        title=name,
                        rows=1000,
                        cols=max(20, len(headers)),
                    )

            current_headers = worksheet.row_values(1)
            if not current_headers:
                worksheet.append_row(headers, value_input_option="RAW")
                worksheet.freeze(rows=1)
            elif current_headers != headers:
                raise SheetsStoreError(
                    f"工作表 {name} 的第一列欄位與程式版本不一致。請先備份資料，再依 README 的欄位處理說明更新。"
                )

    def _worksheet(self, sheet_name: str):
        if sheet_name not in SHEET_HEADERS:
            raise KeyError(f"未知工作表：{sheet_name}")
        return self.spreadsheet.worksheet(sheet_name)

    def append_record(self, sheet_name: str, record: dict[str, Any]) -> None:
        headers = SHEET_HEADERS[sheet_name]
        row = [_cell_value(record.get(header, "")) for header in headers]
        try:
            self._worksheet(sheet_name).append_row(row, value_input_option="RAW")
        except Exception as exc:
            raise SheetsStoreError(f"寫入 {sheet_name} 失敗。") from exc

    def update_session(self, session_id: str, record: dict[str, Any]) -> None:
        headers = SHEET_HEADERS["Sessions"]
        worksheet = self._worksheet("Sessions")
        try:
            identifiers = worksheet.col_values(1)
            row_number = identifiers.index(session_id) + 1
        except ValueError as exc:
            raise SheetsStoreError(f"找不到 session_id：{session_id}") from exc

        values = [_cell_value(record.get(header, "")) for header in headers]
        end_column = _column_letter(len(headers))
        try:
            worksheet.update(
                values=[values],
                range_name=f"A{row_number}:{end_column}{row_number}",
                value_input_option="RAW",
            )
        except Exception as exc:
            raise SheetsStoreError("更新 Session 結束資訊失敗。") from exc

    def usage_summary(self, participant_id: str) -> UsageSummary:
        records = self.read_all("Sessions")
        participant_rows = [
            row for row in records if str(row.get("participant_id", "")).strip() == participant_id
        ]
        completed_statuses = {"completed", "completed_evaluation_error", "safety_ended"}
        completed = sum(
            1 for row in participant_rows if row.get("completion_status") in completed_statuses
        )
        return UsageSummary(started=len(participant_rows), completed=completed)

    def read_all(self, sheet_name: str) -> list[dict[str, Any]]:
        try:
            return self._worksheet(sheet_name).get_all_records(
                expected_headers=SHEET_HEADERS[sheet_name]
            )
        except TypeError:
            # 舊版 gspread 沒有 expected_headers 參數時仍可讀取。
            return self._worksheet(sheet_name).get_all_records()
        except Exception as exc:
            raise SheetsStoreError(f"讀取 {sheet_name} 失敗。") from exc
