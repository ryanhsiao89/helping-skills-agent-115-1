"""Google Sheets 持久化層。

使用一份試算表中的 Sessions、ChatLogs、SkillEvents、Assessments、ContinuityMemory、StudentRoster 工作表。
所有寫入採 RAW，避免學生輸入被 Google Sheets 解讀為公式。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from .constants import SHEET_HEADERS
from .usage_time import AuditedUsageSummary, audited_usage_summary

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)

SHEETS_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
SHEETS_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0, 8.0)


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if value is None:
        value = getattr(exc, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _run_with_retry(operation):
    """對 Google Sheets 429/5xx 做短暫指數退避，降低多人同時使用時的瞬斷。"""
    last_error: Exception | None = None
    attempts = len(SHEETS_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            status = _status_code(exc)
            if status not in SHEETS_RETRYABLE_STATUS_CODES or attempt >= attempts - 1:
                raise
            time.sleep(SHEETS_RETRY_DELAYS_SECONDS[attempt])
    if last_error is not None:
        raise last_error
    raise RuntimeError("Google Sheets operation failed without an exception")


def _friendly_sheet_error(action: str, exc: Exception) -> str:
    status = _status_code(exc)
    if status == 429:
        return (
            f"{action}：Google Sheets 暫時達到流量上限（429）。"
            "系統已自動重試仍未成功，請稍候約 30–60 秒再試。"
        )
    if status in {500, 502, 503, 504}:
        return (
            f"{action}：Google Sheets 服務暫時不穩定（{status}）。"
            "系統已自動重試仍未成功，請稍後再試。"
        )
    if status in {401, 403}:
        return (
            f"{action}：Google Sheets 權限驗證失敗（{status}）。"
            "請教師確認 Streamlit Secrets 的服務帳戶設定，以及試算表是否仍分享給該服務帳戶。"
        )
    return action


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

    def audited_usage_summary(self, participant_id: str) -> AuditedUsageSummary:
        return AuditedUsageSummary(participant_id=str(participant_id or "").strip())

    def read_all(self, sheet_name: str) -> list[dict[str, Any]]:
        return []

    def latest_continuity(self, participant_id: str) -> dict[str, Any] | None:
        return None

    def student_by_email(self, school_email: str) -> dict[str, Any] | None:
        return None

    def ensure_student(
        self,
        *,
        school_email: str,
        participant_id: str,
        verified_at: str,
    ) -> dict[str, Any]:
        return {
            "participant_id": participant_id,
            "school_email": school_email,
            "first_verified_at": verified_at,
        }


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
        return _run_with_retry(lambda: self.spreadsheet.worksheet(sheet_name))

    def append_record(self, sheet_name: str, record: dict[str, Any]) -> None:
        headers = SHEET_HEADERS[sheet_name]
        row = [_cell_value(record.get(header, "")) for header in headers]
        try:
            worksheet = self._worksheet(sheet_name)
            _run_with_retry(
                lambda: worksheet.append_row(row, value_input_option="RAW")
            )
        except Exception as exc:
            raise SheetsStoreError(
                _friendly_sheet_error(f"寫入 {sheet_name} 失敗", exc)
            ) from exc

    def update_session(self, session_id: str, record: dict[str, Any]) -> None:
        headers = SHEET_HEADERS["Sessions"]
        worksheet = self._worksheet("Sessions")
        try:
            identifiers = _run_with_retry(lambda: worksheet.col_values(1))
            row_number = identifiers.index(session_id) + 1
        except ValueError as exc:
            raise SheetsStoreError(f"找不到 session_id：{session_id}") from exc
        except Exception as exc:
            raise SheetsStoreError(
                _friendly_sheet_error("讀取 Sessions 失敗", exc)
            ) from exc

        values = [_cell_value(record.get(header, "")) for header in headers]
        end_column = _column_letter(len(headers))
        try:
            _run_with_retry(
                lambda: worksheet.update(
                    values=[values],
                    range_name=f"A{row_number}:{end_column}{row_number}",
                    value_input_option="RAW",
                )
            )
        except Exception as exc:
            raise SheetsStoreError(
                _friendly_sheet_error("更新 Session 結束資訊失敗", exc)
            ) from exc

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

    def audited_usage_summary(self, participant_id: str) -> AuditedUsageSummary:
        """以 Sessions 與 ChatLogs 交叉核對後計算學期累積上機時間。"""
        return audited_usage_summary(
            participant_id,
            self.read_all("Sessions"),
            self.read_all("ChatLogs"),
        )

    def latest_continuity(self, participant_id: str) -> dict[str, Any] | None:
        """取得同一已驗證學生最新一筆已保存的跨次續談記憶。"""
        participant_id = participant_id.strip()
        if not participant_id:
            return None
        records = self.read_all("ContinuityMemory")
        rows = [
            row
            for row in records
            if str(row.get("participant_id", "")).strip() == participant_id
            and str(row.get("memory_status", "")).strip() in {"ready", "fallback"}
        ]
        if not rows:
            return None

        def sort_key(row: dict[str, Any]) -> tuple[str, int]:
            try:
                number = int(row.get("session_number", 0) or 0)
            except (TypeError, ValueError):
                number = 0
            return (str(row.get("updated_at", "")), number)

        return dict(max(rows, key=sort_key))

    def student_by_email(self, school_email: str) -> dict[str, Any] | None:
        """以已驗證學校 Email 找到穩定的 participant_id。"""
        target = str(school_email or "").strip().lower()
        if not target:
            return None
        rows = self.read_all("StudentRoster")
        for row in rows:
            if str(row.get("school_email", "")).strip().lower() == target:
                return dict(row)
        return None

    def ensure_student(
        self,
        *,
        school_email: str,
        participant_id: str,
        verified_at: str,
    ) -> dict[str, Any]:
        """第一次驗證時建立 StudentRoster；之後沿用既有 participant_id。"""
        existing = self.student_by_email(school_email)
        if existing:
            return existing
        record = {
            "participant_id": participant_id,
            "school_email": str(school_email).strip().lower(),
            "first_verified_at": verified_at,
        }
        self.append_record("StudentRoster", record)
        return record

    def read_all(self, sheet_name: str) -> list[dict[str, Any]]:
        worksheet = self._worksheet(sheet_name)
        try:
            return _run_with_retry(
                lambda: worksheet.get_all_records(
                    expected_headers=SHEET_HEADERS[sheet_name]
                )
            )
        except TypeError:
            # 舊版 gspread 沒有 expected_headers 參數時仍可讀取。
            try:
                return _run_with_retry(lambda: worksheet.get_all_records())
            except Exception as exc:
                raise SheetsStoreError(
                    _friendly_sheet_error(f"讀取 {sheet_name} 失敗", exc)
                ) from exc
        except Exception as exc:
            raise SheetsStoreError(
                _friendly_sheet_error(f"讀取 {sheet_name} 失敗", exc)
            ) from exc
