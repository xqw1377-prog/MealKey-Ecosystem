"""RESEARCH-TE-01 — Incremental Result semantics (Research Zone).

Not wired into Profit Gate, Permission, or experiment_attribution.
V1 observed lift (before/after) remains the production path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# 三层结果不得混写。Ranking 权重必须不同。
ResultLayer = Literal["observed", "attributed", "incremental"]
RESULT_LAYER_RANK_WEIGHT: dict[str, float] = {
    "observed": 0.25,
    "attributed": 0.55,
    "incremental": 1.0,
}


class ObservedResult(BaseModel):
    """before → after。例如订单 +12%。"""

    layer: Literal["observed"] = "observed"
    metric: str
    lift_pct: Optional[float] = None
    summary: str = ""


class AttributedResult(BaseModel):
    """现有 Attribution 之后：与该 Action 相关的提升。例如 ≈ +7%。"""

    layer: Literal["attributed"] = "attributed"
    metric: str
    lift_pct: Optional[float] = None
    attribution_quality: Literal["high", "medium", "low"] = "medium"
    summary: str = ""


EvidenceGrade = Literal[
    "L0_RESEARCH",
    "L1_STORE_CONTRAST",
    "L2_CROSS_STORE",
    "L3_PROFIT_VERIFIED",
]

# L0 (含任何 MT-LIFT 训练物) 不得影响生产。
PRODUCTION_RANKING_MIN_GRADE: tuple[EvidenceGrade, ...] = ("L2_CROSS_STORE", "L3_PROFIT_VERIFIED")
PRODUCTION_FORBIDDEN_GRADES: tuple[EvidenceGrade, ...] = ("L0_RESEARCH",)


class TreatmentSpec(BaseModel):
    treatment: str
    control: str = "no_action"
    target_population: str = ""
    eligibility_rule: str = ""
    observation_window_hours: int = 48
    treatment_cost: Optional[float] = None
    treatment_cost_unit: str = "CNY"
    treatment_cost_known: bool = False


class IncrementalResult(BaseModel):
    """相对 control 的增量，不是 before/after 的 observed lift。

    incremental_profit 未知时必须保持 None / UNKNOWN，禁止用转化率冒充利润。
    """

    experiment_id: str
    store_id: str
    action_type: str

    treatment: TreatmentSpec

    primary_outcome: str = "incremental_contribution_profit"
    secondary_outcomes: list[str] = Field(default_factory=list)

    observed_lift_pct: Optional[float] = None
    estimated_ate: Optional[float] = None
    estimated_cate: Optional[float] = None

    incremental_orders: Optional[float] = None
    incremental_revenue: Optional[float] = None
    incremental_profit: Optional[float] = None

    layer: Literal["incremental"] = "incremental"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    attribution_quality: Literal["high", "medium", "low"] = "low"
    evidence_grade: EvidenceGrade = "L0_RESEARCH"

    summary: str = ""
    evaluated_at: Optional[datetime] = None


def may_influence_candidate_ranking(result: IncrementalResult) -> bool:
    """Uplift 只许做排序证据，且须达到 L2+。任何 L0 研究物都不行。"""
    if result.evidence_grade in PRODUCTION_FORBIDDEN_GRADES:
        return False
    return result.evidence_grade in PRODUCTION_RANKING_MIN_GRADE


def may_authorize_action(result: IncrementalResult) -> bool:
    """Uplift 永远不能单独授权发券 / 写回。"""
    return False
