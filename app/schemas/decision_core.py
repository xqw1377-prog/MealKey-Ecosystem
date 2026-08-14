"""Decision Core V1 — MealKey 真正能算账、做判断、承担后果的经营能力。

5 个交付物：
1. Canonical Profit Calculator — 统一算钱，每个数字有 source+confidence，缺失=UNKNOWN 不猜
2. Campaign Decision Engine — 活动测算 + GREEN/YELLOW/RED/BLACK 分档
3. Profit Diagnosis — 利润变差的归因拆解（订单/客单/补贴/佣金/广告/成本/退款）
4. ODO → Action → Experiment → Result 闭环接线
5. Fixture Test Set — 30-50 个经营案例
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════
# 1. Canonical Profit Calculator
# ═══════════════════════════════════════════════════════════


class MoneyItem(BaseModel):
    """一个钱的数据项——值 + 来源 + 置信度。缺失时 value=None。"""
    value: Optional[float] = None
    source: Literal["platform", "merchant_input", "estimated", "missing"] = "missing"
    confidence: float = 0.0  # 0=完全不确定, 1=平台直连确认


class ProfitBreakdown(BaseModel):
    """单笔订单或某时间段的利润拆解。

    Missing Data 是一等状态：food_cost/packaging_cost 缺失时 value=None，
    绝不 AI 猜一个数字。
    """
    # 收入侧
    customer_paid: MoneyItem = Field(default_factory=MoneyItem)  # 顾客实付
    platform_subsidy: MoneyItem = Field(default_factory=MoneyItem)  # 平台补贴
    original_price: MoneyItem = Field(default_factory=MoneyItem)  # 原价

    # 成本侧
    platform_commission: MoneyItem = Field(default_factory=MoneyItem)  # 平台佣金
    merchant_subsidy: MoneyItem = Field(default_factory=MoneyItem)  # 商家承担优惠
    delivery_fee_borne: MoneyItem = Field(default_factory=MoneyItem)  # 商家承担配送费
    food_cost: MoneyItem = Field(default_factory=MoneyItem)  # 食材成本
    packaging_cost: MoneyItem = Field(default_factory=MoneyItem)  # 包装成本
    ads_allocation: MoneyItem = Field(default_factory=MoneyItem)  # 广告分摊
    refund_compensation: MoneyItem = Field(default_factory=MoneyItem)  # 退款/赔付分摊

    # 计算结果
    merchant_revenue: Optional[float] = None  # 商家实收 = 顾客实付 + 平台补贴 - 平台佣金 - 商家补贴 - 配送
    contribution_profit: Optional[float] = None  # 贡献利润 = 实收 - 食材 - 包装 - 广告 - 退款
    contribution_margin: Optional[float] = None  # 贡献利润率 = 贡献利润 / 顾客实付
    take_home_rate: Optional[float] = None  # 到手率 = 商家实收 / 顾客实付
    profit_per_order: Optional[float] = None  # 单均贡献利润

    # 数据完整性
    has_critical_missing: bool = False  # 食材/包装缺失 → 无法安全判断
    missing_fields: list[str] = Field(default_factory=list)


class ProfitCalcResult(BaseModel):
    """利润计算结果。"""
    breakdown: ProfitBreakdown
    orders: int = 0
    total_gmv: Optional[float] = None
    total_contribution_profit: Optional[float] = None
    safe_to_decide: bool = False  # has_critical_missing=False 时才 True
    warning: str = ""


# ═══════════════════════════════════════════════════════════
# 2. Campaign Decision Engine
# ═══════════════════════════════════════════════════════════


CampaignVerdict = Literal["GREEN", "YELLOW", "RED", "BLACK"]


class CampaignRule(BaseModel):
    """平台活动规则。"""
    campaign_name: str = ""
    platform: str = "meituan"  # meituan / eleme
    campaign_type: str = ""  # lunch_subsidy / discount / full_reduction / coupon
    platform_bears: float = 0.0  # 平台每单承担
    merchant_bears: float = 0.0  # 商家每单承担
    discount_type: Literal["amount", "percentage"] = "amount"
    discount_value: float = 0.0
    min_order_value: Optional[float] = None  # 满减门槛
    applicable_time: str = ""  # "11:00-13:00"
    applicable_days: int = 1  # 持续天数
    max_orders: Optional[int] = None  # 限量


class CampaignOverlay(BaseModel):
    """活动叠加检查——店内现有优惠 + 新活动的叠加效果。"""
    existing_discounts: list[dict[str, Any]] = Field(default_factory=list)
    has_overlap: bool = False
    overlap_detail: str = ""


class CampaignCalcResult(BaseModel):
    """活动测算结果。"""
    # 叠加后的价格
    final_customer_price: Optional[float] = None
    final_merchant_revenue: Optional[float] = None
    merchant_bears_per_order: Optional[float] = None  # 商家每单承担总额
    # 利润
    profit_per_order_with_campaign: Optional[float] = None
    profit_per_order_without_campaign: Optional[float] = None  # 对比基准
    profit_delta_per_order: Optional[float] = None  # 有活动 vs 无活动
    # 预估量
    expected_order_lift_pct: Optional[float] = None
    expected_total_orders: Optional[int] = None
    expected_total_profit_delta: Optional[float] = None
    # 碗均价影响
    avg_price_impact: Optional[float] = None  # 活动后的碗均价变化
    # 产能
    capacity_risk: Literal["none", "moderate", "severe"] = "none"
    # 风险
    take_home_rate_after: Optional[float] = None
    profit_floor: Optional[float] = None
    safe_margin_maintained: bool = False
    # 缺失数据
    missing_data: list[str] = Field(default_factory=list)


class CampaignDecision(BaseModel):
    """活动决策结果——GREEN/YELLOW/RED/BLACK + 具体策略。"""
    verdict: CampaignVerdict
    strategy: str = ""  # 具体策略文本
    # YELLOW 时的限定条件
    scope: Optional[str] = None  # "仅国贸店、午餐、黑椒牛肉饭"
    test_duration_days: Optional[int] = None
    test_max_orders: Optional[int] = None
    guardrail_metrics: list[str] = Field(default_factory=list)  # ["碗均价", "CVR", "差评率"]
    stop_conditions: list[str] = Field(default_factory=list)  # ["如果贡献利润率 <17% 则停止"]
    # 计算
    calc: CampaignCalcResult = Field(default_factory=CampaignCalcResult)
    # 可解释性
    reasoning: str = ""
    confidence: float = 0.7


# ═══════════════════════════════════════════════════════════
# 3. Profit Diagnosis
# ═══════════════════════════════════════════════════════════


class ProfitFactorContribution(BaseModel):
    """利润归因的一个贡献因子。"""
    factor: str  # order_volume / avg_price / merchant_subsidy / commission / ads / food_cost / packaging / refund
    label: str  # 订单量 / 碗均价 / 商家补贴 / 平台佣金 / 广告 / 食材 / 包装 / 退款
    delta: float = 0.0  # 该因子的变化金额（正=增加了利润，负=减少了利润）
    delta_pct: Optional[float] = None
    is_primary: bool = False  # 最大的贡献因子


class ProfitDiagnosisResult(BaseModel):
    """利润诊断结果——回答"为什么利润变差"。"""
    total_profit_delta: float = 0.0  # 总利润变化（负=变差）
    total_profit_delta_pct: Optional[float] = None
    factors: list[ProfitFactorContribution] = Field(default_factory=list)
    primary_cause: str = ""  # "主要是广告成本增加 ¥800 导致利润下降"
    conclusion: str = ""  # "利润下降不是因为订单少，而是广告花了更多钱"
    confidence: float = 0.7
    missing_data: list[str] = Field(default_factory=list)
