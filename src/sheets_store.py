"""Google Sheets 持久化層。

使用一份試算表中的 Sessions、ChatLogs、SkillEvents、Assessments、ContinuityMemory、StudentRoster 工作表。
所有寫入採 RAW，避免學生輸入被 Google Sheets 解讀為公式。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from .constants import SHEET_HEADERS
from .usage_time import AuditedUsageSummary, audited_usage_summary
from .time_recovery import (
    latest_recovery_events,
    recovery_candidate,
    recovery_event_record,
)

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


def _google_api_detail(exc: Exception) -> str:
    """擷取 Google API 可公開的錯誤摘要，不顯示憑證、token 或完整回應內容。"""
    response = getattr(exc, "response", None)
    parts: list[str] = []

    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None

        if isinstance(payload, dict):
            error = payload.get("error", payload)
            if isinstance(error, dict):
                status = str(error.get("status", "") or "").strip()
                message = str(error.get("message", "") or "").strip()
                reasons: list[str] = []
                for item in error.get("errors", []) or []:
                    if isinstance(item, dict):
                        reason = str(item.get("reason", "") or "").strip()
                        if reason and reason not in reasons:
                            reasons.append(reason)
                if status:
                    parts.append(f"status={status}")
                if reasons:
                    parts.append("reason=" + ",".join(reasons[:3]))
                if message:
                    parts.append("message=" + message)

    if not parts:
        raw = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
        if raw:
            parts.append(raw)

    detail = " | ".join(parts)
    # 防禦性遮蔽常見機密格式；Google Sheets 錯誤通常不會包含這些資訊。
    import re
    detail = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[API_KEY_REDACTED]", detail)
    detail = re.sub(
        r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[REDACTED]",
        detail,
    )
    detail = " ".join(detail.split())
    if len(detail) > 500:
        detail = detail[:500] + "…"
    return detail


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
        detail = _google_api_detail(exc)
        suffix = f" Google 回傳：{detail}" if detail else ""
        return (
            f"{action}：Google Sheets 權限驗證失敗（{status}）。"
            "已確認一般共用權限後，請將下列 Google 原始診斷提供給教師判讀。"
            f"{suffix}"
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

    def recover_stale_sessions(
        self, participant_id: str, *, actor: str = "system:otp_verified_student"
    ) -> list[dict[str, Any]]:
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
        """正常與有稽核紀錄的中斷復原分鐘均併入學期 120／60 進度。"""
        return audited_usage_summary(
            participant_id,
            self.read_all("Sessions"),
            self.read_all("ChatLogs"),
            self.read_all("TimeRecoveryLedger"),
        )

    def recover_stale_sessions(
        self, participant_id: str, *, actor: str = "system:otp_verified_student"
    ) -> list[dict[str, Any]]:
        """學生重新登入時，復原有逐輪證據、已閒置的未結束練習。

        每個 Session 最多自動建一筆正式稽核事件；若教師已撤銷，
        不會再次自動補回。任一寫入失敗則顯示錯誤，不默默聲稱補認列。
        """
        participant_id = str(participant_id or "").strip()
        if not participant_id:
            return []

        sessions = [
            row for row in self.read_all("Sessions")
            if str(row.get("participant_id", "") or "").strip() == participant_id
            and str(row.get("completion_status", "") or "").strip() == "in_progress"
        ]
        if not sessions:
            return []

        chat_rows = self.read_all("ChatLogs")
        latest = latest_recovery_events(self.read_all("TimeRecoveryLedger"))
        now = datetime.now(timezone.utc)
        added = []
        for session in sessions:
            candidate = recovery_candidate(session, chat_rows, now=now)
            if candidate is None or candidate.session_id in latest:
                continue
            event = recovery_event_record(
                candidate,
                status="auto_verified",
                actor=actor,
                created_at=now.isoformat(timespec="seconds"),
                note="Streamlit 意外中斷；已依 Sessions × ChatLogs 審核互動證據與 120 秒緩衝。",
            )
            self.append_record("TimeRecoveryLedger", event)
            latest[candidate.session_id] = event
            added.append(event)
        return added

    def append_recovery_decision(
        self, session_id: str, *, actor: str, status: str, note: str
    ) -> dict[str, Any]:
        """教師追加裁定；不刪除舊事件或修改 Sessions。"""
        if not actor.strip() or not note.strip():
            raise SheetsStoreError("教師裁定需要帳號與原因，才可留下稽核軌跡。")
        records = self.read_all("Sessions")
        session = next(
            (row for row in records if str(row.get("session_id", "")) == session_id),
            None,
        )
        if session is None:
            raise SheetsStoreError("找不到指定的 Session。")
        now = datetime.now(timezone.utc)
        candidate = recovery_candidate(session, self.read_all("ChatLogs"), now=now)
        if candidate is None:
            raise SheetsStoreError("該 Session 不符合復原條件，不可直接修改時間。")
        if session_id not in latest_recovery_events(self.read_all("TimeRecoveryLedger")):
            raise SheetsStoreError("這筆 Session 尚未建立原始自動復原紀錄。")
        event = recovery_event_record(
            candidate,
            status=status,
            actor=f"teacher:{actor.strip()}",
            created_at=now.isoformat(timespec="microseconds"),
            note=note.strip(),
        )
        self.append_record("TimeRecoveryLedger", event)
        return event

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
