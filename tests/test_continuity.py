from src.continuity import build_memory_record, recent_context


def test_recent_context_excludes_system_messages():
    messages = [
        {"ui_role": "assistant", "speaker_role": "ai_counselor", "content": "你最近還好嗎？"},
        {"ui_role": "user", "speaker_role": "student_client", "content": "最近課業壓力很大"},
        {"ui_role": "assistant", "speaker_role": "system", "content": "技術錯誤"},
    ]
    context = recent_context(messages)
    assert len(context) == 2
    assert all(item["speaker_role"] != "system" for item in context)


def test_memory_record_keeps_legacy_pin_column_empty():
    session = {
        "participant_id": "SABC123456789",
        "conversation_id": "conversation-1",
        "session_id": "session-2",
        "parent_session_id": "session-1",
        "conversation_session_number": 2,
        "experience_topic_label": "課業或研究壓力",
    }
    messages = [
        {"ui_role": "user", "speaker_role": "student_client", "content": "我還是很擔心明天的課"},
    ]
    record = build_memory_record(
        session=session,
        messages=messages,
        updated_at="2026-09-12T12:00:00+08:00",
        continuity={
            "topic_label": "課業或研究壓力",
            "summary_text": "學生談到新學期課業焦慮。",
            "unresolved_points": ["如何面對下一堂課"],
            "next_opening": "上次我們談到新學期的焦慮，這幾天有什麼變化嗎？",
        },
        status="ready",
    )
    assert record["parent_session_id"] == "session-1"
    assert record["session_number"] == 2
    assert record["pin_hash"] == ""
