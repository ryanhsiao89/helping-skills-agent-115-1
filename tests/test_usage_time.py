from src.usage_time import audit_session_time, audited_usage_summary


def _session(session_id: str, mode: str, start: str, end: str, seconds: int = 3600):
    return {
        "session_id": session_id,
        "participant_id": "P001",
        "mode": mode,
        "started_at": start,
        "ended_at": end,
        "duration_seconds": seconds,
        "completion_status": "completed",
    }


def _chat(session_id: str, role: str, timestamp: str):
    return {
        "session_id": session_id,
        "speaker_role": role,
        "timestamp": timestamp,
    }


def test_audited_summary_requires_120_total_and_60_counselor_minutes():
    sessions = [
        _session(
            "S1",
            "practice",
            "2026-09-15T10:00:00+08:00",
            "2026-09-15T11:00:00+08:00",
        ),
        _session(
            "S2",
            "experience",
            "2026-09-15T13:00:00+08:00",
            "2026-09-15T14:00:00+08:00",
        ),
    ]
    chats = [
        _chat("S1", "student_counselor", "2026-09-15T10:00:00+08:00"),
        _chat("S1", "ai_client", "2026-09-15T10:58:00+08:00"),
        _chat("S2", "student_client", "2026-09-15T13:00:00+08:00"),
        _chat("S2", "ai_counselor", "2026-09-15T13:58:00+08:00"),
    ]

    summary = audited_usage_summary("P001", sessions, chats)

    assert summary.total_minutes == 120.0
    assert summary.counselor_minutes == 60.0
    assert summary.experience_minutes == 60.0
    assert summary.remaining_minutes == 0.0
    assert summary.remaining_counselor_minutes == 0.0
    assert summary.semester_requirement_met is True


def test_practice_minutes_can_exceed_60_and_still_count_toward_total():
    sessions = [
        _session(
            "S1",
            "practice",
            "2026-09-15T10:00:00+08:00",
            "2026-09-15T11:00:00+08:00",
        ),
        _session(
            "S2",
            "practice",
            "2026-09-15T13:00:00+08:00",
            "2026-09-15T14:00:00+08:00",
        ),
    ]
    chats = [
        _chat("S1", "student_counselor", "2026-09-15T10:00:00+08:00"),
        _chat("S1", "ai_client", "2026-09-15T10:58:00+08:00"),
        _chat("S2", "student_counselor", "2026-09-15T13:00:00+08:00"),
        _chat("S2", "ai_client", "2026-09-15T13:58:00+08:00"),
    ]

    summary = audited_usage_summary("P001", sessions, chats)

    assert summary.total_minutes == 120.0
    assert summary.counselor_minutes == 120.0
    assert summary.semester_requirement_met is True


def test_session_without_student_turn_is_not_counted():
    session = _session(
        "S1",
        "practice",
        "2026-09-15T10:00:00+08:00",
        "2026-09-15T10:10:00+08:00",
        seconds=600,
    )
    result = audit_session_time(
        session,
        [_chat("S1", "ai_client", "2026-09-15T10:00:00+08:00")],
    )

    assert result.counted is False
    assert result.seconds == 0
    assert result.reason == "no_student_turn"


def test_unfinished_session_is_not_counted_even_with_chat_logs():
    session = _session(
        "S1",
        "practice",
        "2026-09-15T10:00:00+08:00",
        "2026-09-15T10:10:00+08:00",
        seconds=600,
    )
    session["completion_status"] = "in_progress"
    result = audit_session_time(
        session,
        [
            _chat("S1", "student_counselor", "2026-09-15T10:01:00+08:00"),
            _chat("S1", "ai_client", "2026-09-15T10:02:00+08:00"),
        ],
    )

    assert result.counted is False
    assert result.reason == "session_not_completed"
