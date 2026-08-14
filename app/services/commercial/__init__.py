"""MealKey Commercial OS V1 门面：客户账单 = 经营订阅 + AI 算力。"""

from __future__ import annotations

from app.services.commercial.ai_ledger import charge_ai, plan_token_cost_cny
from app.services.commercial.partner import four_year_economics, split_commission
from app.services.commercial.policy import policy_snapshot
from app.services.commercial.pricing import quote_subscription


def customer_bill(
    *,
    active_stores: int,
    billing_cycle: str = "monthly",
    ai_actual_cny: float | None = None,
    tokens_per_store: int | None = None,
) -> dict:
    sub = quote_subscription(active_stores, billing_cycle)
    period = {"annual": "year", "quarterly": "quarter"}.get(sub.billing_cycle, "month")
    ai_months = {"year": 12, "quarter": 3}.get(period, 1)
    if ai_actual_cny is None:
        planned = plan_token_cost_cny(tokens_per_store) if tokens_per_store else plan_token_cost_cny()
        monthly_ai = planned["actual_cost_cny"] * sub.active_stores
        ai_actual = monthly_ai * ai_months
        ai_plan = planned
    else:
        ai_actual = float(ai_actual_cny)
        ai_plan = None
    ai_charge = charge_ai(ai_actual)
    return {
        "period": period,
        "subscription": sub.as_dict(),
        "ai": ai_charge.as_dict(),
        "ai_plan_per_store": ai_plan,
        "total_cny": round(sub.billed_cny + ai_charge.billed_cny, 2),
        "customer_sees": ["经营服务费", "AI算力费"],
        "customer_does_not_see": ["token", "agent套餐", "功能等级", "会员等级"],
    }


def partner_year_one_story(
    new_qualified_stores: int,
    annual_subscription_cny: float = 3000.0,
    ninety_day_qualified_stores: int = 0,
) -> dict:
    split = split_commission(
        collected_cny=annual_subscription_cny,
        new_qualified_stores=new_qualified_stores,
        ninety_day_qualified_stores=ninety_day_qualified_stores,
        months_since_first_paid=0,
    )
    return {
        "headline": "首年基础分润 50% 先结；+5%～20% 要门店活过 90 天。最高 70%。AI 算力不分润。",
        "split": split.as_dict(),
        "four_year": four_year_economics(annual_subscription_cny, split.y1_rate),
        "policy": policy_snapshot(),
    }
