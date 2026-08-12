"""Ask Engine — 什么时候才允许问老板（Content Engine V1 §06）。

核心原则：不知道这个答案，会明显影响一个值得做的决策，才应该出现。

AskScore = DecisionImpact × Uncertainty × Urgency × HumanUniqueness ÷ InterruptionCost

- DecisionImpact: 这个信息缺失对当前决策的影响（0-1）
- Uncertainty: AI 当前的不确定度（1-confidence，0-1）
- Urgency: 决策紧迫度（0-1）
- HumanUniqueness: 只有老板才知道的程度（0=AI能推断，1=只有老板知道）
- InterruptionCost: 打扰老板的成本（0-1，越高越不该问）

低于阈值的不问。
"""

from __future__ import annotations

from typing import Any

# HumanUniqueness 预设值：只有老板才知道的信息
_HUMAN_UNIQUENESS: dict[str, float] = {
    "priority_style": 1.0,       # 只有老板知道自己要什么
    "profit_floor": 0.95,        # 只有老板知道底线
    "hero_item_floor_price": 0.9,  # 只有老板知道真实成本
    "ads_daily_budget": 0.85,    # 只有老板知道愿意花多少
    "lunch_capacity": 0.8,       # 只有老板知道厨房极限
    "low_risk_auto": 0.7,        # 权限，需要老板授权
    "weekend_strategy": 0.6,     # 老板偏好，但 AI 可以默认
    "competitor_focus": 0.5,     # 老板直觉，但 AI 也能从数据推
    # 以下 AI 可以自己知道，HumanUniqueness 很低
    "audience": 0.15,            # AI 能从订单时间推断
    "hero_sku": 0.1,             # AI 能从销量算
    "avg_price": 0.05,           # AI 能从菜单算
}

# 默认不打扰阈值
_ASK_THRESHOLD = 0.15


def compute_ask_score(
    *,
    field_key: str,
    decision_impact: float = 0.5,
    confidence: float = 0.5,
    urgency: float = 0.5,
    interruption_cost: float = 0.5,
) -> float:
    """计算一个信息缺失时的提问优先级。

    返回 0-1 的 ask_score。低于 _ASK_THRESHOLD 的不问。
    """
    human_uniqueness = _HUMAN_UNIQUENESS.get(field_key, 0.3)
    uncertainty = max(0.0, 1.0 - confidence)  # 不确定度 = 1 - 置信度

    cost = max(0.15, interruption_cost)
    raw = (
        decision_impact
        * uncertainty
        * urgency
        * human_uniqueness
    ) / cost

    return round(min(1.0, max(0.0, raw)), 3)


def should_ask(
    *,
    field_key: str,
    decision_impact: float = 0.5,
    confidence: float = 0.5,
    urgency: float = 0.5,
    interruption_cost: float = 0.5,
    threshold: float = _ASK_THRESHOLD,
) -> tuple[bool, float]:
    """判断是否应该问老板某个信息。

    返回 (should_ask, ask_score)。
    """
    score = compute_ask_score(
        field_key=field_key,
        decision_impact=decision_impact,
        confidence=confidence,
        urgency=urgency,
        interruption_cost=interruption_cost,
    )
    return (score >= threshold, score)


def rank_gaps_by_ask_score(
    gaps: list[str],
    *,
    current_confidence: dict[str, float] | None = None,
    urgency: float = 0.5,
) -> list[tuple[str, float]]:
    """给一批缺口按 ask_score 排序，返回 [(key, score), ...] 降序。

    用于 POIE trigger_understanding 按提问优先级排序缺口。
    """
    confidence = current_confidence or {}
    scored = []
    for key in gaps:
        score = compute_ask_score(
            field_key=key,
            decision_impact=0.7,  # 缺口默认中等影响
            confidence=confidence.get(key, 0.3),  # 默认低置信度
            urgency=urgency,
            interruption_cost=0.4,
        )
        scored.append((key, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def clean_expired_context_facts(facts: list[Any]) -> list[Any]:
    """清理过期的 ContextFact（Content Engine V1 §04）。

    过了 valid_until 的自动失效。
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    active = []
    for fact in facts:
        valid_until = getattr(fact, "valid_until", None)
        if valid_until:
            try:
                expiry = datetime.fromisoformat(valid_until)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= now:
                    continue  # 过期了，跳过
            except Exception:  # noqa: BLE001
                pass  # 解析失败不丢弃
        active.append(fact)
    return active
