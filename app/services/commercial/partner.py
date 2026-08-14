"""合伙人计佣：单层直销；只分到账基础经营订阅。"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.commercial.policy import (
    BONUS_CONFIRM_DAYS,
    PARTNER_Y1_BASE,
    QUALIFY_DAYS,
    lifecycle_partner_rate,
    y1_partner_rate,
)
from app.services.commercial.pricing import collected_subscription_base


class CommissionDenied(ValueError):
    pass


@dataclass(frozen=True)
class CommissionSplit:
    subscription_base_cny: float
    y1_rate: float
    lifecycle_rate: float
    monthly_base_cny: float
    performance_accrual_cny: float
    payable_now_cny: float
    partner_cny: float
    mealkey_cny: float
    thirty_day_qualified: int = 0
    ninety_day_qualified: int = 0
    potential_y1_rate: float = 0.50

    def as_dict(self) -> dict:
        return {
            "subscription_base_cny": self.subscription_base_cny,
            "y1_rate": self.y1_rate,
            "lifecycle_rate": self.lifecycle_rate,
            "monthly_base_cny": self.monthly_base_cny,
            "performance_accrual_cny": self.performance_accrual_cny,
            "payable_now_cny": self.payable_now_cny,
            "partner_cny": self.partner_cny,
            "mealkey_cny": self.mealkey_cny,
            "thirty_day_qualified": self.thirty_day_qualified,
            "ninety_day_qualified": self.ninety_day_qualified,
            "potential_y1_rate": self.potential_y1_rate,
        }


def requires_service_qualification(y1_rate: float) -> bool:
    """65% / 70% 需要能做 Onboarding 和一线客户成功。"""
    return float(y1_rate) + 1e-9 >= 0.65


def assert_direct_only(*, upline_partner_id: str | None = None) -> None:
    if upline_partner_id:
        raise CommissionDenied("MealKey 只认 Partner → 直接客户，不给上线抽成。")


def assert_not_self_deal(*, license_kind: str, owner_partner_id: str | None, earning_partner_id: str) -> None:
    if license_kind == "owned":
        raise CommissionDenied("自有门店不产生合伙人返佣。")
    if owner_partner_id and owner_partner_id == earning_partner_id:
        raise CommissionDenied("同一家店不能既享受客户折扣又自返佣。")


def is_new_qualified(*, paid: bool, refunded: bool, activated: bool, days_active: int) -> bool:
    return bool(paid and activated and not refunded and int(days_active or 0) >= QUALIFY_DAYS)


def is_bonus_confirmed(*, paid: bool, refunded: bool, activated: bool, days_active: int) -> bool:
    return bool(paid and activated and not refunded and int(days_active or 0) >= BONUS_CONFIRM_DAYS)


def is_90_day_qualified(*, paid: bool, refunded: bool, activated: bool, days_active: int) -> bool:
    """90-Day Qualified Store：档位奖励只认还在付费、还在活跃的店。"""
    return is_bonus_confirmed(paid=paid, refunded=refunded, activated=activated, days_active=days_active)


def true_up_y1_rate(previous_qualified: int, new_qualified: int) -> tuple[float, float, bool]:
    """年度新增达标后，该年全部新增 Cohort 的首年分润追溯到新档。"""
    old_rate = y1_partner_rate(previous_qualified)
    new_rate = y1_partner_rate(new_qualified)
    return old_rate, new_rate, new_rate > old_rate + 1e-9


def split_commission(
    *,
    collected_cny: float,
    refunded_cny: float = 0.0,
    new_qualified_stores: int,
    months_since_first_paid: int,
    include_ai_cny: float = 0.0,
    ninety_day_qualified_stores: int = 0,
) -> CommissionSplit:
    """Y1：50% 基础可按 30 天有效店结算；+5%～20% 只按 90 天有效店解锁。

    拉来 300 家一个月全退，拿不到 70%。AI 算力永远不分润。
    """
    if include_ai_cny:
        raise CommissionDenied("合伙人绝对不参与 AI 算力分成。")
    base = collected_subscription_base(collected_cny, refunded_cny)
    potential = y1_partner_rate(new_qualified_stores)
    confirmed = y1_partner_rate(ninety_day_qualified_stores)
    y1 = confirmed
    life = lifecycle_partner_rate(months_since_first_paid, y1)
    partner = round(base * life, 2)
    monthly_base = round(base * PARTNER_Y1_BASE, 2) if months_since_first_paid < 12 else partner
    accrual = round(max(partner - monthly_base, 0.0), 2) if months_since_first_paid < 12 else 0.0
    payable_now = monthly_base if months_since_first_paid < 12 else partner
    return CommissionSplit(
        subscription_base_cny=base,
        y1_rate=y1,
        lifecycle_rate=life,
        monthly_base_cny=monthly_base,
        performance_accrual_cny=accrual,
        payable_now_cny=payable_now,
        partner_cny=partner,
        mealkey_cny=round(base - partner, 2),
        thirty_day_qualified=int(new_qualified_stores or 0),
        ninety_day_qualified=int(ninety_day_qualified_stores or 0),
        potential_y1_rate=potential,
    )


def true_up_amount(*, subscription_base_cny: float, from_rate: float, to_rate: float) -> float:
    if to_rate <= from_rate:
        return 0.0
    return round(float(subscription_base_cny) * (to_rate - from_rate), 2)


def four_year_economics(annual_subscription_cny: float, y1_rate: float) -> dict:
    years = [
        ("Y1", y1_rate),
        ("Y2", 0.30),
        ("Y3", 0.20),
        ("Y4+", 0.10),
    ]
    rows = []
    partner_total = 0.0
    mealkey_total = 0.0
    for label, rate in years:
        partner = round(annual_subscription_cny * rate, 2)
        mealkey = round(annual_subscription_cny - partner, 2)
        partner_total += partner
        mealkey_total += mealkey
        rows.append(
            {
                "year": label,
                "rate": rate,
                "partner_cny": partner,
                "mealkey_cny": mealkey,
            }
        )
    return {
        "annual_subscription_cny": annual_subscription_cny,
        "years": rows,
        "partner_total_cny": round(partner_total, 2),
        "mealkey_total_cny": round(mealkey_total, 2),
        "mealkey_share": round(mealkey_total / (annual_subscription_cny * 4), 4) if annual_subscription_cny else 0,
    }
