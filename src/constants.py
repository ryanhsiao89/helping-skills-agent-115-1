"""跨模組共用常數與 Google Sheets 欄位定義。"""

from __future__ import annotations

AGENT_TYPE = "helping"
PROMPT_VERSION_DEFAULT = "helping-v1.0.0"
RUBRIC_VERSION_DEFAULT = "helping-rubric-v1.0.0"

STAGES = ("exploration", "insight", "action")
STAGE_LABELS = {
    "exploration": "探索",
    "insight": "洞察",
    "action": "行動",
    "full_demo": "完整示範",
}

MODE_LABELS = {
    "experience": "體驗模式：學生當個案",
    "practice": "實作模式：學生當諮商師",
}

SHEET_HEADERS: dict[str, list[str]] = {
    "Sessions": [
        "session_id",
        "participant_id",
        "agent_type",
        "mode",
        "started_at",
        "ended_at",
        "duration_seconds",
        "duration_target_min",
        "case_id",
        "stage_start",
        "stage_end",
        "model_name",
        "prompt_version",
        "completion_status",
        "message_count",
        "crisis_flag",
    ],
    "ChatLogs": [
        "turn_id",
        "session_id",
        "turn_index",
        "speaker_role",
        "speaker_id",
        "content_raw",
        "timestamp",
        "stage_at_turn",
        "skill_labels",
        "selected_skill_match",
        "latency_ms",
        "error_flag",
        "model_name",
        "prompt_version",
    ],
    "SkillEvents": [
        "skill_event_id",
        "session_id",
        "assessment_id",
        "technique",
        "category",
        "evidence_quote",
        "quality",
        "rationale",
        "effect",
        "alternative_response",
        "created_at",
        "evaluator_model",
        "rubric_version",
    ],
    "Assessments": [
        "assessment_id",
        "session_id",
        "rubric_version",
        "created_at",
        "dimension_scores_json",
        "stage_judgment",
        "strengths_json",
        "improvement_points_json",
        "quoted_examples_json",
        "next_tasks_json",
        "raw_model_output",
        "parsed_json",
        "evaluator_model",
        "evaluator_temperature",
        "status",
    ],
    # 跨日續談記憶。既有四張研究資料表完全不改欄位，避免舊資料 schema mismatch。
    "ContinuityMemory": [
        "memory_id",
        "participant_id",
        "conversation_id",
        "session_id",
        "parent_session_id",
        "session_number",
        "updated_at",
        "topic_label",
        "summary_text",
        "unresolved_points_json",
        "next_opening",
        "recent_context_json",
        "pin_hash",
        "memory_status",
    ],
}
