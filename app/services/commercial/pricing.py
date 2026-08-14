"""客户订阅报价：门店数优惠 × 购买周期优惠。没有券。"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.commercial.policy import (
    ANNUAL_MONTHS_PAID,
    ANNUAL_MONTHS_USED,
    QUARTERLY_MONTHS_PAID,
    QUARTERLY_MONTHS_USED,
    SUBSCRIPTION_FLOOR_CNY,
    volume_price,
)

CYCLE_ALIASES = {
    "annual": "annual",
    "year": "annual",
    "yearly": "annual",
    "quarterly": "quarterly",
    "quarter": "quarterly",
    "q": "quarterly",
    "monthly": "monthly",
    "month": "monthly",
}


def normalize_cycle(billing_cycle: str | None) -> str:
    raw = str(billing_cycle or "").strip().lower()
    return CYCLE_ALIASES.get(raw, "monthly")


@dataclass(frozen=True)
class SubscriptionQuote:
    active_stores: int
    billing_cycle: str
    unit_monthly_cny: float
    unit_quarterly_cny: float
    unit_annual_cny: float
    equiv_monthly_cny: float
    billed_cny: float
    paid_months: float
    used_months: int
    needs_approval: bool
    floor_cny: float = SUBSCRIPTION_FLOOR_CNY

    def as_dict(self) -> dict:
        commitment = self.billing_cycle in {"quarterly", "annual"}
        return {
            "active_stores": self.active_stores,
            "billing_cycle": self.billing_cycle,
            "unit_monthly_cny": self.unit_monthly_cny,
            "unit_quarterly_cny": self.unit_quarterly_cny,
            "unit_annual_cny": self.unit_annual_cny,
            "equiv_monthly_cny": self.equiv_monthly_cny,
            "billed_cny": self.billed_cny,
            "paid_months": self.paid_months,
            "used_months": self.used_months,
            "needs_approval": self.needs_approval,
            "floor_cny": self.floor_cny,
            "discounts": ["store_volume", "commitment"] if commitment else ["store_volume"],
        }


def quote_subscription(active_stores: int, billing_cycle: str = "monthly") -> SubscriptionQuote:
    cycle = normalize_cycle(billing_cycle)
    stores = max(int(active_stores or 0), 1)
    price = volume_price(stores)
    unit_quarterly = round(price.monthly_cny * QUARTERLY_MONTHS_PAID, 2)
    if cycle == "annual":
        paid_months = float(ANNUAL_MONTHS_PAID)
        used_months = ANNUAL_MONTHS_USED
        equiv = round(price.annual_cny / ANNUAL_MONTHS_USED, 2)
        billed = round(price.annual_cny * stores, 2)
    elif cycle == "quarterly":
        paid_months = float(QUARTERLY_MONTHS_PAID)
        used_months = QUARTERLY_MONTHS_USED
        equiv = round(unit_quarterly / QUARTERLY_MONTHS_USED, 2)
        billed = round(unit_quarterly * stores, 2)
    else:
        paid_months = 1.0
        used_months = 1
        equiv = price.monthly_cny
        billed = round(price.monthly_cny * stores, 2)
    return SubscriptionQuote(
        active_stores=stores,
        billing_cycle=cycle,
        unit_monthly_cny=price.monthly_cny,
        unit_quarterly_cny=unit_quarterly,
        unit_annual_cny=price.annual_cny,
        equiv_monthly_cny=equiv,
        billed_cny=billed,
        paid_months=paid_months,
        used_months=used_months,
        needs_approval=equiv + 1e-9 < SUBSCRIPTION_FLOOR_CNY,
    )


def collected_subscription_base(amount_cny: float, refunded_cny: float = 0.0) -> float:
    """合伙人计佣基数：到账基础经营费，扣退款。"""
    return round(max(float(amount_cny or 0) - float(refunded_cny or 0), 0.0), 2)


def annual_paid_months() -> tuple[int, int]:
    return ANNUAL_MONTHS_PAID, ANNUAL_MONTHS_USED
