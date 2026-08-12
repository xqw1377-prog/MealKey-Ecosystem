from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.store_state import StoreState

AgentKey = Literal[
    "competition",
    "menu",
    "product",
    "storefront",
    "diagnosis",
    "growth",
    "promo",
    "ads",
    "crm",
    "service",
    "review",
    "store_matrix",
]


class AgentMeta(BaseModel):
    key: AgentKey
    label: str
    version: str = "v2"
    confidence: Optional[float] = None
    generated_at: datetime
    # LLM 增强后的自然语言总结（未配置 LLM 或失败时为 None，前端回退到 conclusion）
    ai_narrative: Optional[str] = None
    ai_mode: Optional[str] = None  # llm | heuristic_fallback | None


class CompetitorBrief(BaseModel):
    competitor_id: str
    name: str
    score: int
    distance_m: Optional[int] = None
    price_band: Optional[str] = None
    rating: Optional[float] = None
    positioning: str
    advantage: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    featured_products: list[str] = Field(default_factory=list)
    menu_item_count: int = 0
    set_meal_count: int = 0
    recent_move: Optional[str] = None


class CompetitionChangeView(BaseModel):
    type: str
    summary: str
    price: Optional[float] = None


class CompetitionAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    benchmark_group: str
    competition_score: int
    nearby_total: int = 0
    market_focus: list[str] = Field(default_factory=list)
    top_competitors: list[CompetitorBrief] = Field(default_factory=list)
    changes: list[CompetitionChangeView] = Field(default_factory=list)
    threat_signals: list[str] = Field(default_factory=list)
    conclusion: str
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    expected_impact: str


class MenuRoleItem(BaseModel):
    item_id: str
    name: str
    role: str
    price: Optional[float] = None
    order_share_pct: Optional[float] = None
    ctr_delta_pct: Optional[float] = None
    cvr: Optional[float] = None
    rationale: str


class MenuCategorySummary(BaseModel):
    category: str
    item_count: int
    avg_price: Optional[float] = None
    top_roles: list[str] = Field(default_factory=list)
    health_note: str


class MenuPricingLadder(BaseModel):
    anchor_min: Optional[float] = None
    anchor_max: Optional[float] = None
    low_band_count: int = 0
    mid_band_count: int = 0
    high_band_count: int = 0
    gap_note: Optional[str] = None


class MenuBundleOpportunity(BaseModel):
    primary_item_id: Optional[str] = None
    primary_item_name: str
    attach_item_id: Optional[str] = None
    attach_item_name: str
    reason: str
    expected_outcome: str


class MenuCleanupCandidate(BaseModel):
    item_id: str
    name: str
    role: str
    reason: str
    action: str


class MenuPatchSuggestion(BaseModel):
    patch_type: str
    target_role: str
    item_name: str
    suggested_category: Optional[str] = None
    suggested_price: Optional[float] = None
    reason: str
    expected_outcome: str
    evidence_count: int = 0
    sources: list[str] = Field(default_factory=list)


class MenuPatchApplyResponse(BaseModel):
    store_id: str
    patch_index: int
    item_id: str
    item_name: str
    recommendation_id: str
    experiment_id: Optional[str] = None
    status: str
    message: str
    review_note: Optional[str] = None
    observe_focus: list[str] = Field(default_factory=list)
    next_decision: Optional[str] = None
    patch: MenuPatchSuggestion


class MenuCleanupApplyResponse(BaseModel):
    store_id: str
    candidate_index: int
    item_id: str
    item_name: str
    recommendation_id: str
    experiment_id: Optional[str] = None
    status: str
    message: str
    review_note: Optional[str] = None
    observe_focus: list[str] = Field(default_factory=list)
    next_decision: Optional[str] = None
    candidate: MenuCleanupCandidate


class MenuBundleApplyResponse(BaseModel):
    store_id: str
    opportunity_index: int
    item_id: str
    item_name: str
    recommendation_id: str
    experiment_id: Optional[str] = None
    status: str
    message: str
    review_note: Optional[str] = None
    observe_focus: list[str] = Field(default_factory=list)
    next_decision: Optional[str] = None
    opportunity: MenuBundleOpportunity


class MenuAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    menu_health_score: int
    role_distribution: dict[str, int] = Field(default_factory=dict)
    items: list[MenuRoleItem] = Field(default_factory=list)
    workflow_summary: Optional[str] = None
    category_summary: list[MenuCategorySummary] = Field(default_factory=list)
    pricing_ladder: MenuPricingLadder = Field(default_factory=MenuPricingLadder)
    bundle_opportunities: list[MenuBundleOpportunity] = Field(default_factory=list)
    cleanup_candidates: list[MenuCleanupCandidate] = Field(default_factory=list)
    suggested_patches: list[MenuPatchSuggestion] = Field(default_factory=list)
    structural_gaps: list[str] = Field(default_factory=list)
    document_gaps: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class ProductSuggestion(BaseModel):
    type: str
    title: str
    detail: str
    action_type: Optional[str] = None
    priority: int = 1
    expected_metric: Optional[str] = None
    expected_lift_pct_low: Optional[float] = None
    expected_lift_pct_high: Optional[float] = None
    window_hours: int = 24
    risk_level: str = "low"
    rollback_rule: Optional[str] = None
    generated_content: dict[str, Any] = Field(default_factory=dict)


class ProductHealthDimension(BaseModel):
    key: str
    label: str
    score: int
    observed_value: Optional[float] = None
    baseline_value: Optional[float] = None
    delta_pct: Optional[float] = None
    status: str


class ProductRootCause(BaseModel):
    code: str
    stage: str
    title: str
    explanation: str
    confidence: float
    evidence: list[str] = Field(default_factory=list)


class ProductCandidate(BaseModel):
    item_id: str
    name: str
    role: str
    health_score: int
    opportunity_score: int
    diagnosis_stage: str
    issue: str
    recommended_action: str
    order_share_pct: Optional[float] = None
    ctr_delta_pct: Optional[float] = None
    cvr_delta_pct: Optional[float] = None


class ProductActionCreateResponse(BaseModel):
    store_id: str
    item_id: str
    item_name: str
    suggestion_index: int
    recommendation_id: str
    experiment_id: Optional[str] = None
    status: str
    message: str
    review_note: Optional[str] = None
    observe_focus: list[str] = Field(default_factory=list)
    next_decision: Optional[str] = None
    suggestion: ProductSuggestion


class AgentWorkflowItem(BaseModel):
    recommendation_id: str
    title: str
    action_type: str
    object_ref: str
    object_name: str
    status: str
    execution_phase: str = "observe"
    phase_reason: Optional[str] = None
    expected_metric: str
    window_hours: int
    confidence: float
    rollback_rule: Optional[str] = None
    evidence: list[str] = Field(default_factory=list)
    generated_content: dict[str, Any] = Field(default_factory=dict)
    experiment_id: Optional[str] = None
    experiment_result: Optional[str] = None
    experiment_lift_pct: Optional[float] = None
    experiment_notes: Optional[str] = None
    next_decision: Optional[str] = None


class ProductAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    focus_item_id: Optional[str] = None
    focus_item_name: str
    health_score: int = 0
    health_dimensions: list[ProductHealthDimension] = Field(default_factory=list)
    diagnosis_stage: str
    issue: str
    diagnosis: str
    why_now: Optional[str] = None
    metrics: dict[str, Optional[float]] = Field(default_factory=dict)
    root_causes: list[ProductRootCause] = Field(default_factory=list)
    decision_path: list[str] = Field(default_factory=list)
    item_candidates: list[ProductCandidate] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[ProductSuggestion] = Field(default_factory=list)
    related_actions: list[str] = Field(default_factory=list)
    experiment_guardrail: str = "一次只执行一个商品动作，观察窗结束后再进入下一步。"
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class DiagnosisObservationView(BaseModel):
    metric: str
    what_happened: str
    delta_pct: Optional[float] = None
    confidence: Optional[float] = None


class DiagnosisComparison(BaseModel):
    key: str
    label: str
    current_from: Optional[str] = None
    current_to: Optional[str] = None
    baseline_from: Optional[str] = None
    baseline_to: Optional[str] = None
    orders_delta_pct: Optional[float] = None
    gmv_delta_pct: Optional[float] = None
    status: str = "unavailable"
    note: str


class DiagnosisMetricSignal(BaseModel):
    metric: str
    label: str
    observed_value: Optional[float] = None
    baseline_value: Optional[float] = None
    delta_pct: Optional[float] = None
    severity: str
    direction: str
    confidence: float


class DiagnosisRootCause(BaseModel):
    rank: int
    code: str
    title: str
    explanation: str
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    affected_metrics: list[str] = Field(default_factory=list)


class DiagnosisMarketComparison(BaseModel):
    availability: str = "unavailable"
    data_type: str = "unavailable"
    own_orders_delta_pct: Optional[float] = None
    market_orders_delta_pct: Optional[float] = None
    relative_status: str = "unknown"
    note: str


class DiagnosisAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    diagnosis_score: int = 0
    executive_summary: str = ""
    daily_summary: str
    primary_problem: str
    root_cause: Optional[str] = None
    comparisons: list[DiagnosisComparison] = Field(default_factory=list)
    metric_signals: list[DiagnosisMetricSignal] = Field(default_factory=list)
    root_causes: list[DiagnosisRootCause] = Field(default_factory=list)
    market_comparison: Optional[DiagnosisMarketComparison] = None
    data_gaps: list[str] = Field(default_factory=list)
    observations: list[DiagnosisObservationView] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    action_priorities: list[str] = Field(default_factory=list)
    workflow_summary: Optional[str] = None
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class GrowthActionView(BaseModel):
    action_type: str
    title: str
    object_name: str
    summary: str
    expected_metric: str
    window_hours: int
    confidence: float
    score: Optional[float] = None


class GrowthScoreFactors(BaseModel):
    expected_impact: float
    confidence: float
    ease_of_execution: float
    strategic_fit: float
    risk: float


class GrowthOpportunityView(BaseModel):
    key: str
    source_agent: str
    title: str
    problem: str
    action_type: str
    object_name: str
    expected_metric: str
    expected_lift_pct_low: Optional[float] = None
    expected_lift_pct_high: Optional[float] = None
    score: float
    factors: GrowthScoreFactors
    evidence: list[str] = Field(default_factory=list)
    recommendation_id: Optional[str] = None
    status: str = "candidate"
    executable: bool = False


class GrowthPlanStep(BaseModel):
    day: int
    title: str
    goal: str
    instruction: str
    verify: str
    status: str = "planned"
    source_agent: Optional[str] = None
    recommendation_id: Optional[str] = None
    dependency: Optional[str] = None
    stop_condition: Optional[str] = None


class GrowthAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    execution_mode: str = "experiment"
    strategy_score: int = 0
    weekly_goal: str = ""
    today_priority: Optional[str] = None
    reason: str
    evidence: list[str] = Field(default_factory=list)
    opportunity_pool: list[GrowthOpportunityView] = Field(default_factory=list)
    selected_opportunity: Optional[GrowthOpportunityView] = None
    top_actions: list[GrowthActionView] = Field(default_factory=list)
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None
    experiments_summary: dict[str, int] = Field(default_factory=dict)
    learning_summary: str = ""
    plan_progress_pct: int = 0
    weekly_plan: list[GrowthPlanStep] = Field(default_factory=list)
    do_not_do: list[str] = Field(default_factory=list)


class StorefrontDimension(BaseModel):
    key: str
    label: str
    score: int
    status: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    sales_lever: str = "ctr"


class StorefrontIssue(BaseModel):
    code: str
    severity: str
    title: str
    detail: str
    evidence: list[str] = Field(default_factory=list)
    sales_impact_est: str
    suggested_action_type: str
    dimension_key: str
    object_ref: Optional[str] = None
    object_name: Optional[str] = None


class StorefrontSalesImpact(BaseModel):
    primary_metric: str
    lift_pct_low: float
    lift_pct_high: float
    narrative: str
    confidence: float = 0.6


class StorefrontPriorityAction(BaseModel):
    action_type: str
    title: str
    detail: str
    expected_metric: str
    expected_lift_pct_low: float
    expected_lift_pct_high: float
    window_hours: int = 24
    risk_level: str = "low"
    severity: str = "medium"
    object_ref: str
    object_name: str
    generated_content: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)


class StorefrontAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    health_score: int = 0
    dimensions: list[StorefrontDimension] = Field(default_factory=list)
    issues: list[StorefrontIssue] = Field(default_factory=list)
    sales_impact: Optional[StorefrontSalesImpact] = None
    priority_actions: list[StorefrontPriorityAction] = Field(default_factory=list)
    conclusion: str = ""
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    expected_impact: str = ""
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class StorefrontActionCreateResponse(BaseModel):
    store_id: str
    action_index: int
    recommendation_id: str
    experiment_id: Optional[str] = None
    status: str
    message: str
    review_note: Optional[str] = None
    observe_focus: list[str] = Field(default_factory=list)
    next_decision: Optional[str] = None
    action: StorefrontPriorityAction


class StorefrontImageAssistRequest(BaseModel):
    item_id: Optional[str] = None
    item_name: Optional[str] = None
    problem: Optional[str] = None


class StorefrontActionCreateRequest(BaseModel):
    with_ai: bool = True


class AgentPriorityAction(BaseModel):
    action_type: str
    title: str
    detail: str
    expected_metric: str
    expected_lift_pct_low: float = 0.0
    expected_lift_pct_high: float = 0.0
    window_hours: int = 24
    risk_level: str = "low"
    severity: str = "medium"
    object_ref: str
    object_name: str
    generated_content: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    profit_gate_allowed: Optional[bool] = None
    profit_gate_reason: Optional[str] = None
    create_enabled: bool = True
    create_block_reason: Optional[str] = None


class AgentActionCreateResponse(BaseModel):
    store_id: str
    agent_key: AgentKey
    action_index: int
    recommendation_id: str
    experiment_id: Optional[str] = None
    status: str
    message: str
    review_note: Optional[str] = None
    observe_focus: list[str] = Field(default_factory=list)
    next_decision: Optional[str] = None
    action: AgentPriorityAction


class AgentSignal(BaseModel):
    code: str
    title: str
    detail: str
    severity: str = "medium"
    evidence: list[str] = Field(default_factory=list)


class PromoAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    health_score: int = 0
    unlock_ready: bool = False
    signals: list[AgentSignal] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    priority_actions: list[AgentPriorityAction] = Field(default_factory=list)
    conclusion: str = ""
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    expected_impact: str = ""
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class AdsAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    health_score: int = 0
    unlock_ready: bool = False
    traffic_readiness_score: Optional[int] = None  # 投流就绪度 0-100（步骤4）
    recommended_budget: Optional[float] = None
    target_item_name: Optional[str] = None
    estimated_roi: Optional[float] = None
    signals: list[AgentSignal] = Field(default_factory=list)
    priority_actions: list[AgentPriorityAction] = Field(default_factory=list)
    conclusion: str = ""
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    expected_impact: str = ""
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class CrmSegmentView(BaseModel):
    key: str
    label: str
    estimated_count: int
    share_pct: Optional[float] = None
    note: str


class CrmAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    health_score: int = 0
    repurchase_rate: Optional[float] = None
    repurchase_delta_pct: Optional[float] = None
    segments: list[CrmSegmentView] = Field(default_factory=list)
    signals: list[AgentSignal] = Field(default_factory=list)
    priority_actions: list[AgentPriorityAction] = Field(default_factory=list)
    conclusion: str = ""
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    expected_impact: str = ""
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class ServiceAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    health_score: int = 0
    pending_replies: int = 0
    negative_review_count: int = 0
    theme_breakdown: dict[str, int] = Field(default_factory=dict)
    signals: list[AgentSignal] = Field(default_factory=list)
    priority_actions: list[AgentPriorityAction] = Field(default_factory=list)
    conclusion: str = ""
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    expected_impact: str = ""
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class ReviewThemeView(BaseModel):
    theme: str
    label: str
    count: int
    share_pct: float
    sample: Optional[str] = None


class ReviewAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    health_score: int = 0
    avg_rating: Optional[float] = None
    rating_delta_pct: Optional[float] = None
    review_count: int = 0
    themes: list[ReviewThemeView] = Field(default_factory=list)
    signals: list[AgentSignal] = Field(default_factory=list)
    priority_actions: list[AgentPriorityAction] = Field(default_factory=list)
    conclusion: str = ""
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    expected_impact: str = ""
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class StoreMatrixConcept(BaseModel):
    code: str
    name: str
    positioning: str
    daypart: str
    rationale: str
    readiness: str = "candidate"


class StoreMatrixAgentResult(BaseModel):
    meta: AgentMeta
    readiness: str = "partial"
    blockers: list[str] = Field(default_factory=list)
    health_score: int = 0
    unlock_ready: bool = False
    sibling_store_count: int = 0
    sibling_stores: list[str] = Field(default_factory=list)
    concepts: list[StoreMatrixConcept] = Field(default_factory=list)
    signals: list[AgentSignal] = Field(default_factory=list)
    priority_actions: list[AgentPriorityAction] = Field(default_factory=list)
    conclusion: str = ""
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    expected_impact: str = ""
    action_queue: list[AgentWorkflowItem] = Field(default_factory=list)
    current_action: Optional[AgentWorkflowItem] = None


class StoreAgentsResponse(BaseModel):
    store_id: str
    store_name: str
    days: int
    generated_at: datetime
    store_state: StoreState
    competition: CompetitionAgentResult
    menu: MenuAgentResult
    product: ProductAgentResult
    storefront: StorefrontAgentResult
    diagnosis: DiagnosisAgentResult
    growth: GrowthAgentResult
    promo: PromoAgentResult
    ads: AdsAgentResult
    crm: CrmAgentResult
    service: ServiceAgentResult
    review: ReviewAgentResult
    store_matrix: StoreMatrixAgentResult
