"""以 Sessions 與 ChatLogs 互相勾稽的累積上機時間計算。

原則：
1. 只計入已正式結束的 session。
2. Sessions 的 started_at / ended_at / duration_seconds 彼此交叉核對，取較保守值。
3. ChatLogs 必須至少有一則學生實際輸入，且之後至少有一則 AI 回應。
4. 從第一則學生輸入起算，最後一則學生／AI 互動後保留最多 120 秒收尾緩衝；
   避免開著頁面但沒有互動的時間被無限制累加。
5. 最終每次計入秒數不會超過 Sessions 所記錄的實際 session 時長。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

SEMESTER_TARGET_MINUTES = 120
POST_INTERACTION_GRACE_SECONDS = 120
COUNTABLE_COMPLETION_STATUSES = {
    "completed",
    "completed_evaluation_error",
    "safety_ended",
}
STUDENT_ROLES = {"student_client", "student_counselor"}
AI_ROLES = {"ai_client", "ai_counselor"}


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _positive_seconds(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


@dataclass(frozen=True)
class AuditedSessionTime:
    session_id: str
    participant_id: str
    seconds: int
    counted: bool
    reason: str


@dataclass(frozen=True)
class AuditedUsageSummary:
    participant_id: str
    started_sessions: int = 0
    completed_sessions: int = 0
    counted_sessions: int = 0
    total_seconds: int = 0

    @property
    def total_minutes(self) -> float:
        return round(self.total_seconds / 60, 1)

    @property
    def remaining_minutes(self) -> float:
        return round(max(0.0, SEMESTER_TARGET_MINUTES - self.total_seconds / 60), 1)

    @property
    def progress_ratio(self) -> float:
        if SEMESTER_TARGET_MINUTES <= 0:
            return 1.0
        return min(1.0, max(0.0, self.total_seconds / 60 / SEMESTER_TARGET_MINUTES))


def audit_session_time(
    session: dict[str, Any],
    chat_logs: Iterable[dict[str, Any]],
) -> AuditedSessionTime:
    """計算單一 session 可列入學期累積的稽核後秒數。"""

    session_id = str(session.get("session_id", "") or "").strip()
    participant_id = str(session.get("participant_id", "") or "").strip()
    status = str(session.get("completion_status", "") or "").strip()

    if status not in COUNTABLE_COMPLETION_STATUSES:
        return AuditedSessionTime(session_id, participant_id, 0, False, "session_not_completed")

    started_at = _parse_datetime(session.get("started_at"))
    ended_at = _parse_datetime(session.get("ended_at"))
    if started_at is None or ended_at is None or ended_at <= started_at:
        return AuditedSessionTime(session_id, participant_id, 0, False, "invalid_session_time")

    wall_seconds = max(0.0, (ended_at - started_at).total_seconds())
    stored_seconds = _positive_seconds(session.get("duration_seconds"))
    session_seconds = min(wall_seconds, stored_seconds) if stored_seconds else wall_seconds
    if session_seconds <= 0:
        return AuditedSessionTime(session_id, participant_id, 0, False, "zero_session_duration")

    valid_logs: list[tuple[datetime, str]] = []
    for row in chat_logs:
        if str(row.get("session_id", "") or "").strip() != session_id:
            continue
        timestamp = _parse_datetime(row.get("timestamp"))
        if timestamp is None:
            continue
        # 僅接受位於 session 時間窗內的對話事件；允許 5 秒時鐘／寫入誤差。
        if timestamp < started_at - timedelta(seconds=5):
            continue
        if timestamp > ended_at + timedelta(seconds=5):
            continue
        role = str(row.get("speaker_role", "") or "").strip()
        valid_logs.append((timestamp, role))

    valid_logs.sort(key=lambda item: item[0])
    student_times = [timestamp for timestamp, role in valid_logs if role in STUDENT_ROLES]
    if not student_times:
        return AuditedSessionTime(session_id, participant_id, 0, False, "no_student_turn")

    first_student_at = student_times[0]
    ai_replies = [
        timestamp
        for timestamp, role in valid_logs
        if role in AI_ROLES and timestamp >= first_student_at
    ]
    if not ai_replies:
        return AuditedSessionTime(session_id, participant_id, 0, False, "no_ai_reply")

    interaction_times = [
        timestamp
        for timestamp, role in valid_logs
        if role in STUDENT_ROLES | AI_ROLES and timestamp >= first_student_at
    ]
    last_interaction_at = max(interaction_times)
    audited_end = min(
        ended_at,
        last_interaction_at + timedelta(seconds=POST_INTERACTION_GRACE_SECONDS),
    )
    chat_supported_seconds = max(0.0, (audited_end - first_student_at).total_seconds())
    audited_seconds = int(max(0.0, min(session_seconds, chat_supported_seconds)))

    if audited_seconds <= 0:
        return AuditedSessionTime(session_id, participant_id, 0, False, "no_supported_duration")
    return AuditedSessionTime(session_id, participant_id, audited_seconds, True, "counted")


def audited_usage_summary(
    participant_id: str,
    sessions: Iterable[dict[str, Any]],
    chat_logs: Iterable[dict[str, Any]],
) -> AuditedUsageSummary:
    """彙整一位學生的學期累積上機時間。"""

    participant_id = str(participant_id or "").strip()
    session_rows = [
        dict(row)
        for row in sessions
        if str(row.get("participant_id", "") or "").strip() == participant_id
    ]
    chat_rows = [dict(row) for row in chat_logs]

    completed_sessions = sum(
        1
        for row in session_rows
        if str(row.get("completion_status", "") or "").strip()
        in COUNTABLE_COMPLETION_STATUSES
    )
    audited = [audit_session_time(row, chat_rows) for row in session_rows]
    counted = [item for item in audited if item.counted]

    return AuditedUsageSummary(
        participant_id=participant_id,
        started_sessions=len(session_rows),
        completed_sessions=completed_sessions,
        counted_sessions=len(counted),
        total_seconds=sum(item.seconds for item in counted),
    )
