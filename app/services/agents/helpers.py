from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.entities import ItemFunnelDaily
from app.models.ohre import Experiment, Recommendation
from app.services.truth_resolution import production_funnel_clause
from app.schemas.agents import AgentKey, AgentMeta

from .constants import AGENT_LABELS

def _json_loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []

def _json_loads_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}

def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _recommendation_in_observation(
    rec: Recommendation,
    experiment: Experiment | None,
    generated_at: datetime,
) -> tuple[bool, datetime | None]:
    event_at = _as_utc(rec.executed_at or rec.adopted_at or rec.created_at)
    if rec.status != "executed" or event_at is None:
        return False, event_at
    observe_until = event_at + timedelta(hours=rec.window_hours or 168)
    return observe_until >= generated_at and (experiment is None or experiment.result in {None, "pending"}), event_at

def _metric_label(metric: str) -> str:
    labels = {
        "gmv": "成交额",
        "orders": "订单",
        "impressions": "曝光",
        "ctr": "点击率",
        "cvr": "转化率",
    }
    return labels.get(metric, metric)

def _problem_summary(problem_type: str | None) -> str:
    mapping = {
        "store_ctr_down": "昨天的核心问题不是流量塌了，而是第一眼吸引力不足。",
        "store_cvr_down": "昨天的核心问题不是没人看，而是看完没有下单。",
    }
    return mapping.get(problem_type, "当前主要问题还需要更多证据来收敛。")

def _recommendation_title(action_type: str) -> str:
    mapping = {
        "change_main_image": "先换主图，抢回第一眼点击",
        "change_title": "重写标题，把卖点和价格感知说清",
        "add_set_meal": "补一组套餐，承接犹豫用户",
        "adjust_price_value": "优化价格锚点和价值表达",
        "menu_cleanup": "执行低效 SKU 清理",
        "menu_patch": "执行菜单结构修正",
        "store_discount": "只在必要时做门店折扣测试",
    }
    return mapping.get(action_type, action_type)

def _recommendation_summary(action_type: str) -> str:
    mapping = {
        "change_main_image": "低风险、可逆、最适合先验证 CTR。",
        "change_title": "适合在不改价格的前提下提升点击吸引力。",
        "add_set_meal": "更适合解决 CVR 和凑单承接问题。",
        "adjust_price_value": "先校准价格感知，不直接进入全店降价。",
        "menu_cleanup": "对低效 SKU 做停用测试，验证菜单收敛后能否改善整体承接。",
        "menu_patch": "把菜单结构问题落成具体修正动作，并进入后续观察窗。",
        "store_discount": "高冲击但高风险，优先级应低于图文和套餐。",
    }
    return mapping.get(action_type, "把建议收敛成一条可以验证的动作。")

def _recommendation_priority(rec: Recommendation) -> float:
    lift = float(rec.expected_lift_pct_high or rec.expected_lift_pct_low or 5)
    confidence = float(rec.confidence or 0.5)
    scope_bonus = 1.15 if rec.object_ref.startswith("item:") else 0.92
    action_bias = {
        "change_main_image": 1.20,
        "change_title": 1.08,
        "add_set_meal": 1.0,
        "adjust_price_value": 0.92,
        "menu_patch": 0.95,
        "menu_cleanup": 0.82,
        "store_discount": 0.55,
    }.get(rec.action_type, 0.9)
    return lift * confidence * scope_bonus * action_bias

def _sum_item_window(db: Session, item_id: str, from_day, to_day) -> dict[str, float]:
    stmt = (
        select(
            func.sum(ItemFunnelDaily.orders).label("orders"),
            func.sum(ItemFunnelDaily.gmv).label("gmv"),
            func.sum(ItemFunnelDaily.impressions).label("impressions"),
            func.sum(ItemFunnelDaily.visits).label("visits"),
            func.avg(ItemFunnelDaily.ctr).label("ctr"),
            func.avg(ItemFunnelDaily.cvr).label("cvr"),
        )
        .where(ItemFunnelDaily.item_id == item_id)
        .where(ItemFunnelDaily.day >= from_day)
        .where(ItemFunnelDaily.day <= to_day)
        .where(production_funnel_clause(ItemFunnelDaily.data_source))
    )
    row = db.execute(stmt).mappings().one()
    return {
        "orders": float(row["orders"] or 0),
        "gmv": float(row["gmv"] or 0),
        "impressions": float(row["impressions"] or 0),
        "visits": float(row["visits"] or 0),
        "ctr": float(row["ctr"]) if row["ctr"] is not None else None,
        "cvr": float(row["cvr"]) if row["cvr"] is not None else None,
    }

def _delta_pct(baseline: Optional[float], observed: Optional[float]) -> Optional[float]:
    if baseline is None or observed is None or baseline == 0:
        return None
    return (observed - baseline) / baseline * 100.0

def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value).strip().lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")

def _recommendation_evidence(rec: Recommendation) -> list[str]:
    if not rec.evidence_json:
        return []
    try:
        payload = json.loads(rec.evidence_json)
    except json.JSONDecodeError:
        return []
    lines: list[str] = []
    if isinstance(payload, list):
        lines.extend(str(row) for row in payload[:4])
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (str, int, float)):
                lines.append(f"{key}: {value}")
            elif isinstance(value, list):
                lines.extend(str(row) for row in value[:2])
    return lines[:3]

def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return deduped

def _agent_meta(key: AgentKey, generated_at: datetime, confidence: Optional[float]) -> AgentMeta:
    return AgentMeta(key=key, label=AGENT_LABELS[key], confidence=confidence, generated_at=generated_at)

def _price_band(menu_items: list[dict[str, Any]]) -> Optional[str]:
    prices = [float(row["price"]) for row in menu_items if row.get("price") is not None]
    if not prices:
        return None
    return f"{int(min(prices))}-{int(max(prices))}"
