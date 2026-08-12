from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Formal learning loop:
# Observation → Hypothesis → Recommendation → Experiment → Result → Strategy Memory

ResultLabel = Literal["positive", "neutral", "negative", "unknown", "pending"]


class ExperimentResultView(BaseModel):
    """OHRE 的 Result 层：实验必须留下可复用结论。"""

    experiment_id: str
    recommendation_id: str
    store_id: str
    action_type: str
    object_ref: str
    object_name: Optional[str] = None
    metric: str
    lift_pct: Optional[float] = None
    result: ResultLabel = "pending"
    attribution_quality: Literal["high", "medium", "low"] = "medium"
    window_hours: Optional[int] = None
    summary: str = ""
    evaluated_at: Optional[datetime] = None
    evidence: list[str] = Field(default_factory=list)


class StrategyMemoryItem(BaseModel):
    """Strategy Memory：把 Result 变成下一次决策经验。"""

    id: str
    store_id: str
    action_type: str
    context_tags: list[str] = Field(default_factory=list)
    result: ResultLabel
    lift_pct: Optional[float] = None
    lesson: str
    reuse_when: str
    avoid_when: Optional[str] = None
    source_experiment_id: Optional[str] = None
    confidence: float = 0.6
    created_at: datetime


class StrategyMemorySnapshot(BaseModel):
    store_id: str
    items: list[StrategyMemoryItem] = Field(default_factory=list)
    positive_patterns: list[str] = Field(default_factory=list)
    negative_patterns: list[str] = Field(default_factory=list)
