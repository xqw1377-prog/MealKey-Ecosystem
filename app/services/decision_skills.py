"""Decision Skills：Profit / Campaign 进入同一条 Closed Loop，不新增 UI 入口。"""

from __future__ import annotations

from typing import Optional

from app.schemas.decision_core import CampaignRule
from app.schemas.poie import CandidateAction
from app.schemas.store_state import StoreState
from app.services.decision_core import calculate_campaign, diagnose_profit_change
from app.services.poie.scoring import score_candidate


def profit_skill_candidates(state: StoreState | None) -> list[CandidateAction]:
    if state is None:
        return []
    profit = state.profit
    delta = profit.contribution_profit_delta_pct
    if delta is None or delta > -3:
        return []
    current, baseline = _profit_windows(profit)
    orders = state.business.orders
    diagnosis = diagnose_profit_change(
        current=current,
        baseline=baseline,
        orders_current=int(orders.observed_value) if orders and orders.observed_value else None,
        orders_baseline=int(orders.baseline_value) if orders and orders.baseline_value else None,
    )
    top = next((item for item in diagnosis.factors if item.is_primary), diagnosis.factors[0] if diagnosis.factors else None)
    title = _profit_title(top.factor if top else "", top.label if top else "利润")
    return [
        CandidateAction(
            id=f"skill:profit:{top.factor if top else 'profit'}",
            title=title,
            trigger="anomaly",
            insight=diagnosis.conclusion or profit.judgment or "利润变差，先处理主因。",
            why_now=f"利润较基线 {delta:.1f}%。{diagnosis.primary_cause}",
            already_did="已完成利润八因子拆解，不靠感觉猜。",
            success_metric="贡献利润止跌",
            interrupt_reason="anomaly",
            suggested_state="confirm",
            score=score_candidate(
                business_impact=0.82,
                urgency=0.7,
                confidence=max(0.5, diagnosis.confidence),
                need_for_human=0.7,
                goal_relevance=0.75,
                interruption_cost=0.4,
            ),
        )
    ]


def campaign_skill_candidates(
    state: StoreState | None,
    *,
    sku_price: float | None = None,
    rule: CampaignRule | None = None,
) -> list[CandidateAction]:
    if state is None:
        return []
    profit = state.profit
    price = sku_price or _hero_price(state)
    if price is None:
        return []
    campaign_rule = rule or CampaignRule(
        campaign_name="平台满减活动",
        discount_type="amount",
        discount_value=5,
        platform_bears=2,
        merchant_bears=3,
        applicable_time="11:00-13:00",
    )
    orders = state.business.orders
    decision = calculate_campaign(
        campaign_rule,
        sku_price=price,
        food_cost=profit.food_cost,
        packaging_cost=profit.packaging_cost,
        avg_daily_orders=int(orders.observed_value or 80) if orders else 80,
    )
    if decision.verdict in {"BLACK", "RED"}:
        return [
            CandidateAction(
                id="skill:campaign:hold",
                title="这次活动先别参加",
                trigger="opportunity",
                insight=decision.reasoning,
                why_now="算完账以后，参加会伤利润或数据不够，不能当今天的 Now。",
                already_did="已用活动决策引擎算过单均利润和利润率底线。",
                success_metric="利润率不低于底线",
                interrupt_reason="opportunity",
                suggested_state="auto_do",
                score=score_candidate(
                    business_impact=0.55,
                    urgency=0.4,
                    confidence=max(0.5, decision.confidence or 0.7),
                    need_for_human=0.15,
                    goal_relevance=0.6,
                    interruption_cost=0.35,
                ),
            )
        ]
    if decision.verdict in {"GREEN", "YELLOW"}:
        return [
            CandidateAction(
                id=f"skill:campaign:{decision.verdict.lower()}",
                title="限量参加这档活动" if decision.verdict == "YELLOW" else "可以参加这档活动",
                trigger="opportunity",
                insight=decision.reasoning,
                why_now=decision.strategy or "活动测算已通过利润底线。",
                already_did="已完成活动测算，并核对叠加和产能。",
                success_metric="订单上升且利润率不破线",
                interrupt_reason="opportunity",
                suggested_state="confirm",
                score=score_candidate(
                    business_impact=0.7 if decision.verdict == "GREEN" else 0.58,
                    urgency=0.55,
                    confidence=decision.confidence or 0.7,
                    need_for_human=0.65,
                    goal_relevance=0.6,
                    interruption_cost=0.5,
                ),
            )
        ]
    return []


def collect_decision_skill_candidates(state: StoreState | None) -> list[CandidateAction]:
    out: list[CandidateAction] = []
    out.extend(profit_skill_candidates(state))
    out.extend(campaign_skill_candidates(state))
    return out


def _profit_windows(profit) -> tuple[dict[str, float | None], dict[str, float | None]]:
    current = {
        "customer_paid": profit.customer_paid,
        "platform_commission": profit.platform_commission,
        "merchant_subsidy": profit.merchant_subsidy,
        "food_cost": profit.food_cost,
        "packaging_cost": profit.packaging_cost,
        "ads_spend": profit.ads_spend,
        "refund_cost": profit.refund_cost,
    }
    factor = 1.0
    if profit.contribution_profit_delta_pct not in (None, 0, -100):
        denom = 1.0 + (profit.contribution_profit_delta_pct / 100.0)
        if denom != 0:
            factor = 1.0 / denom
    baseline = {
        key: (value * factor if isinstance(value, (int, float)) else value) for key, value in current.items()
    }
    return current, baseline


def _profit_title(factor: str, label: str) -> str:
    if factor in {"merchant_subsidy", "ads_spend"}:
        return "先换主图，不要再叠优惠或加投"
    if factor == "customer_paid":
        return "先改标题把价值说清楚"
    if factor in {"food_cost", "packaging_cost"}:
        return "先核对成本和包装，再决定活动"
    return f"利润下滑，先处理{label}"


def _hero_price(state: StoreState) -> Optional[float]:
    if isinstance(state.profit.customer_paid, (int, float)) and state.profit.customer_paid > 0:
        return float(state.profit.customer_paid)
    return None
