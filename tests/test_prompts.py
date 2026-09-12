from src.cases import get_case
from src.prompts import dialogue_system_prompt, dialogue_turn_input, format_transcript


def test_practice_prompt_contains_role_and_stage_constraints():
    prompt = dialogue_system_prompt(
        mode="practice",
        stage="exploration",
        case=get_case("college_peer_01"),
    )
    assert "不得跳出個案角色" in prompt
    assert "漸進式揭露" in prompt
    assert "探索" in prompt


def test_transcript_keeps_recent_content_when_trimmed():
    messages = [
        {"speaker_role": "student_counselor", "content": "較早內容" * 20},
        {"speaker_role": "ai_client", "content": "最近內容"},
    ]
    transcript = format_transcript(messages, max_chars=30)
    assert "最近內容" in transcript
    assert "較早內容已省略" in transcript


def test_dialogue_turn_input_includes_safe_continuity_context():
    memory = {
        "topic_label": "課業或研究壓力",
        "summary_text": "上次談到新學期課業焦慮。",
        "unresolved_points_json": '["如何面對下一堂課"]',
        "recent_context_json": '[{"speaker_role":"student_client","content":"我擔心這學期會很難過"}]',
        "pin_hash": "must-not-leak",
        "session_id": "must-not-leak-either",
    }
    prompt = dialogue_turn_input(
        [{"speaker_role": "ai_counselor", "content": "今天想從哪裡接著談？"}],
        max_chars=1000,
        continuity_memory=memory,
    )
    assert "上次談到新學期課業焦慮" in prompt
    assert "如何面對下一堂課" in prompt
    assert "我擔心這學期會很難過" in prompt
    assert "must-not-leak" not in prompt
