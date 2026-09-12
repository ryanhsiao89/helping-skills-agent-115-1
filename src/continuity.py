"""跨日續談記憶的純函式工具；不依賴 Streamlit。"""

from __future__ import annotations

import uuid
from typing import Any


def recent_context(messages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, str]]:
    """保存前次最後數輪對話；排除 system/error 訊息，避免把技術錯誤帶入續談。"""
    selected: list[dict[str, str]] = []
    for message in messages:
        if message.get("ui_role") == "system" or message.get("speaker_role") == "system":
            continue
        content = " ".join(str(message.get("content", "")).split()).strip()
        if not content:
            continue
        selected.append(
            {
                "speaker_role": str(message.get("speaker_role", "")),
                "content": content,
            }
        )
    return selected[-limit:]


def build_memory_record(
    *,
    session: dict[str, Any],
    messages: list[dict[str, Any]],
    updated_at: str,
    continuity: dict[str, Any] | None,
    status: str,
) -> dict[str, Any]:
    continuity = continuity or {}
    topic_label = str(continuity.get("topic_label", "") or "").strip()
    summary_text = str(continuity.get("summary_text", "") or "").strip()
    unresolved = continuity.get("unresolved_points", []) or []
    next_opening = str(continuity.get("next_opening", "") or "").strip()

    if not topic_label:
        topic_label = str(session.get("experience_topic_label", "") or "")
    if not summary_text:
        summary_text = "前次摘要未能完整產生；續談時請以前次最後幾輪對話為主要脈絡。"
    if not next_opening:
        next_opening = "上次我們談過一段近況。今天你想從上次談到的地方繼續，還是先說說這幾天有什麼變化？"

    return {
        "memory_id": str(uuid.uuid4()),
        "participant_id": session["participant_id"],
        "conversation_id": session["conversation_id"],
        "session_id": session["session_id"],
        "parent_session_id": session.get("parent_session_id", ""),
        "session_number": session.get("conversation_session_number", 1),
        "updated_at": updated_at,
        "topic_label": topic_label,
        "summary_text": summary_text,
        "unresolved_points_json": unresolved,
        "next_opening": next_opening,
        "recent_context_json": recent_context(messages),
        # 舊版欄位保留以避免既有試算表 schema mismatch；Email OTP 版不再使用固定 PIN。
        "pin_hash": "",
        "memory_status": status,
    }
