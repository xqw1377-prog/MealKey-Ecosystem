from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.arbiter import OpsQueueBrief
from app.schemas.mealkey_score import MealKeyScore, OperationScore


class DeltaMetric(BaseModel):
    delta_pct: Optional[float] = None
    confidence: float = 0.7
    value: Optional[float] = None
    baseline_value: Optional[float] = None
    observed_value: Optional[float] = None


class StoreInfo(BaseModel):
    store_id: str
    name: str
    category: Optional[str] = None
    city: Optional[str] = None
    lng: Optional[float] = None
    lat: Optional[float] = None


class MarketInfo(BaseModel):
    market_type: list[str] = Field(default_factory=list)
    radius_m: int = 1000
    as_of: Optional[str] = None


class WindowInfo(BaseModel):
    from_day: date
    to_day: date
    compare_from_day: date
    compare_to_day: date


class CoreItem(BaseModel):
    item_id: str
    name: str
    order_share_pct: Optional[float] = None
    ctr_delta_pct: Optional[float] = None
    flags: list[str] = Field(default_factory=list)


class CompetitionChange(BaseModel):
    c_store_id: str
    type: str
    summary: str
    price: Optional[float] = None


class FeedbackInfo(BaseModel):
    keywords: list[dict] = Field(default_factory=list)
    scores: dict = Field(default_factory=dict)
    # 差评闭环信号
    recent_review_count: int = 0
    recent_bad_review_count: int = 0  # 近期 1-3 星评价数
    bad_review_rate: Optional[float] = None  # 差评占比
    recent_bad_reviews: list[dict] = Field(default_factory=list)  # [{rating, content, reviewed_at}]


class PrimaryProblem(BaseModel):
    type: str
    confidence: float


# ---------- Sensing layer (P0 frozen) ----------

class HealthSignal(BaseModel):
    key: str
    label: str
    value: Optional[float] = None
    unit: Optional[str] = None
    status: Literal["ok", "watch", "risk", "unknown"] = "unknown"
    threshold: Optional[float] = None
    note: Optional[str] = None


class PlatformHealthState(BaseModel):
    """平台健康状态：进入 StoreState，不做独立页面。"""

    score: int = 0
    status: Literal["healthy", "watch", "risk", "unknown"] = "unknown"
    top_risk: Optional[str] = None
    judgment: str = ""
    open_status: Literal["open", "closed", "unknown"] = "unknown"
    business_hours_ok: Optional[bool] = None
    meal_prep_rate: Optional[float] = None
    merchant_cancel_rate: Optional[float] = None
    on_time_delivery_rate: Optional[float] = None
    im_reply_rate: Optional[float] = None
    store_rating: Optional[float] = None
    mid_bad_review_rate: Optional[float] = None
    hero_sku_in_stock_rate: Optional[float] = None
    decoration_completeness: Optional[float] = None
    violation_status: Literal["none", "warning", "penalty", "unknown"] = "unknown"
    activity_valid: Optional[bool] = None
    signals: list[HealthSignal] = Field(default_factory=list)


class ProfitState(BaseModel):
    """到手率 + 真实利润状态。Growth/活动/投流必须过 Profit Gate。"""

    gross_gmv: Optional[float] = None
    customer_paid: Optional[float] = None
    merchant_revenue: Optional[float] = None
    platform_commission: Optional[float] = None
    merchant_subsidy: Optional[float] = None
    ads_spend: Optional[float] = None
    packaging_cost: Optional[float] = None
    food_cost: Optional[float] = None
    refund_cost: Optional[float] = None
    take_home_rate: Optional[float] = None
    take_home_rate_delta_pct: Optional[float] = None
    contribution_margin: Optional[float] = None
    contribution_profit: Optional[float] = None
    contribution_profit_delta_pct: Optional[float] = None
    contribution_profit_per_order: Optional[float] = None
    data_quality: Literal["observed", "proxy", "missing"] = "missing"
    # UNKNOWN 一等状态:缺失的成本字段列表,驱动 Ask Engine
    missing_blocks: list[str] = Field(default_factory=list)
    judgment: str = ""


class BenchmarkMetric(BaseModel):
    key: str
    label: str
    store_value: Optional[float] = None
    area_avg: Optional[float] = None
    top_25_pct: Optional[float] = None
    top_10_pct: Optional[float] = None
    gap_vs_avg_pct: Optional[float] = None
    gap_vs_top25_pct: Optional[float] = None
    unit: str = "pct"


class BenchmarkState(BaseModel):
    """商圈对标：让 Diagnosis 从绝对值升级为相对位置判断。"""

    available: bool = False
    peer_count: int = 0
    metrics: list[BenchmarkMetric] = Field(default_factory=list)
    judgment: str = ""


class BusinessState(BaseModel):
    """经营结果摘要（由 KPI 投影，供店长首页使用）。"""

    health_score: int = 0
    orders: Optional[DeltaMetric] = None
    gmv: Optional[DeltaMetric] = None
    impressions: Optional[DeltaMetric] = None
    ctr: Optional[DeltaMetric] = None
    cvr: Optional[DeltaMetric] = None
    aov: Optional[DeltaMetric] = None
    judgment: str = ""


class CustomerState(BaseModel):
    """用户经营代理状态（无用户明细时用漏斗代理）。"""

    repurchase_rate: Optional[float] = None
    repurchase_delta_pct: Optional[float] = None
    new_customer_share_pct: Optional[float] = None
    churn_risk_level: Literal["low", "medium", "high", "unknown"] = "unknown"
    judgment: str = ""


class DataCoverage(BaseModel):
    """门店真实数据覆盖度。缺哪一块就诚实标出来，供 Ads/利润/归因 fail-closed。"""

    funnel_days: int = 0
    ads_days: int = 0
    reviews: int = 0
    order_rows: int = 0
    items_with_cost: int = 0
    synthetic_item_funnel: bool = False
    ads_source: Literal["ad_spend_daily", "shop_funnel", "missing"] = "missing"
    ads_observed: bool = False
    orders_observed: bool = False


class AdsSummary(BaseModel):
    """投流摘要 — 从 AdSpendDaily 聚合,暴露给前端和 analyze_ads。"""
    total_cost: Optional[float] = None
    avg_daily_cost: Optional[float] = None
    avg_cpc: Optional[float] = None
    avg_roas: Optional[float] = None
    avg_ctr: Optional[float] = None
    total_clicks: Optional[int] = None
    total_ads_orders: Optional[int] = None
    cpc_trend_pct: Optional[float] = None  # CPC 变化百分比
    roas_trend_pct: Optional[float] = None  # ROAS 变化百分比
    days: int = 0
    daily_rows: list[dict] = Field(default_factory=list)  # [{day, cost, clicks, cpc, roas}]
    findings: list[str] = Field(default_factory=list)  # analyze_ads 的关键发现


class StoreState(BaseModel):
    store: StoreInfo
    market: MarketInfo
    window: WindowInfo
    kpis: dict[str, DeltaMetric]
    core_items: list[CoreItem] = Field(default_factory=list)
    competition_changes: list[CompetitionChange] = Field(default_factory=list)
    feedback: FeedbackInfo = Field(default_factory=FeedbackInfo)
    primary_problem: Optional[PrimaryProblem] = None
    # Sensing layer
    business: BusinessState = Field(default_factory=BusinessState)
    platform_health: PlatformHealthState = Field(default_factory=PlatformHealthState)
    profit: ProfitState = Field(default_factory=ProfitState)
    benchmark: BenchmarkState = Field(default_factory=BenchmarkState)
    customer: CustomerState = Field(default_factory=CustomerState)
    data_coverage: DataCoverage = Field(default_factory=DataCoverage)
    ads_summary: AdsSummary = Field(default_factory=AdsSummary)
    generated_at: Optional[datetime] = None


class ActionCandidate(BaseModel):
    object_ref: str
    action_type: str
    expected_metric: str = "ctr"
    expected_lift_pct_low: Optional[float] = None
    expected_lift_pct_high: Optional[float] = None
    window_hours: int = 24
    rollback_rule: Optional[str] = None
    confidence: float = 0.7
    evidence: list[str] = Field(default_factory=list)
    score: Optional[float] = None


class DailyJobResult(BaseModel):
    store_state: StoreState
    observations: list[dict] = Field(default_factory=list)
    hypothesis: Optional[dict] = None
    opportunities: list[dict] = Field(default_factory=list)
    top_actions: list[ActionCandidate] = Field(default_factory=list)
    today_action: Optional[ActionCandidate] = None


ConfidenceLevel = Literal["high", "medium", "low"]


class BriefProblem(BaseModel):
    """晨报里的一条问题。"""
    title: str
    detail: str = ""
    severity: str = "medium"  # high | medium | low
    source_agent: str = ""  # 来自哪个 agent


class BriefResult(BaseModel):
    """结果通知：上次实验/动作的结论（第 6 类触发）。

    让老板感觉"AI 会对自己的建议负责"。
    """
    title: str  # "牛肉饭主图实验"
    outcome: str  # positive/negative/neutral/unknown
    detail: str  # "CTR +17.3%, 订单 +8.6%, 有效"
    action_type: str = ""
    lift_pct: Optional[float] = None
    recommendation_id: Optional[str] = None
    experiment_id: Optional[str] = None


class BriefTask(BaseModel):
    """晨报里的一条今日任务。"""
    title: str
    detail: str = ""
    expected_metric: str = ""  # ctr/cvr/orders/rating...
    expected_lift_low: Optional[float] = None  # 量化预计影响（下限%）
    expected_lift_high: Optional[float] = None  # 量化预计影响（上限%）
    agent_key: str = ""  # 建议来源 agent
    recommendation_id: Optional[str] = None
    status: Optional[str] = None  # proposed/adopted/executed/...


class ParallelNote(BaseModel):
    """结构化后台并行动作，替代纯字符串 parallel_service_notes。"""

    agent_key: str
    title: str
    kind: Literal["auto", "confirm", "scan"] = "auto"


class PrimaryExperimentBrief(BaseModel):
    """首页主实验闭环：确认 → 执行 → 观察 → 评估。"""

    title: str
    recommendation_id: Optional[str] = None
    experiment_id: Optional[str] = None
    status: Optional[str] = None
    expected_metric: str = ""
    expected_lift_low: Optional[float] = None
    expected_lift_high: Optional[float] = None
    window_hours: int = 48
    can_evaluate: bool = False
    result: Optional[str] = None


class ProfitSummaryBrief(BaseModel):
    contribution_profit: Optional[float] = None
    contribution_profit_delta_pct: Optional[float] = None
    contribution_profit_per_order: Optional[float] = None
    take_home_rate: Optional[float] = None
    take_home_rate_delta_pct: Optional[float] = None
    data_quality: Literal["observed", "proxy", "missing"] = "missing"
    missing_blocks: list[str] = Field(default_factory=list)
    judgment: str = ""


class ManagerHomeBrief(BaseModel):
    """首页状态机：现在怎么样 → 发生什么 → 为什么 → 今天做什么。

    V2 升级：新增 mealkey_score（5 维加权统一分）+ problems/tasks（3+3 结构）。
    V3：ops_queue 由 Priority Arbiter 产出——决策卡 / Goal / 经营线程。
    旧字段（top_problem_title 等）保留做兼容，前端可渐进迁移。
    """

    store_name: str
    business_health_score: int
    business_judgment: str
    top_problem_title: Optional[str] = None
    top_problem_detail: Optional[str] = None
    top_opportunity_title: Optional[str] = None
    top_opportunity_detail: Optional[str] = None
    primary_experiment_title: Optional[str] = None
    primary_experiment_window: Optional[str] = None
    parallel_service_notes: list[str] = Field(default_factory=list)
    open_event_count: int = 0
    platform_health_score: int = 0
    take_home_rate: Optional[float] = None
    # V2 新增
    mealkey_score: Optional[MealKeyScore] = None
    operation_score: Optional[OperationScore] = None
    problems: list[BriefProblem] = Field(default_factory=list)
    tasks: list[BriefTask] = Field(default_factory=list)
    parallel_notes: list[ParallelNote] = Field(default_factory=list)
    primary_experiment: Optional[PrimaryExperimentBrief] = None
    # V3 新增：3 区前台 + 结果 + 目标（步骤 5）
    needs_you: list[BriefTask] = Field(default_factory=list)  # 「现在需要你」— need_confirm + need_assist
    auto_doing: list[ParallelNote] = Field(default_factory=list)  # 「MealKey 正在做」— auto_handle
    results: list[BriefResult] = Field(default_factory=list)  # 「结果」— 实验结论
    goal_prompt: Optional[str] = None  # 永久入口：「你想让 MealKey 帮你做到什么？」
    active_goals: list[Any] = Field(default_factory=list)  # GoalView 列表
    deviation_alerts: list[Any] = Field(default_factory=list)  # 目标偏差提醒
    profit_summary: Optional[ProfitSummaryBrief] = None
    # V3：经营队列（交互单位）
    ops_queue: Optional[OpsQueueBrief] = None
    # V4：右栏 AI 主动经营流（POIE 六路径投影）
    proactive_feed: list[Any] = Field(default_factory=list)
