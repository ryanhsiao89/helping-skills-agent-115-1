"""晤談後結構化回饋的資料模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackPoint(BaseModel):
    title: str = Field(description="具體而簡短的回饋標題")
    evidence_quote: str = Field(
        description="逐字稿中的完整短句；無證據時填寫『目前查無明確逐字稿證據』"
    )
    explanation: str = Field(description="此句的功能、效果或問題")
    alternative_response: str = Field(default="", description="可改寫的替代回應；優點項目可留空")


class TechniqueEvent(BaseModel):
    technique: str = Field(description="助人技巧名稱")
    category: Literal["探索", "洞察", "行動", "跨階段"]
    evidence_quote: str = Field(description="實際逐字稿引句")
    quality: Literal["機械套用", "基本恰當", "自然且有助益", "無法判定"]
    rationale: str = Field(description="判定技巧與品質的理由")
    effect: str = Field(description="緊接其後可觀察到的對話效果；不可臆測內在效果")
    alternative_response: str = Field(default="", description="必要時提供較合適說法")


class SkillStatistic(BaseModel):
    technique: str
    count: int = Field(ge=0)
    note: str = Field(default="", description="次數不等於品質；必要的限定說明")


class ContinuitySummary(BaseModel):
    """供下一次體驗模式續談使用的去識別摘要。"""

    topic_label: str = Field(default="", description="本次談話的簡短主題標籤，不含可識別資訊")
    summary_text: str = Field(default="", description="本次談話重點摘要，只使用逐字稿已出現內容")
    unresolved_points: list[str] = Field(
        default_factory=list,
        description="尚未談完或可在下次延續的重點，不得新增逐字稿未出現的事實",
    )
    next_opening: str = Field(
        default="",
        description="下一次續談時 AI 可使用的自然開場白；不可宣稱記得未被保存的內容",
    )


class AssessmentResult(BaseModel):
    mode: Literal["experience", "practice"]
    overall_summary: str
    stage_judgment: str
    strengths: list[FeedbackPoint] = Field(min_length=1, max_length=3)
    improvement_points: list[FeedbackPoint] = Field(min_length=1, max_length=3)
    technique_events: list[TechniqueEvent]
    skill_statistics: list[SkillStatistic]
    next_practice_tasks: list[str] = Field(min_length=1, max_length=2)
    evidence_limitations: str = Field(
        default="",
        description="資料不足、晤談太短或無法可靠判定之處；沒有則留空",
    )
    continuity: ContinuitySummary = Field(
        default_factory=ContinuitySummary,
        description="僅供 experience 模式跨次續談；practice 模式可留空",
    )
