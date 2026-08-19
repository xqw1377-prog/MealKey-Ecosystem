"""GROWTH-PRIMITIVE-02 — Growth Action Primitive Registry。

蒸馏自 OfferKit（schema 架构）+ fuintCatering（真实餐饮营销业务模型）。

纪律：
- 这只是 Action Registry（结构化、受控、可归因的经营动作定义），
  不建 MealKey CRM Center / Coupon Platform / Loyalty SaaS。
- 每个 primitive 带 profit_guard / risk_level / permission / observation_window /
  attribution_method —— 全部走既有 Profit Gate → Risk → Permission 管道。
- fuintCatering 只做了业务模型研究，未复用任何代码（其商用需购买源码授权）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class GrowthActionPrimitive:
    """一条结构化增长动作原语。"""

    action_type: str
    # 目标人群（fuintCatering 业务模型蒸馏）
    target_segment: str  # SLEEPING / NEW / HIGH_VALUE / CHURN_RISK / COMPLAINED / ALL
    # 触达渠道
    channel: str  # SMS / WECHAT / PLATFORM_MESSAGE / IN_APP
    # 权益内容（OfferKit schema 蒸馏）
    offer_type: str  # COUPON / POINTS / REFERRAL / FREE_ITEM / DISCOUNT
    offer_value: Optional[float] = None
    # 资格条件
    eligibility: str = ""  # 例如 "last_order_days >= 30"
    # 成本与护栏
    est_cost_per_target: float = 0.0
    profit_guard: str = "require_positive_unit_economics"
    max_total_budget_cny: Optional[float] = None
    # 风险与权限（OfferKit risk metadata 对齐）
    risk_level: str = "mutating"  # safe / mutating / destructive
    permission: str = "ASK_APPROVAL"
    # 频控（防止骚扰）
    frequency_cap: str = "1x/30d/target"
    # 验证与归因
    observation_window_hours: int = 168
    attribution_method: str = "PRE_POST"  # PRE_POST / HOLDOUT / GEO
    incremental_success_metric: str = "incremental_orders"
    # 执行能力（与 permission 正交）：permission 回答"可以做吗"，capability 回答"能实际做吗"
    # NOT_IMPLEMENTED / OBSERVE_ONLY / IMPLEMENTED
    execution_capability: str = "NOT_IMPLEMENTED"

    @property
    def execution_status(self) -> str:
        """综合执行状态：permission 允许 + capability 未实现 → BLOCKED_NOT_IMPLEMENTED。"""
        if self.execution_capability == "NOT_IMPLEMENTED":
            return "BLOCKED_NOT_IMPLEMENTED"
        if self.execution_capability == "OBSERVE_ONLY":
            return "OBSERVE_ONLY"
        return f"READY_{self.permission}"


# ---------------------------------------------------------------------------
# Registry — 从 OfferKit + fuintCatering 蒸馏的原语集
# ---------------------------------------------------------------------------

GROWTH_PRIMITIVES: dict[str, GrowthActionPrimitive] = {
    # fuintCatering「沉睡唤醒」：last_order >= 30 天自动发券
    "REACTIVATE_SLEEPING_COUPON": GrowthActionPrimitive(
        action_type="REACTIVATE_SLEEPING_COUPON",
        target_segment="SLEEPING",
        channel="PLATFORM_MESSAGE",
        offer_type="COUPON",
        offer_value=5.0,
        eligibility="last_order_days >= 30 and lifetime_orders >= 2",
        est_cost_per_target=5.0,
        max_total_budget_cny=300.0,
        risk_level="mutating",
        permission="ASK_APPROVAL",
        frequency_cap="1x/30d/target",
        observation_window_hours=168,
        attribution_method="HOLDOUT",
        incremental_success_metric="incremental_orders",
    ),
    # fuintCatering「开卡礼」：新会员首单券
    "NEW_MEMBER_FIRST_ORDER_COUPON": GrowthActionPrimitive(
        action_type="NEW_MEMBER_FIRST_ORDER_COUPON",
        target_segment="NEW",
        channel="WECHAT",
        offer_type="COUPON",
        offer_value=8.0,
        eligibility="member_age_days <= 7 and first_order = false",
        est_cost_per_target=8.0,
        max_total_budget_cny=400.0,
        risk_level="mutating",
        permission="ASK_APPROVAL",
        frequency_cap="1x/lifetime/target",
        observation_window_hours=72,
        attribution_method="PRE_POST",
        incremental_success_metric="first_order_rate",
    ),
    # OfferKit Referral 模式
    "REFERRAL_BOTH_REWARD": GrowthActionPrimitive(
        action_type="REFERRAL_BOTH_REWARD",
        target_segment="HIGH_VALUE",
        channel="WECHAT",
        offer_type="REFERRAL",
        offer_value=10.0,
        eligibility="lifetime_orders >= 10 and avg_rating >= 4.5",
        est_cost_per_target=10.0,
        max_total_budget_cny=500.0,
        risk_level="mutating",
        permission="ASK_APPROVAL",
        frequency_cap="1x/90d/target",
        observation_window_hours=336,
        attribution_method="HOLDOUT",
        incremental_success_metric="referred_first_orders",
    ),
    # fuintCatering「积分」：复购积分加倍
    "LOYALTY_POINTS_MULTIPLIER": GrowthActionPrimitive(
        action_type="LOYALTY_POINTS_MULTIPLIER",
        target_segment="ALL",
        channel="IN_APP",
        offer_type="POINTS",
        eligibility="active_member = true",
        est_cost_per_target=0.5,
        profit_guard="points_liability_cap",
        max_total_budget_cny=200.0,
        risk_level="safe",
        permission="AUTO_AND_REPORT",
        frequency_cap="1x/campaign",
        observation_window_hours=168,
        attribution_method="PRE_POST",
        incremental_success_metric="repurchase_rate",
    ),
    # 投诉顾客修复（差评闭环 → 关系修复）
    "COMPLAINT_RECOVERY_COUPON": GrowthActionPrimitive(
        action_type="COMPLAINT_RECOVERY_COUPON",
        target_segment="COMPLAINED",
        channel="PLATFORM_MESSAGE",
        offer_type="COUPON",
        offer_value=6.0,
        eligibility="has_negative_review within 14d and not yet compensated",
        est_cost_per_target=6.0,
        max_total_budget_cny=200.0,
        risk_level="mutating",
        permission="ASK_APPROVAL",
        frequency_cap="1x/incident",
        observation_window_hours=336,
        attribution_method="PRE_POST",
        incremental_success_metric="reorder_after_complaint_rate",
    ),
    # 流失风险预警（只观察不打扰 — 无平台副作用 → OBSERVE_ONLY）
    "CHURN_RISK_WATCH": GrowthActionPrimitive(
        action_type="CHURN_RISK_WATCH",
        target_segment="CHURN_RISK",
        channel="IN_APP",
        offer_type="DISCOUNT",
        offer_value=0.0,
        eligibility="predicted_churn_prob >= 0.6",
        est_cost_per_target=0.0,
        risk_level="safe",
        permission="AUTO_AND_REPORT",
        frequency_cap="none",
        observation_window_hours=168,
        attribution_method="PRE_POST",
        incremental_success_metric="retained_customers",
        execution_capability="OBSERVE_ONLY",
    ),
}


def get_primitive(action_type: str) -> Optional[GrowthActionPrimitive]:
    return GROWTH_PRIMITIVES.get(action_type)


def list_primitives() -> list[dict]:
    return [vars(p) for p in GROWTH_PRIMITIVES.values()]


def primitives_for_segment(segment: str) -> list[GrowthActionPrimitive]:
    return [p for p in GROWTH_PRIMITIVES.values() if p.target_segment == segment or p.target_segment == "ALL"]


def check_budget_guard(action_type: str, target_count: int) -> dict:
    """预算护栏：超预算 → 拒绝执行，建议缩减目标人群。"""
    p = get_primitive(action_type)
    if p is None:
        return {"ok": False, "reason": "unknown primitive"}
    total_cost = p.est_cost_per_target * target_count
    if p.max_total_budget_cny and total_cost > p.max_total_budget_cny:
        max_targets = int(p.max_total_budget_cny / p.est_cost_per_target) if p.est_cost_per_target else 0
        return {
            "ok": False,
            "reason": f"budget exceeded: ¥{total_cost:.0f} > cap ¥{p.max_total_budget_cny:.0f}",
            "max_targets": max_targets,
        }
    return {"ok": True, "est_total_cost": round(total_cost, 2)}
