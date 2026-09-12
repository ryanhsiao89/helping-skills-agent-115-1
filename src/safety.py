"""教學系統的最低限度危機攔截。

這不是臨床風險評估工具。目的只是在體驗模式出現明確、第一人稱、即時的
自傷／他傷語句時停止角色扮演，改提供真人求助方向。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyResult:
    is_crisis: bool
    matched_pattern: str = ""


_CRISIS_PATTERNS = (
    r"我.{0,8}(現在|等等|今天|今晚).{0,8}(想死|自殺|結束生命|傷害自己)",
    r"我.{0,8}(已經|正在|準備|打算).{0,8}(自殺|割腕|跳樓|吞藥|傷害自己|殺人|傷害他人)",
    r"I\s*(am|'m)?\s*(going to|planning to|about to).{0,20}(kill myself|hurt myself|kill someone)",
)


def detect_immediate_crisis(text: str) -> SafetyResult:
    normalized = " ".join(text.strip().split())
    for pattern in _CRISIS_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return SafetyResult(True, pattern)
    return SafetyResult(False)


def crisis_response() -> str:
    return (
        "我先停止這段教學模擬。你剛才的內容可能涉及立即安全風險，現在最重要的不是繼續和 AI 演練，"
        "而是讓真人立即陪你。請先離開可能造成傷害的物品或地點，聯絡一位你信任且能到場的人；"
        "若你或他人可能立即受傷，請撥打 119 或 110，或直接前往最近的急診。"
        "在臺灣也可撥打衛生福利部 1925 安心專線，取得 24 小時免付費心理支持。"
    )
