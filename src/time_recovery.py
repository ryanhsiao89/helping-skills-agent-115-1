"""可追溯的 Streamlit 意外中斷分鐘復原。

不覆寫 Sessions 原始狀態或捏造 ended_at；只有完整的逐輪證據、適當間隔，
且超過最後一輪活動 15 分鐘的 in_progress Session 才能自動建立補認列。
教師後續可用追加事件撤銷／重新核定，不刪除原始稽核資料。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .usage_time import (
    AI_ROLES,
    POST_INTERACTION_GRACE_SECONDS,
    STUDENT_ROLES,
)

RECOVERY_STALE_SECONDS = 15 * 60
MAX_INTERACTION_GAP_SECONDS = 15 * 60
MIN_RECOVERABLE_SECONDS = 120
RECOVERY_POLICY_VERSION = "time-recovery-v1"
CREDITED_STATUSES = {"auto_verified", "teacher_approved"}
REVOKED_STATUSES = {"teacher_revoked"}


def _dt(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value or "").strip())
        return dt if dt.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RecoveryCandidate:
    session_id: str
    participant_id: str
    mode: str
    first_student_at: str
    last_interaction_at: str
    credited_seconds: int
    student_turns: int
    ai_turns: int
    source_turn_count: int
    source_digest: str

    @property
    def minutes(self) -> float:
        return round(self.credited_seconds / 60, 1)


def recovery_id_for_session(session_id: str) -> str:
    digest = hashlib.sha256(
        f"{RECOVERY_POLICY_VERSION}|{session_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"TR-{digest}"


def recovery_candidate(
    session: dict[str, Any],
    chat_rows: Iterable[dict[str, Any]],
    *,
    now: datetime,
) -> RecoveryCandidate | None:
    """嚴格依原始 Sessions × ChatLogs 判斷，未達門檻的情況不自動認列。"""
    if str(session.get("completion_status", "")).strip() != "in_progress":
        return None
    session_id = str(session.get("session_id", "") or "").strip()
    participant_id = str(session.get("participant_id", "") or "").strip()
    mode = str(session.get("mode", "") or "").strip()
    start = _dt(session.get("started_at"))
    if not session_id or not participant_id or mode not in {"practice", "experience"} or not start:
        return None

    valid: list[tuple[datetime, str, str]] = []
    for row in chat_rows:
        if str(row.get("session_id", "") or "").strip() != session_id:
            continue
        role = str(row.get("speaker_role", "") or "").strip()
        if role not in STUDENT_ROLES | AI_ROLES:
            continue
        timestamp = _dt(row.get("timestamp"))
        if not timestamp or _as_utc(timestamp) < _as_utc(start) - timedelta(seconds=5):
            continue
        if _as_utc(timestamp) > _as_utc(now):
            continue
        event_id = str(row.get("turn_id", "") or "").strip()
        valid.append((timestamp, role, event_id))

    valid.sort(key=lambda item: _as_utc(item[0]))
    student = [t for t, r, _ in valid if r in STUDENT_ROLES]
    if len(student) < 2:
        return None
    first_student = student[0]
    active = [(t, r, event_id) for t, r, event_id in valid
              if _as_utc(t) >= _as_utc(first_student)]
    ai = [t for t, r, _ in active if r in AI_ROLES
          and _as_utc(t) >= _as_utc(first_student)]
    if len(ai) < 2:
        return None

    last = active[-1][0]
    if (_as_utc(now) - _as_utc(last)).total_seconds() < RECOVERY_STALE_SECONDS:
        return None

    # 過長的互動空窗不應在缺乏證據下自動整段算入；交由教師人工核實。
    timestamps = [_as_utc(t) for t, _, _ in active]
    if any((b - a).total_seconds() > MAX_INTERACTION_GAP_SECONDS
           for a, b in zip(timestamps, timestamps[1:])):
        return None

    active_span_seconds = int(
        (_as_utc(last) - _as_utc(first_student)).total_seconds()
    )
    # 最低兩分鐘是實際互動跨度；不可僅靠 120 秒收尾緩衝過門檻。
    if active_span_seconds < MIN_RECOVERABLE_SECONDS:
        return None
    seconds = active_span_seconds + POST_INTERACTION_GRACE_SECONDS

    source = [
        [event_id, timestamp.isoformat(), role]
        for timestamp, role, event_id in active
    ]
    digest = hashlib.sha256(
        json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RecoveryCandidate(
        session_id=session_id,
        participant_id=participant_id,
        mode=mode,
        first_student_at=first_student.isoformat(),
        last_interaction_at=last.isoformat(),
        credited_seconds=seconds,
        student_turns=len(student),
        ai_turns=len(ai),
        source_turn_count=len(active),
        source_digest=digest,
    )


def latest_recovery_events(
    rows: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """以 append-only 順序決定最後有效裁定；撤銷事件會保留歷史。"""
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("session_id", "") or "").strip()
        if sid:
            latest[sid] = dict(row)
    return latest


def credited_recoveries(
    rows: Iterable[dict[str, Any]],
    *,
    participant_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for sid, record in latest_recovery_events(rows).items():
        status = str(record.get("recovery_status", "") or "").strip()
        if status not in CREDITED_STATUSES:
            continue
        if participant_id is not None and str(record.get("participant_id", "")).strip() != participant_id:
            continue
        try:
            seconds = int(float(record.get("credited_seconds", 0) or 0))
        except (TypeError, ValueError):
            continue
        if seconds <= 0:
            continue
        result[sid] = record
    return result


def recovery_event_record(
    candidate: RecoveryCandidate,
    *,
    status: str,
    actor: str,
    created_at: str,
    note: str = "",
) -> dict[str, Any]:
    if status not in CREDITED_STATUSES | REVOKED_STATUSES:
        raise ValueError("invalid recovery decision")
    return {
        "event_id": hashlib.sha256(
            f"{candidate.session_id}|{status}|{actor}|{created_at}".encode("utf-8")
        ).hexdigest()[:32],
        "recovery_id": recovery_id_for_session(candidate.session_id),
        "session_id": candidate.session_id,
        "participant_id": candidate.participant_id,
        "mode": candidate.mode,
        "recovery_status": status,
        "credited_seconds": candidate.credited_seconds if status not in REVOKED_STATUSES else 0,
        "first_student_at": candidate.first_student_at,
        "last_interaction_at": candidate.last_interaction_at,
        "student_turns": candidate.student_turns,
        "ai_turns": candidate.ai_turns,
        "source_turn_count": candidate.source_turn_count,
        "source_digest": candidate.source_digest,
        "policy_version": RECOVERY_POLICY_VERSION,
        "grace_seconds": POST_INTERACTION_GRACE_SECONDS,
        "actor": actor,
        "created_at": created_at,
        "note": note,
    }
