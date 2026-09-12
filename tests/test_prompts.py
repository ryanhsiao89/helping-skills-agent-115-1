from src.cases import get_case
from src.prompts import (
    dialogue_system_prompt,
    dialogue_turn_input,
    evaluator_system_prompt,
    format_transcript,
)


def test_practice_prompt_contains_role_and_stage_constraints():
    prompt = dialogue_system_prompt(
        mode="practice",
        stage="exploration",
        case=get_case("college_peer_01"),
    )
    assert "不得跳出個案角色" in prompt
    assert "漸進式揭露" in prompt
    assert "探索" in prompt


def test_practice_prompt_treats_parentheses_as_nonverbal_behavior():
    prompt = dialogue_system_prompt(
        mode="practice",
        stage="exploration",
        case=get_case("college_peer_01"),
    )
    assert "非語言" in prompt
    assert "安靜等待他人發言" in prompt
    assert "不得把括號內容誤認為助人者說出口的話" in prompt


def test_experience_prompt_treats_parentheses_as_nonverbal_behavior():
    prompt = dialogue_system_prompt(
        mode="experience",
        stage="full_demo",
        experience_topic="人際互動",
    )
    assert "非語言" in prompt
    assert "不可過度解讀" in prompt


def test_transcript_keeps_recent_content_when_trimmed():
    messages = [
        {"speaker_role": "student_counselor", "content": "較早內容" * 20},
        {"speaker_role": "ai_client", "content": "最近內容"},
    ]
    transcript = format_transcript(messages, max_chars=30)
    assert "最近內容" in transcript
    assert "較早內容已省略" in transcript


def test_dialogue_turn_input_repeats_nonverbal_rule():
    prompt = dialogue_turn_input(
        [{"speaker_role": "student_counselor", "content": "(安靜等待他人發言)"}],
        max_chars=1000,
    )
    assert "非語言行為" in prompt
    assert "不是角色實際說出口的話" in prompt
    assert "(安靜等待他人發言)" in prompt


def test_evaluator_does_not_count_nonverbal_as_verbal_technique():
    prompt = evaluator_system_prompt()
    assert "非語言內容" in prompt
    assert "不可當作口語句子" in prompt
    assert "verbal technique" in prompt


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
