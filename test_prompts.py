from src.cases import get_case
from src.prompts import dialogue_system_prompt, format_transcript


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
