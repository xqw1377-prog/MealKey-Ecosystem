"""AI 算力账：真实成本 × 1.30；预算控制但不突然停掉店长。"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.commercial.policy import (
    AI_MARKUP,
    AI_STORE_BUDGET_ACTUAL_CNY,
    AI_THROTTLE_RATIO,
    ACQUISITION_AUDIT_CAP_CNY,
    BASE_CASE_TOKENS_PER_STORE,
    CUSTOMER_BILL_CATEGORIES,
    FX_USD_CNY_BUDGET,
    MODEL_MIX,
    MODEL_USD_PER_M,
    TOKEN_CACHED_INPUT_SHARE,
    TOKEN_INPUT_SHARE,
)


@dataclass(frozen=True)
class AICharge:
    actual_cost_cny: float
    billed_cny: float
    markup: float = AI_MARKUP

    def as_dict(self) -> dict:
        return {
            "actual_cost_cny": self.actual_cost_cny,
            "billed_cny": self.billed_cny,
            "markup": self.markup,
        }


@dataclass(frozen=True)
class AIBudgetState:
    store_count: int
    used_actual_cny: float
    budget_actual_cny: float
    ratio: float
    state: str  # normal | throttle | cap_noncritical
    continue_high_value: bool = True

    def as_dict(self) -> dict:
        return {
            "store_count": self.store_count,
            "used_actual_cny": self.used_actual_cny,
            "budget_actual_cny": self.budget_actual_cny,
            "ratio": self.ratio,
            "state": self.state,
            "continue_high_value": self.continue_high_value,
        }


def charge_ai(actual_cost_cny: float) -> AICharge:
    actual = round(max(float(actual_cost_cny or 0), 0.0), 4)
    billed = round(actual * AI_MARKUP, 2)
    return AICharge(actual_cost_cny=round(actual, 2), billed_cny=billed)


def enterprise_budget_actual(store_count: int) -> float:
    return round(max(int(store_count or 0), 1) * AI_STORE_BUDGET_ACTUAL_CNY, 2)


def budget_state(used_actual_cny: float, store_count: int = 1) -> AIBudgetState:
    budget = enterprise_budget_actual(store_count)
    used = max(float(used_actual_cny or 0), 0.0)
    ratio = round(used / budget, 4) if budget else 0.0
    if ratio >= 1:
        state = "cap_noncritical"
    elif ratio >= AI_THROTTLE_RATIO:
        state = "throttle"
    else:
        state = "normal"
    return AIBudgetState(
        store_count=max(int(store_count or 0), 1),
        used_actual_cny=round(used, 2),
        budget_actual_cny=budget,
        ratio=ratio,
        state=state,
        continue_high_value=True,
    )


def acquisition_over_cap(actual_cost_cny: float) -> bool:
    return float(actual_cost_cny or 0) > ACQUISITION_AUDIT_CAP_CNY + 1e-9


def plan_token_cost_cny(raw_tokens: int = BASE_CASE_TOKENS_PER_STORE) -> dict:
    """规划模型：85% input / 15% output，50% input 缓存，Luna/Terra/Sol 负载。"""
    tokens = max(int(raw_tokens or 0), 0)
    input_tokens = tokens * TOKEN_INPUT_SHARE
    output_tokens = tokens * (1 - TOKEN_INPUT_SHARE)
    cached = input_tokens * TOKEN_CACHED_INPUT_SHARE
    fresh_input = input_tokens - cached
    usd = 0.0
    for tier, share in MODEL_MIX.items():
        in_p, cached_p, out_p = MODEL_USD_PER_M[tier]
        usd += share * (
            fresh_input / 1_000_000 * in_p
            + cached / 1_000_000 * cached_p
            + output_tokens / 1_000_000 * out_p
        )
    actual = round(usd * FX_USD_CNY_BUDGET, 2)
    billed = charge_ai(actual).billed_cny
    return {
        "raw_tokens": tokens,
        "actual_cost_cny": actual,
        "billed_cny": billed,
        "fx_usd_cny": FX_USD_CNY_BUDGET,
        "mix": dict(MODEL_MIX),
    }


def customer_bill_categories() -> tuple[str, ...]:
    return CUSTOMER_BILL_CATEGORIES
