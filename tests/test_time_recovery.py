"""嚴格驗證意外中斷恢復：有時間戳記證據、不得重複計入、可追蹤撤銷。"""
from datetime import datetime, timezone

from src.time_recovery import (
    credited_recoveries,
    latest_recovery_events,
    recovery_candidate,
    recovery_event_record,
    recovery_id_for_session,
)
from src.usage_time import audited_usage_summary


SID = "sample-recoverable-session"


def _session():
    return {
        "session_id": SID,
        "participant_id": "P001",
        "mode": "practice",
        "started_at": "2026-10-18T14:23:58+08:00",
        "ended_at": "",
        "duration_seconds": "",
        "completion_status": "in_progress",
    }


def _logs():
    # 這是去識別的合成測試證據；時間跨度與本次 28 分鐘事故相同。
    stamps = [
        ("student_counselor", "2026-10-18T14:25:46+08:00"),
        ("ai_client", "2026-10-18T14:25:48+08:00"),
        ("student_counselor", "2026-10-18T14:40:41+08:00"),
        ("ai_client", "2026-10-18T14:40:43+08:00"),
        ("student_counselor", "2026-10-18T14:51:28+08:00"),
        ("ai_client", "2026-10-18T14:51:32+08:00"),
    ]
    return [
        {
            "session_id": SID,
            "turn_id": f"T{i}",
            "timestamp": timestamp,
            "speaker_role": role,
        }
        for i, (role, timestamp) in enumerate(stamps)
    ]


def test_recover_28_minute_interrupted_practice():
    # 測試中含 14 分 53 秒與 10 分 45 秒的間隔，均在 15 分鐘門檻內。
    candidate = recovery_candidate(
        _session(), _logs(), now=datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)
    )
    assert candidate is not None
    assert candidate.credited_seconds == 1666
    assert candidate.minutes == 27.8
    assert candidate.mode == "practice"
    assert candidate.student_turns == 3
    assert candidate.ai_turns == 3

    event = recovery_event_record(
        candidate,
        status="auto_verified",
        actor="system:otp_verified_student",
        created_at="2026-10-18T08:00:00+00:00",
    )
    summary = audited_usage_summary("P001", [_session()], _logs(), [event])
    assert summary.total_seconds == 1666
    assert summary.counselor_seconds == 1666
    assert summary.recovered_seconds == 1666
    assert summary.counted_sessions == 1


def test_recovery_never_double_counts_session_or_ledger_duplicates():
    candidate = recovery_candidate(
        _session(), _logs(), now=datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)
    )
    event = recovery_event_record(
        candidate, status="auto_verified", actor="system", created_at="2026-10-18T08:00:00+00:00"
    )
    first = audited_usage_summary("P001", [_session()], _logs(), [event, event])
    assert first.total_seconds == 1666

    completed = {
        **_session(),
        "completion_status": "completed",
        "ended_at": "2026-10-18T14:52:00+08:00",
        "duration_seconds": 1682,
    }
    normal = audited_usage_summary("P001", [completed], _logs())
    combined = audited_usage_summary("P001", [completed], _logs(), [event])
    assert combined.total_seconds == normal.total_seconds
    assert combined.recovered_seconds == 0


def test_teacher_can_revoke_without_erasing_history():
    candidate = recovery_candidate(
        _session(), _logs(), now=datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)
    )
    approved = recovery_event_record(
        candidate, status="auto_verified", actor="system", created_at="2026-10-18T08:00:00+00:00"
    )
    revoked = recovery_event_record(
        candidate, status="teacher_revoked", actor="teacher:test", 
        created_at="2026-10-18T08:01:00+00:00", note="逐字核實後不予採計"
    )
    events = [approved, revoked]
    assert len(events) == 2
    assert latest_recovery_events(events)[SID]["recovery_status"] == "teacher_revoked"
    assert credited_recoveries(events) == {}
    summary = audited_usage_summary("P001", [_session()], _logs(), events)
    assert summary.total_seconds == 0


def test_recovery_requires_stale_and_two_real_exchanges():
    session, logs = _session(), _logs()
    assert recovery_candidate(
        session, logs, now=datetime(2026, 10, 18, 6, 55, tzinfo=timezone.utc)
    ) is None
    assert recovery_candidate(
        session, logs[:2], now=datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)
    ) is None


def test_invalid_gap_remains_for_teacher_manual_review():
    logs = _logs()
    logs[2]["timestamp"] = "2026-10-18T15:20:00+08:00"
    assert recovery_candidate(
        _session(), logs, now=datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
    ) is None


def test_recovery_id_deterministic():
    assert recovery_id_for_session(SID) == recovery_id_for_session(SID)
    assert recovery_id_for_session(SID) != recovery_id_for_session("another")


def test_two_minute_threshold_excludes_grace_period():
    logs = [
        {
            "session_id": SID,
            "turn_id": str(i),
            "timestamp": stamp,
            "speaker_role": role,
        }
        for i, (role, stamp) in enumerate([
            ("student_counselor", "2026-10-18T14:25:46+08:00"),
            ("ai_client", "2026-10-18T14:25:48+08:00"),
            ("student_counselor", "2026-10-18T14:26:01+08:00"),
            ("ai_client", "2026-10-18T14:26:03+08:00"),
        ])
    ]
    assert recovery_candidate(
        _session(), logs, now=datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)
    ) is None
