"""Profit Gate: promo/ads/growth actions must pass contribution check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.schemas.store_state import ProfitState


@dataclass
class ProfitGateDecision:
    allowed: bool
    verdict: str
    reason: str
    projected_take_home_rate: Optional[float] = None
    projected_profit_per_order: Optional[float] = None
    order_lift_pct: Optional[float] = None


def evaluate_profit_gate(
    profit: ProfitState,
    *,
    action_type: str,
    expected_order_lift_pct: float,
    expected_take_home_rate_after: Optional[float] = None,
    min_take_home_rate: float = 0.58,
    min_profit_per_order: float = 3.5,
    system_mode: str = "operating",
    memory_veto: Optional[str] = None,
) -> ProfitGateDecision:
    """
    Example:
      orders +18% but take-home 64% → 57% => reject ("买流水不赚钱")

    system_mode="safe" 时，补贴/投流类动作一律禁止（MOS 未满足）。
    """
    current_thr = profit.take_home_rate
    current_ppo = profit.contribution_profit_per_order

    if memory_veto:
        return ProfitGateDecision(
            allowed=False,
            verdict="blocked_memory",
            reason=f"策略记忆否决：{memory_veto}",
            order_lift_pct=expected_order_lift_pct,
        )

    # Safe Mode：MOS 未满足时禁止利润相关动作
    if system_mode == "safe":
        from app.services.mos_engine import is_action_allowed_in_safe_mode

        if not is_action_allowed_in_safe_mode(action_type):
            return ProfitGateDecision(
                allowed=False,
                verdict="blocked_safe_mode",
                reason="系统处于 Safe Mode（关键经营信息未确认），暂不允许此动作。请先回答 AI 的几个基本问题。",
                order_lift_pct=expected_order_lift_pct,
            )

    # If no profit data, allow only low-risk non-spend actions.
    if profit.data_quality == "missing" or current_thr is None:
        if action_type in {"join_lunch_campaign", "match_competitor_promo", "boost_hero_item_ads", "store_discount"}:
            return ProfitGateDecision(
                allowed=False,
                verdict="blocked",
                reason="利润数据不足，暂不允许补贴/投流类动作。",
                order_lift_pct=expected_order_lift_pct,
            )
        return ProfitGateDecision(
            allowed=True,
            verdict="pass_limited",
            reason="利润数据不足，仅允许低成本优化动作。",
            order_lift_pct=expected_order_lift_pct,
        )

    projected_thr = expected_take_home_rate_after
    if projected_thr is None:
        # Heuristic: heavy promo/ads compress take-home.
        pressure = 0.0
        if action_type in {"join_lunch_campaign", "match_competitor_promo", "store_discount"}:
            pressure = 0.06 + max(0.0, expected_order_lift_pct) * 0.0015
        elif action_type in {"boost_hero_item_ads", "shift_ads_to_high_cvr_item"}:
            pressure = 0.03 + max(0.0, expected_order_lift_pct) * 0.001
        projected_thr = max(0.0, current_thr - pressure)

    projected_ppo = current_ppo
    if current_ppo is not None and projected_thr is not None and current_thr:
        projected_ppo = current_ppo * (projected_thr / current_thr)

    if projected_thr < min_take_home_rate and expected_order_lift_pct > 0:
        return ProfitGateDecision(
            allowed=False,
            verdict="reject_buy_gmv",
            reason=(
                f"不建议参加/投放：预计订单 +{expected_order_lift_pct:.0f}%，"
                f"但到手率 {current_thr:.0%} → {projected_thr:.0%}，更像买流水。"
            ),
            projected_take_home_rate=projected_thr,
            projected_profit_per_order=projected_ppo,
            order_lift_pct=expected_order_lift_pct,
        )

    if projected_ppo is not None and projected_ppo < min_profit_per_order and action_type in {
        "join_lunch_campaign",
        "match_competitor_promo",
        "boost_hero_item_ads",
        "store_discount",
    }:
        return ProfitGateDecision(
            allowed=False,
            verdict="reject_low_contribution",
            reason=(
                f"预计单均贡献利润过低（¥{projected_ppo:.1f} < ¥{min_profit_per_order:.1f}），先优化结构再冲量。"
            ),
            projected_take_home_rate=projected_thr,
            projected_profit_per_order=projected_ppo,
            order_lift_pct=expected_order_lift_pct,
        )

    return ProfitGateDecision(
        allowed=True,
        verdict="pass",
        reason="通过利润门禁：增长与到手率可同时接受。",
        projected_take_home_rate=projected_thr,
        projected_profit_per_order=projected_ppo,
        order_lift_pct=expected_order_lift_pct,
    )
