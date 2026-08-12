"""Content Engine V1 contracts.

统一定义 Checklist / Playbook / ODO / Projection 的显式 schema，
让运行时不再依赖零散文案约定。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

OperatingReason = Literal[
    "TIME",
    "ANOMALY",
    "CONTINUATION",
    "OPPORTUNITY",
    "GOAL_DEVIATION",
    "RESULT",
    "UNDERSTANDING",
]

OperatingDomain = Literal[
    "PLATFORM",
    "PRODUCT",
    "COMPETITION",
    "TRAFFIC",
    "PROFIT",
    "CUSTOMER",
    "REPUTATION",
    "STORE_GROWTH",
]

OperatingObjectType = Literal[
    "store",
    "sku",
    "campaign",
    "user_segment",
    "review",
    "thread",
    "goal",
    "other",
]

AnalysisNodeKey = Literal[
    "startup",
    "morning_readiness",
    "pre_lunch_nba",
    "lunch_protect",
    "post_lunch_review",
    "pre_dinner_nba",
    "dinner_protect",
    "night_settlement",
    "weekly_strategy",
    "monthly_strategy",
]

ChecklistBlockingMode = Literal["none", "safe_mode", "block_action", "block_startup"]
ChecklistAskPolicy = Literal["never", "infer_then_confirm", "ask_when_blocking", "ask_contextual"]
GuideType = Literal["QUESTION", "APPROVAL", "FILE_REQUEST", "PLAN_REVIEW", "RESULT", "PROGRESS", "INFO"]
ArbitrationOutcome = Literal["AUTO", "AUTO_AND_REPORT", "ASK_APPROVAL", "ASK_INFORMATION", "OBSERVE", "DROP"]
ProjectionStatus = Literal["need_you", "working", "waiting", "completed", "watching"]


class OperatingObjectRef(BaseModel):
    type: OperatingObjectType = "other"
    id: str = ""
    name: str = ""


class FindingSummary(BaseModel):
    metric: str = ""
    change: str = ""
    benchmark: str = ""
    note: str = ""


class DiagnosisSummary(BaseModel):
    primary: str = ""
    confidence: float = 0.7
    alternatives: list[str] = Field(default_factory=list)


class BusinessImpactSummary(BaseModel):
    orders: str = ""
    profit: str = ""
    ranking: str = ""
    rating: str = ""
    repurchase: str = ""
    summary: str = ""


class RecommendedAction(BaseModel):
    type: str = ""
    title: str = ""
    detail: str = ""
    window: str = ""
    budget_limit: Optional[float] = None
    owner: Literal["ai", "boss", "shared"] = "ai"


class SuccessMetric(BaseModel):
    metric: str = ""
    target: str = ""
    window: str = ""


class OperatingDecisionObject(BaseModel):
    """Operating Decision Object — Content Engine 的核心运行时对象。

    `reason/domain/object/source_node` 是新 contract。
    其余兼容字段用于平滑承接现有 pipeline / API。
    """

    id: str = ""
    reason: OperatingReason = "ANOMALY"
    domain: OperatingDomain = "PRODUCT"
    object: OperatingObjectRef = Field(default_factory=OperatingObjectRef)
    source_node: Optional[AnalysisNodeKey] = None

    why_now: str = ""
    finding: FindingSummary = Field(default_factory=FindingSummary)
    diagnosis: DiagnosisSummary = Field(default_factory=DiagnosisSummary)
    evidence: list[str] = Field(default_factory=list)
    business_impact: BusinessImpactSummary = Field(default_factory=BusinessImpactSummary)
    candidate_actions: list[RecommendedAction] = Field(default_factory=list)
    recommended_action: RecommendedAction = Field(default_factory=RecommendedAction)
    required_context_keys: list[str] = Field(default_factory=list)
    human_required: bool = False
    human_reason: str = ""
    success_metric: SuccessMetric = Field(default_factory=SuccessMetric)
    next_check_at: str = ""

    execution_mode: ArbitrationOutcome = "ASK_APPROVAL"
    pipeline_steps_completed: list[str] = Field(default_factory=list)
    safe_mode_blocked: bool = False

    # Compatibility fields for current runtime.
    trigger: str = ""
    created_at: str = ""
    subject: str = ""
    observation: str = ""
    comparison: str = ""
    confidence: float = 0.7
    goal_relevance: str = ""
    goal_relevance_level: Literal["high", "medium", "low"] = "medium"
    action_type: str = ""
    human_request: str = ""
    observation_window_hours: int = 48
    next_check: str = ""
    autonomy: str = ""
    profitability: Optional[str] = None
    risk_level: Literal["low", "medium", "high"] = "medium"
    reversibility: Literal["easy", "medium", "hard"] = "medium"
    estimated_loss: Optional[float] = None


class WorkThreadProjection(BaseModel):
    id: str
    title: str
    status: ProjectionStatus = "working"
    owner_line: str = ""
    next_step: str = ""
    source_odo_id: str = ""


class GuideChoice(BaseModel):
    id: str
    label: str


class GuideDirective(BaseModel):
    id: str = ""
    type: GuideType = "INFO"
    title: str = ""
    prompt: str = ""
    explanation: str = ""
    choices: list[GuideChoice] = Field(default_factory=list)
    allow_free_text: bool = False
    allow_file: bool = False
    required_context_keys: list[str] = Field(default_factory=list)
    source_odo_id: str = ""


class ProactiveEventProjection(BaseModel):
    id: str
    reason: OperatingReason
    domain: OperatingDomain
    headline: str
    summary: str = ""
    occurred_at: str = ""
    status: str = "observing"
    source_odo_id: str = ""


class ChecklistFieldSpec(BaseModel):
    key: str
    label: str = ""
    domain: OperatingDomain
    source_priority: list[str] = Field(default_factory=list)
    first_required_at: str = ""
    used_by: list[str] = Field(default_factory=list)
    blocking_mode: ChecklistBlockingMode = "none"
    ask_policy: ChecklistAskPolicy = "ask_contextual"
    stale_after: str = ""
    fallback: str = ""


class AnalysisPlaybookRule(BaseModel):
    node: AnalysisNodeKey
    enabled_when: list[str] = Field(default_factory=list)
    domains: list[OperatingDomain] = Field(default_factory=list)
    output_limit: int = 1
    protect_mode: bool = False
    allowed_reasons: list[OperatingReason] = Field(default_factory=list)
    summary: str = ""
