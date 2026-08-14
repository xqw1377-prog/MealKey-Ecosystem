"""把实验 Result 变成下一次行动的定量排序。

Memory 不能只是经验仓库。一次有效的换图，必须能把
「换图 / 换标题 / 降价 / 加投」的相对优先级改掉。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from app.schemas.strategy_memory import StrategyMemoryItem, StrategyMemorySnapshot

FAMILIES: dict[str, set[str]] = {
    "creative": {
        "change_main_image",
        "change_title",
        "refresh_hero_image",
        "refresh_signature_card",
    },
    "price": {
        "adjust_price_value",
        "store_discount",
        "launch_value_bundle_promo",
        "join_lunch_campaign",
        "match_competitor_promo",
    },
    "ads": {
        "boost_hero_item_ads",
        "shift_ads_to_high_cvr_item",
        "pause_broad_ads",
    },
    "reputation": {
        "batch_reply_negative_reviews",
        "reply_ordinary_reviews",
        "fix_top_review_theme",
        "pin_positive_review_themes",
        "reply_rating_critical_reviews",
    },
}


def family_of(action_type: str) -> str:
    for name, members in FAMILIES.items():
        if action_type in members:
            return name
    return "other"


def memory_delta_for_action(
    action_type: str,
    memory: StrategyMemorySnapshot | None,
    *,
    metric: str | None = None,
) -> float:
    """返回加在 0–1 优先级上的增量。"""
    if memory is None or not memory.items:
        return 0.0
    delta = 0.0
    for index, item in enumerate(memory.items[:8]):
        recency = 1.0 if index == 0 else max(0.35, 0.85**index)
        weight = recency * max(0.4, min(1.0, item.confidence or 0.7))
        lift = abs(item.lift_pct or 0.0)
        same = item.action_type == action_type
        learned_family = family_of(item.action_type)
        action_family = family_of(action_type)
        metric_match = True
        if metric and item.context_tags:
            metric_match = metric in item.context_tags or any(
                tag in {metric, "ctr", "cvr", "orders", "rating"} for tag in item.context_tags
            )
        if same:
            if item.result == "positive":
                delta += min(0.28, 0.12 + 0.007 * min(lift, 20.0)) * (weight / 0.72)
            elif item.result == "negative":
                delta -= min(0.30, 0.14 + 0.006 * min(lift, 20.0)) * (weight / 0.64)
            elif item.result == "neutral":
                delta -= 0.05 * recency
        elif learned_family == action_family and action_family != "other":
            if item.result == "positive":
                delta += 0.07 * recency
            elif item.result == "negative":
                delta -= 0.05 * recency
        elif learned_family == "creative" and action_family in {"price", "ads"} and item.result == "positive":
            delta -= (0.17 if action_family == "price" else 0.13) * recency
        elif learned_family in {"price", "ads"} and action_family == "creative" and item.result == "negative":
            delta += 0.08 * recency
        if not metric_match and same:
            delta *= 0.85
    return round(max(-0.40, min(0.32, delta)), 4)


def apply_memory_to_scores(
    candidates: Iterable[dict[str, Any]],
    memory: StrategyMemorySnapshot | None,
    *,
    metric: str | None = None,
) -> list[dict[str, Any]]:
    """candidates: {action_type, score}，score 为 0–1。返回按 final 降序的新列表。"""
    ranked: list[dict[str, Any]] = []
    for row in candidates:
        action_type = str(row.get("action_type") or "")
        base = float(row.get("score") or 0.0)
        delta = memory_delta_for_action(action_type, memory, metric=metric)
        final = max(0.0, min(1.0, round(base + delta, 2)))
        ranked.append({**row, "base_score": base, "memory_delta": delta, "score": final})
    ranked.sort(key=lambda item: (-float(item["score"]), str(item.get("action_type") or "")))
    return ranked


def apply_memory_to_growth_pool(pool: list[Any], memory: StrategyMemorySnapshot | None) -> list[Any]:
    """把 0–100 的 growth score 按 memory 重排。"""
    if not pool:
        return pool
    adjusted = []
    for row in pool:
        base = max(0.0, min(1.0, float(getattr(row, "score", 0.0) or 0.0) / 100.0))
        delta = memory_delta_for_action(getattr(row, "action_type", ""), memory)
        final = max(0.0, min(1.0, base + delta))
        update = {"score": round(final * 100.0, 1)}
        if hasattr(row, "model_copy"):
            adjusted.append(row.model_copy(update=update))
        else:
            row.score = update["score"]
            adjusted.append(row)
    adjusted.sort(key=lambda item: (-float(getattr(item, "score", 0.0) or 0.0), family_of(getattr(item, "action_type", ""))))
    return adjusted


def memory_from_result(
    *,
    action_type: str,
    result: str,
    lift_pct: float | None,
    confidence: float = 0.72,
    metric: str = "ctr",
) -> StrategyMemorySnapshot:
    """测试/桥接用：一条 Result 直接变成可排序的 Memory。"""
    from datetime import datetime, timezone

    item = StrategyMemoryItem(
        id="mem-result",
        store_id="s",
        action_type=action_type,
        context_tags=["effective" if result == "positive" else result, metric, action_type],
        result=result,  # type: ignore[arg-type]
        lift_pct=lift_pct,
        lesson=f"{action_type} {result}",
        reuse_when="同类指标压力时优先复用",
        avoid_when=None,
        confidence=confidence,
        created_at=datetime.now(timezone.utc),
    )
    return StrategyMemorySnapshot(store_id="s", items=[item], positive_patterns=[item.lesson] if result == "positive" else [])
