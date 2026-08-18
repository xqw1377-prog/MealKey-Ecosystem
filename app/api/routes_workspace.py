from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes_dev import seed_demo
from app.core.config import settings
from app.core.security import enforce_store_access
from app.db.session import get_db
from app.models.entities import Brand, ItemFunnelDaily, Menu, MenuItem, MenuItemVersion, Merchant, ShopFunnelDaily, Store
from app.models.intake import IntakeRawAsset, IntakeSubmission
from app.models.notification import Notification
from app.models.ohre import Experiment, Hypothesis, Observation, Recommendation
from app.models.settings import AppSetting
from app.schemas.workspace import AskRequest, DocumentSyncRequest, IntakeSubmitRequest, IntakePreviewRequest
from app.services.agents import build_store_agents
from app.services.chat_attachments import build_attachment_context, parse_upload_files
from app.services.daily_job import run_daily_job
from app.services.truth_resolution import production_funnel_clause
from app.services.document_alignment import build_document_alignment, preview_document_alignment
from app.services.store_state import build_store_state

router = APIRouter()
logger = logging.getLogger(__name__)


def _store_query():
    return select(Store).options(
        selectinload(Store.merchant),
        selectinload(Store.brand),
        selectinload(Store.items).selectinload(MenuItem.current_version),
    )


def _load_store(db: Session, store_id: str) -> Store | None:
    stmt = _store_query().where(Store.id == store_id)
    return db.execute(stmt).scalar_one_or_none()


def _json_loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _json_loads_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _confidence_label(score: float | None) -> str:
    if score is None:
        return "medium"
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def _question_examples() -> list[str]:
    return [
        "为什么最近订单下降？",
        "我应该增加什么菜？",
        "附近谁在抢我的生意？",
        "我的资料和系统判断对齐了吗？",
    ]


def _health_score(kpis: dict[str, Any]) -> int:
    score = 78
    weights = {"orders": 0.9, "ctr": 0.8, "cvr": 0.7, "impressions": 0.4}
    for metric, weight in weights.items():
        delta = (kpis.get(metric) or {}).get("delta_pct")
        if delta is None:
            continue
        score += int(max(min(delta, 12), -18) * weight)
    return max(32, min(96, score))


def _score_breakdown(store_state: dict[str, Any]) -> list[dict[str, Any]]:
    kpis = store_state.get("kpis", {})
    core_items = store_state.get("core_items", [])
    feedback_scores = (store_state.get("feedback") or {}).get("scores", {})
    product_metric = 80
    if core_items:
        avg_ctr_delta = sum((item.get("ctr_delta_pct") or 0) for item in core_items) / len(core_items)
        product_metric = max(40, min(95, 80 + int(avg_ctr_delta)))
    menu_structure = 74
    if len(core_items) >= 3:
        menu_structure += 4
    if len(core_items) <= 1:
        menu_structure -= 8
    competition = 72
    if store_state.get("competition_changes"):
        competition -= min(12, len(store_state["competition_changes"]) * 3)
    orders_delta = (kpis.get("orders") or {}).get("delta_pct") or 0
    trend = max(40, min(95, 76 + int(orders_delta)))
    rating_hint = feedback_scores.get("sentiment") or 0.75
    review = max(45, min(95, int(60 + rating_hint * 35)))
    rows = [
        {"key": "product", "label": "商品表现", "weight": 0.30, "score": product_metric},
        {"key": "menu", "label": "菜单结构", "weight": 0.20, "score": menu_structure},
        {"key": "competition", "label": "竞争能力", "weight": 0.20, "score": competition},
        {"key": "trend", "label": "经营趋势", "weight": 0.20, "score": trend},
        {"key": "review", "label": "评价表现", "weight": 0.10, "score": review},
    ]
    for row in rows:
        row["weighted_score"] = round(row["score"] * row["weight"], 1)
    return rows


def _estimate_intake_readiness(payload: IntakePreviewRequest) -> dict[str, Any]:
    missing_fields: list[str] = []
    if not payload.store_name:
        missing_fields.append("store_name")
    if not payload.category:
        missing_fields.append("category")
    if not (payload.platform_store_url or payload.menu_items or payload.raw_assets):
        missing_fields.append("menu_or_source")
    if not payload.daily_metrics:
        missing_fields.append("daily_metrics")

    source_types = sorted({asset.asset_type for asset in payload.raw_assets})
    if payload.platform_store_url:
        source_types.append("store_link")
    if payload.menu_items:
        source_types.append("structured_menu")
    if payload.daily_metrics:
        source_types.append("daily_metrics")
    source_types = sorted(set(source_types))

    score = 100
    score -= len(missing_fields) * 18
    score += min(12, len(source_types) * 4)
    readiness_score = max(25, min(96, score))
    if readiness_score >= 82:
        readiness = "ready"
    elif readiness_score >= 60:
        readiness = "partial"
    else:
        readiness = "needs_more_data"
    return {
        "readiness": readiness,
        "readiness_score": readiness_score,
        "missing_fields": missing_fields,
        "source_types": source_types,
        "can_generate_report": readiness != "needs_more_data",
    }


def _build_store_profile_preview(payload: IntakePreviewRequest) -> dict[str, Any]:
    price_values = [item.price for item in payload.menu_items if item.price is not None]
    price_band = None
    if price_values:
        price_band = f"{int(min(price_values))}-{int(max(price_values))}"
    audience = payload.audience or "待确认客群"
    market_hint = payload.area or payload.city or "待补充商圈"
    core_item = payload.menu_items[0].name if payload.menu_items else "待识别核心商品"
    return {
        "store_name": payload.store_name,
        "category": payload.category,
        "market": market_hint,
        "audience": audience,
        "price_band": price_band,
        "competition_level": "高" if payload.area and "写字楼" in payload.area else "待判定",
        "core_item": core_item,
    }


def _expand_intake_metrics(payload: IntakeSubmitRequest) -> list[dict[str, Any]]:
    metrics = sorted(payload.daily_metrics, key=lambda row: row.day)
    if not metrics:
        return []

    window_days = 7
    today = date.today()
    observe_to = today - timedelta(days=1)
    observe_from = observe_to - timedelta(days=window_days - 1)
    baseline_to = observe_from - timedelta(days=1)
    baseline_from = baseline_to - timedelta(days=window_days - 1)

    first = metrics[0]
    last = metrics[-1]
    downtrend = (
        (first.orders is not None and last.orders is not None and last.orders < first.orders)
        or "下降" in (payload.pain or "")
    )
    baseline_multiplier = 1.12 if downtrend else 0.94
    impressions_multiplier = 1.03 if downtrend else 0.98

    expanded: list[dict[str, Any]] = []

    def _as_number(value: Any, fallback: float = 0.0) -> float:
        if value is None:
            return fallback
        return float(value)

    for idx in range(window_days):
        day = baseline_from + timedelta(days=idx)
        orders = max(1, round(_as_number(last.orders, 100) * baseline_multiplier))
        impressions = max(orders * 8, round(_as_number(last.impressions, 4000) * impressions_multiplier))
        visits = max(orders * 2, round(_as_number(last.visits, 600) * baseline_multiplier))
        gmv = round(_as_number(last.gmv, orders * 30) * baseline_multiplier, 2)
        expanded.append(
            {
                "day": day,
                "orders": orders,
                "impressions": impressions,
                "visits": visits,
                "add_to_cart": max(orders, round(visits * 0.42)),
                "payments": orders,
                "gmv": gmv,
                "aov": round(gmv / orders, 2) if orders else None,
                "phase": "baseline",
                "synthetic": True,
            }
        )

    for idx in range(window_days):
        day = observe_from + timedelta(days=idx)
        seed = metrics[min(idx, len(metrics) - 1)]
        orders = max(1, round(_as_number(seed.orders, _as_number(last.orders, 100))))
        impressions = max(orders * 8, round(_as_number(seed.impressions, _as_number(last.impressions, 4000))))
        visits = max(orders * 2, round(_as_number(seed.visits, _as_number(last.visits, 600))))
        gmv = round(_as_number(seed.gmv, _as_number(last.gmv, orders * 30)), 2)
        expanded.append(
            {
                "day": day,
                "orders": orders,
                "impressions": impressions,
                "visits": visits,
                "add_to_cart": max(orders, round(visits * 0.4)),
                "payments": orders,
                "gmv": gmv,
                "aov": round(gmv / orders, 2) if orders else None,
                "phase": "observe",
                "synthetic": seed.orders is None or seed.impressions is None,
            }
        )

    return expanded


def _metric_label(metric: str) -> str:
    labels = {
        "gmv": "成交额",
        "orders": "订单",
        "impressions": "曝光",
        "ctr": "点击率",
        "cvr": "转化率",
    }
    return labels.get(metric, metric)


def _recommendation_title(action_type: str) -> str:
    mapping = {
        "change_main_image": "先换主图，抢回第一眼点击",
        "change_title": "重写标题，把卖点和价格感知说清",
        "add_set_meal": "补一组套餐，承接犹豫用户",
        "store_discount": "只在必要时做门店折扣测试",
    }
    return mapping.get(action_type, action_type)


def _recommendation_summary(action_type: str) -> str:
    mapping = {
        "change_main_image": "低风险、可逆、最适合先验证 CTR。",
        "change_title": "适合在不改价格的前提下提升点击吸引力。",
        "add_set_meal": "更适合解决 CVR 和凑单承接问题。",
        "store_discount": "高冲击但高风险，优先级应低于图文和套餐。",
    }
    return mapping.get(action_type, "把建议收敛为一条明确动作。")


def _problem_summary(problem_type: str | None) -> str:
    mapping = {
        "store_ctr_down": "昨天的核心问题不是流量塌了，而是第一眼吸引力不足。",
        "store_cvr_down": "昨天的核心问题不是没人看，而是看完没有下单。",
    }
    return mapping.get(problem_type, "昨天的核心问题需要继续收敛证据。")


def _action_package(rec: Recommendation, item_names: dict[str, str]) -> dict[str, Any]:
    object_name = rec.object_ref
    item_id = None
    if rec.object_ref.startswith("item:"):
        item_id = rec.object_ref.split(":", 1)[1]
        object_name = item_names.get(item_id, "当前主推商品")
    elif rec.object_ref.startswith("store:"):
        object_name = "门店整体"

    steps_map = {
        "change_main_image": [
            "保留一个主视觉主体，不拼贴，不堆字。",
            "突出菜品本体、分量感和热气，背景降噪。",
            "24 小时只改主图，不叠加折扣活动。",
        ],
        "change_title": [
            "标题先写品类和主卖点，再写价格感知。",
            "避免口号式修饰，聚焦一个决策理由。",
            "24 小时内只测试一个标题版本。",
        ],
        "add_set_meal": [
            "围绕主推 SKU 增加 1 组低决策成本套餐。",
            "价格锚点要和当前客单保持同区间。",
            "先做午餐或晚餐单时段验证，避免全量铺开。",
        ],
        "store_discount": [
            "先限定时段和对象，再决定折扣深度。",
            "与主图/标题改动错开，避免归因混淆。",
            "72 小时内重点盯订单与利润质量。",
        ],
    }
    generated_map = {
        "change_main_image": {
            "visual_brief": f"{object_name} 使用干净近景主图，突出肉量、热气和真实分量，不加营销贴纸。",
            "caption": f"{object_name}｜现炒现出锅，第一眼就让人知道值不值得点",
        },
        "change_title": {
            "title_candidate": f"{object_name}｜现炒热卖·分量更稳",
            "subtitle_candidate": "先把用户点进来，再看是否需要动价格。",
        },
        "add_set_meal": {
            "bundle_name": f"{object_name} 双人套餐",
            "bundle_logic": "主推 SKU + 一份小食/饮品，优先解决犹豫用户的选择障碍。",
        },
        "store_discount": {
            "campaign_name": "午餐时段限时折扣",
            "campaign_note": "只作为最后顺位测试，不建议和低风险动作同时上。",
        },
    }
    return {
        "id": rec.id,
        "title": _recommendation_title(rec.action_type),
        "summary": _recommendation_summary(rec.action_type),
        "object_ref": rec.object_ref,
        "object_name": object_name,
        "action_type": rec.action_type,
        "expected_metric": rec.expected_metric,
        "expected_lift_pct_low": rec.expected_lift_pct_low,
        "expected_lift_pct_high": rec.expected_lift_pct_high,
        "window_hours": rec.window_hours,
        "rollback_rule": rec.rollback_rule,
        "confidence": rec.confidence,
        "status": rec.status,
        "adopted_at": rec.adopted_at,
        "executed_at": rec.executed_at,
        "evidence": _json_loads_list(rec.evidence_json),
        "steps": steps_map.get(rec.action_type, []),
        "generated_content": generated_map.get(rec.action_type, {}),
    }


def _recommendation_priority(rec: Recommendation) -> float:
    lift = float(rec.expected_lift_pct_high or rec.expected_lift_pct_low or 5)
    confidence = float(rec.confidence or 0.5)
    scope_bonus = 1.15 if rec.object_ref.startswith("item:") else 0.92
    action_bias = {
        "change_main_image": 1.20,
        "change_title": 1.08,
        "add_set_meal": 1.0,
        "store_discount": 0.55,
    }.get(rec.action_type, 0.9)
    return lift * confidence * scope_bonus * action_bias


def _build_daily_brief(
    store_state: dict[str, Any],
    today_action: dict[str, Any] | None,
    hypothesis: Hypothesis | None,
) -> dict[str, Any]:
    primary_problem = (store_state.get("primary_problem") or {}).get("type")
    metrics = store_state.get("kpis", {})
    metric_key = None
    if primary_problem == "store_ctr_down":
        metric_key = "ctr"
    elif primary_problem == "store_cvr_down":
        metric_key = "cvr"
    else:
        metric_key = "orders"

    metric_row = metrics.get(metric_key) or {}
    delta = metric_row.get("delta_pct")
    delta_text = format(delta, ".1f") + "%" if delta is not None else "暂无明显变化"
    return {
        "yesterday_change": f"{_metric_label(metric_key)} {delta_text}" if delta is not None else "昨天未发现明显异常",
        "reason": hypothesis.root_cause if hypothesis else _problem_summary(primary_problem),
        "today_action": today_action["title"] if today_action else "先生成今日主动作",
        "verify_metric": (
            f"看 {today_action['expected_metric']} 在 {today_action['window_hours']} 小时内是否改善"
            if today_action
            else "先运行诊断，再给验证口径"
        ),
    }


def _build_growth_plan(
    store_state: dict[str, Any],
    action_packages: list[dict[str, Any]],
    experiments: list[Experiment],
) -> list[dict[str, Any]]:
    primary_problem = (store_state.get("primary_problem") or {}).get("type")
    focus = "先修点击吸引力" if primary_problem == "store_ctr_down" else "先修转化承接"
    pending_count = sum(1 for exp in experiments if exp.result == "pending")
    plan: list[dict[str, Any]] = []

    if action_packages:
        first = action_packages[0]
        plan.append(
            {
                "day": 1,
                "title": first["title"],
                "goal": focus,
                "instruction": f"先推进 {first['object_name']} 的 {first['action_type']}，不要叠加第二个高风险动作。",
                "verify": f"{first['window_hours']}h 看 {first['expected_metric']} 是否进入正向变化。",
            }
        )

    if len(action_packages) > 1:
        second = action_packages[1]
        plan.append(
            {
                "day": 2,
                "title": "观察主动作，再决定是否推进备选",
                "goal": "避免归因污染",
                "instruction": f"先复核 Day 1 的结果；如果没有明显改善，再准备 {second['title']}。",
                "verify": f"继续看 {action_packages[0]['expected_metric']}，并记录是否需要切换到备选动作。",
            }
        )
        plan.append(
            {
                "day": 3,
                "title": second["title"],
                "goal": "推进第二顺位动作",
                "instruction": f"如果 Day 1 无显著提升，再执行 {second['object_name']} 的 {second['action_type']}。",
                "verify": f"{second['window_hours']}h 看 {second['expected_metric']}。",
            }
        )

    if len(action_packages) > 2:
        third = action_packages[2]
        plan.append(
            {
                "day": 4,
                "title": "补结构，不做价格冲动决策",
                "goal": "保持动作节奏",
                "instruction": f"仅在前两条没有形成稳定改善时，再考虑 {third['title']}。",
                "verify": f"重点看 {third['expected_metric']} 和回滚条件。",
            }
        )

    plan.append(
        {
            "day": 5,
            "title": "复盘本周证据",
            "goal": "把 observation / experiment 写成经验",
            "instruction": "整理本周已执行动作，确认哪些动作该保留，哪些动作该停止。",
            "verify": f"当前待验证动作 {pending_count} 条，优先清空 pending。",
        }
    )
    plan.append(
        {
            "day": 6,
            "title": "只保留一条继续动作",
            "goal": "控制动作频率",
            "instruction": "如果已有正向动作，继续执行它；如果没有，回到低风险动作重新测试。",
            "verify": "不要在同一天同时改图、改标题、改折扣。",
        }
    )
    plan.append(
        {
            "day": 7,
            "title": "周复盘与下周计划",
            "goal": "形成下一轮增长策略",
            "instruction": "按本周验证结果，把动作分成保留、回滚、继续测试三类。",
            "verify": "下周仍保持每天 1 条主动作。",
        }
    )
    return plan[:7]


def _serialize_experiment(exp: Experiment, recommendation_lookup: dict[str, Recommendation]) -> dict[str, Any]:
    from datetime import datetime, timezone

    rec = recommendation_lookup.get(exp.recommendation_id)
    content = _json_loads_dict(getattr(rec, "content_json", None)) if rec else {}
    generated = content.get("generated_content") if isinstance(content.get("generated_content"), dict) else {}
    window_hours = getattr(rec, "window_hours", None) if rec else None
    if window_hours is None and exp.observe_from and exp.observe_to:
        window_hours = max(1, int((exp.observe_to - exp.observe_from).total_seconds() // 3600))
    can_evaluate = False
    if exp.result == "pending":
        if exp.observe_to is None:
            can_evaluate = True
        else:
            observe_to = exp.observe_to
            if observe_to.tzinfo is None:
                observe_to = observe_to.replace(tzinfo=timezone.utc)
            can_evaluate = datetime.now(timezone.utc) >= observe_to
    return {
        "id": exp.id,
        "recommendation_id": exp.recommendation_id,
        "action_title": _recommendation_title(rec.action_type) if rec else "动作验证",
        "action_type": rec.action_type if rec else None,
        "result": exp.result,
        "baseline_value": exp.baseline_value,
        "observed_value": exp.observed_value,
        "lift_pct": exp.lift_pct,
        "attribution_quality": exp.attribution_quality,
        "notes": exp.notes,
        "result_summary": exp.notes,
        "baseline_from": exp.baseline_from,
        "baseline_to": exp.baseline_to,
        "observe_from": exp.observe_from,
        "observe_to": exp.observe_to,
        "window_hours": window_hours,
        "can_evaluate": can_evaluate,
        "metric_name": rec.expected_metric if rec else None,
        "ads_budget": generated.get("recommended_budget") or content.get("recommended_budget"),
        "ads_roi": generated.get("estimated_roi") or content.get("estimated_roi"),
    }


def _recent_trend(db: Session, store_id: str, days: int = 14) -> list[dict[str, Any]]:
    stmt = (
        select(ShopFunnelDaily)
        .where(
            ShopFunnelDaily.store_id == store_id,
            production_funnel_clause(ShopFunnelDaily.data_source),
        )
        .order_by(ShopFunnelDaily.day.desc())
        .limit(days)
    )
    rows = list(reversed(db.execute(stmt).scalars().all()))
    # contribution_profit 为代理估算：GMV × (1 - 佣金 - 补贴) ≈ GMV × 0.70
    take_home_proxy = 0.70
    return [
        {
            "day": row.day.isoformat(),
            "orders": row.orders or 0,
            "gmv": row.gmv or 0,
            "impressions": row.impressions or 0,
            "visits": row.visits or 0,
            "contribution_profit": round(float(row.gmv or 0) * take_home_proxy, 2),
        }
        for row in rows
    ]


def _menu_items(store: Store) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in store.items:
        current = item.current_version
        name = current.name if current else "未命名商品"
        items.append(
            {
                "item_id": item.id,
                "name": name,
                "category": current.category if current else None,
                "price": current.price if current else None,
                "description": current.description if current else None,
                "is_active": item.is_active,
            }
        )
    return items


def _core_items_with_names(store_state: dict[str, Any], item_names: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in store_state.get("core_items", []):
        enriched = dict(row)
        enriched["name"] = item_names.get(row["item_id"], row.get("name") or "当前主推商品")
        share = enriched.get("order_share_pct") or 0
        if share >= 55:
            enriched["role"] = "爆品"
        elif share >= 25:
            enriched["role"] = "主力款"
        elif enriched.get("ctr_delta_pct") is not None and enriched["ctr_delta_pct"] < -8:
            enriched["role"] = "问题商品"
        else:
            enriched["role"] = "观察中"
        out.append(enriched)
    return out


def _today_tasks(action_packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for action in action_packages[:3]:
        tasks.append(
            {
                "id": action["id"],
                "title": action["title"],
                "object_name": action["object_name"],
                "status": action["status"],
            }
        )
    return tasks


def _today_opportunity(action_packages: list[dict[str, Any]], store_state: dict[str, Any]) -> dict[str, Any] | None:
    if not action_packages:
        return None
    action = action_packages[0]
    expected_low = action.get("expected_lift_pct_low") or 0
    expected_high = action.get("expected_lift_pct_high") or expected_low
    return {
        "title": action["object_name"],
        "problem": _problem_summary((store_state.get("primary_problem") or {}).get("type")),
        "impact": f"{expected_low:.0f}%~{expected_high:.0f}%",
        "action_id": action["id"],
    }


def _today_risk(store_state: dict[str, Any]) -> dict[str, Any] | None:
    changes = store_state.get("competition_changes") or []
    if changes:
        first = changes[0]
        return {
            "title": first.get("summary") or "竞品有新变化",
            "impact": "可能影响午餐订单与点击竞争。",
        }
    primary_problem = store_state.get("primary_problem") or {}
    if primary_problem.get("type") == "store_ctr_down":
        return {"title": "主推商品点击竞争力下降", "impact": "如果不处理，主动作会继续丢点击。"}
    if primary_problem.get("type") == "store_cvr_down":
        return {"title": "主推商品转化承接偏弱", "impact": "如果继续叠加活动，归因会更混乱。"}
    return None


def _product_focus(
    store_state: dict[str, Any],
    menu_items: list[dict[str, Any]],
    action_packages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    item_actions = [action for action in action_packages if str(action.get("object_ref", "")).startswith("item:")]
    core_items = store_state.get("core_items") or []
    if not item_actions and not core_items:
        return None

    target_action = item_actions[0] if item_actions else action_packages[0]
    object_ref = target_action.get("object_ref") or ""
    item_id = object_ref.split(":", 1)[1] if object_ref.startswith("item:") else None
    core_item = next((row for row in core_items if row.get("item_id") == item_id), core_items[0] if core_items else None)
    menu_item = next((row for row in menu_items if row.get("item_id") == item_id), None)
    related_actions = [action for action in item_actions if action.get("object_ref") == object_ref][:3]
    if not related_actions and target_action:
        related_actions = [target_action]

    ctr_delta = core_item.get("ctr_delta_pct") if core_item else None
    if ctr_delta is not None and ctr_delta <= -8:
        diagnosis = "用户看见了类似商品，但第一眼没有优先点你。"
        issue = "CTR 下降"
    elif ctr_delta is not None and ctr_delta < 0:
        diagnosis = "商品吸引力在变弱，先优先修主图和标题。"
        issue = "点击吸引力走弱"
    else:
        diagnosis = "先用一个低风险动作验证这个商品还能不能继续放大。"
        issue = "主推商品需要验证"

    return {
        "item_id": item_id,
        "name": target_action.get("object_name") or (menu_item or {}).get("name") or "当前主推商品",
        "role": (core_item or {}).get("role") or "主推商品",
        "category": (menu_item or {}).get("category"),
        "price": (menu_item or {}).get("price"),
        "description": (menu_item or {}).get("description"),
        "issue": issue,
        "diagnosis": diagnosis,
        "ctr_delta_pct": ctr_delta,
        "order_share_pct": (core_item or {}).get("order_share_pct"),
        "actions": related_actions,
        "verify_metric": target_action.get("expected_metric"),
        "window_hours": target_action.get("window_hours"),
        "rollback_rule": target_action.get("rollback_rule"),
    }


def _merge_dashboard_with_agents(dashboard: dict[str, Any], agents_payload) -> dict[str, Any]:
    if agents_payload is None:
        return dashboard

    agents = agents_payload.model_dump(mode="json")
    merged = {**dashboard, "agents": agents}

    menu_items_by_id = {item["item_id"]: item for item in dashboard.get("menu_items", [])}
    menu_agent_items = []
    for item in agents.get("menu", {}).get("items", []):
        combined = dict(menu_items_by_id.get(item["item_id"], {}))
        combined.update(item)
        menu_agent_items.append(combined)

    item_by_id = {item["item_id"]: item for item in menu_agent_items}
    focus_item_id = (agents.get("product") or {}).get("focus_item_id")
    focus_item = item_by_id.get(focus_item_id) if focus_item_id else None
    focus_actions = [
        action
        for action in (dashboard.get("action_packages") or [])
        if focus_item_id and action.get("object_ref") == f"item:{focus_item_id}"
    ]

    merged["store_state"] = {
        **dashboard.get("store_state", {}),
        **(agents.get("store_state") or {}),
        "core_items": [
            {
                "item_id": item["item_id"],
                "name": item["name"],
                "role": item.get("role"),
                "order_share_pct": item.get("order_share_pct"),
                "ctr_delta_pct": item.get("ctr_delta_pct"),
                "flags": [],
            }
            for item in menu_agent_items
        ]
        or dashboard.get("store_state", {}).get("core_items", []),
    }

    competition_agent = agents.get("competition") or {}
    merged["competition"] = {
        **dashboard.get("competition", {}),
        "strategy": competition_agent.get("conclusion") or dashboard.get("competition", {}).get("strategy"),
        "conclusion": competition_agent.get("conclusion") or dashboard.get("competition", {}).get("conclusion"),
        "market_focus": competition_agent.get("market_focus") or dashboard.get("competition", {}).get("market_focus", []),
        "evidence": (
            [
                *(competition_agent.get("reasons") or []),
                *[row.get("summary") for row in (competition_agent.get("changes") or []) if row.get("summary")],
            ]
        )[:6]
        or dashboard.get("competition", {}).get("evidence", []),
        "reasons": competition_agent.get("reasons") or dashboard.get("competition", {}).get("reasons", []),
        "top_competitors": competition_agent.get("top_competitors", []),
        "competition_score": competition_agent.get("competition_score"),
        "nearby_total": competition_agent.get("nearby_total")
        if competition_agent.get("nearby_total") is not None
        else dashboard.get("competition", {}).get("nearby_total"),
        "readiness": competition_agent.get("readiness") or dashboard.get("competition", {}).get("readiness"),
        "expected_impact": competition_agent.get("expected_impact")
        or dashboard.get("competition", {}).get("expected_impact"),
        "benchmark_group": competition_agent.get("benchmark_group")
        or dashboard.get("competition", {}).get("benchmark_group"),
    }

    merged["hypothesis"] = {
        **(dashboard.get("hypothesis") or {}),
        "root_cause": (agents.get("diagnosis") or {}).get("root_cause")
        or (dashboard.get("hypothesis") or {}).get("root_cause"),
        "confidence": (agents.get("diagnosis") or {}).get("meta", {}).get("confidence")
        if (agents.get("diagnosis") or {}).get("meta", {}).get("confidence") is not None
        else (dashboard.get("hypothesis") or {}).get("confidence"),
    }

    diagnosis_observations = (agents.get("diagnosis") or {}).get("observations") or []
    if diagnosis_observations:
        merged["observations"] = [
            {
                **obs,
                "baseline_value": None,
                "observed_value": None,
            }
            for obs in diagnosis_observations
        ]

    merged["product_focus"] = {
        **(dashboard.get("product_focus") or {}),
        "item_id": (agents.get("product") or {}).get("focus_item_id") or (dashboard.get("product_focus") or {}).get("item_id"),
        "name": (agents.get("product") or {}).get("focus_item_name") or (dashboard.get("product_focus") or {}).get("name"),
        "role": (focus_item or {}).get("role") or (dashboard.get("product_focus") or {}).get("role"),
        "category": (focus_item or {}).get("category") or (dashboard.get("product_focus") or {}).get("category"),
        "price": (focus_item or {}).get("price", (dashboard.get("product_focus") or {}).get("price")),
        "description": (focus_item or {}).get("description") or (dashboard.get("product_focus") or {}).get("description"),
        "order_share_pct": (focus_item or {}).get("order_share_pct", (dashboard.get("product_focus") or {}).get("order_share_pct")),
        "ctr_delta_pct": (focus_item or {}).get("ctr_delta_pct", (dashboard.get("product_focus") or {}).get("ctr_delta_pct")),
        "issue": (agents.get("product") or {}).get("issue") or (dashboard.get("product_focus") or {}).get("issue"),
        "diagnosis": (agents.get("product") or {}).get("diagnosis") or (dashboard.get("product_focus") or {}).get("diagnosis"),
        "diagnosis_stage": (agents.get("product") or {}).get("diagnosis_stage"),
        "recommendations": (agents.get("product") or {}).get("recommendations") or [],
        "actions": focus_actions or (dashboard.get("product_focus") or {}).get("actions", []),
    }

    if (agents.get("growth") or {}).get("weekly_plan"):
        merged["growth_plan"] = (agents.get("growth") or {}).get("weekly_plan")
    merged["daily_brief"] = {
        **(dashboard.get("daily_brief") or {}),
        "reason": (agents.get("growth") or {}).get("reason") or (dashboard.get("daily_brief") or {}).get("reason"),
    }

    return merged


def _classify_question(question: str) -> str:
    lowered = question.lower()
    if any(keyword in question for keyword in ("资料", "文档", "对齐", "口径", "事实源")):
        return "document_alignment"
    if any(keyword in question for keyword in ("竞争", "附近", "谁抢", "商圈")):
        return "competition"
    if any(keyword in question for keyword in ("菜单", "增加什么菜", "卖什么", "sku")):
        return "menu"
    if any(keyword in question for keyword in ("商品", "主图", "标题", "牛肉饭", "套餐")):
        return "product"
    if any(keyword in question for keyword in ("为什么", "订单", "下降", "诊断")):
        return "diagnosis"
    if "growth" in lowered or any(keyword in question for keyword in ("增长", "提升", "计划")):
        return "growth"
    return "diagnosis"


def _answer_store_manager(question: str, dashboard: dict[str, Any]) -> dict[str, Any]:
    question_type = _classify_question(question)
    document_alignment = dashboard.get("document_alignment") or {}
    opportunity = dashboard.get("today_opportunity")
    risk = dashboard.get("today_risk")
    hypothesis = dashboard.get("hypothesis") or {}
    tasks = dashboard.get("today_tasks") or []
    competition = dashboard.get("competition") or {}
    core_items = dashboard.get("store_state", {}).get("core_items", [])
    top_item = core_items[0] if core_items else None

    if document_alignment.get("status") in {"conflict", "missing_documents"}:
        reasons = [document_alignment.get("summary") or "当前资料口径还不稳定。"]
        reasons.extend(
            f"{row.get('label')} 在 {row.get('source')} 中出现了冲突值 {row.get('document_value')}"
            for row in document_alignment.get("conflicts", [])[:2]
        )
        actions = document_alignment.get("recommendations") or ["先补齐门店原始资料。"]
        conclusion = "先不要急着下经营动作，当前更需要把资料和系统事实对齐。"
        expected = "先把资料口径统一，再进入经营判断，后续建议会更稳。"
        answer = (
            f"老板，我先帮你踩一脚刹车。{conclusion}"
            f" 现在最关键的是：{actions[0]}"
        )
        return {
            "question": question,
            "question_type": "document_alignment",
            "conclusion": conclusion,
            "reasons": reasons[:3],
            "actions": actions[:3],
            "expected": expected,
            "confidence": _confidence_label(0.92 if document_alignment.get("status") == "conflict" else 0.75),
            "answer": answer,
            "document_alignment": {
                "status": document_alignment.get("status"),
                "alignment_score": document_alignment.get("alignment_score"),
            },
        }

    if question_type == "document_alignment":
        conclusion = document_alignment.get("summary") or "当前资料已经进入系统，但还需要继续补强证据。"
        reasons = [
            f"当前文档对齐分 {document_alignment.get('alignment_score', 0)}。",
            f"已接入原始资料 {document_alignment.get('documents_count', 0)} 份。",
        ]
        if document_alignment.get("missing_fields"):
            reasons.append(f"仍缺少 {len(document_alignment['missing_fields'])} 个关键字段证据。")
        actions = document_alignment.get("recommendations") or ["继续补充经营资料。"]
        expected = "资料越完整，后续诊断、问答和动作建议就越能保持同一口径。"
    elif question_type == "competition":
        conclusion = competition.get("strategy") or "先别急着降价，先看谁在用套餐和图片抢你的第一眼。"
        reasons = list(competition.get("evidence") or ["当前优先看同商圈、同价格带、同用户群的竞争对手。"])
        actions = [
            "先补一个高价值套餐，而不是直接全店降价。",
            "盯住近 7 天竞品的套餐和主图变化。",
        ]
        expected = "先把竞争问题收敛成 1 条动作，再在 24-72 小时内看订单与 CTR。"
    elif question_type == "menu":
        conclusion = "先把菜单当成赚钱结构来调，不是继续堆 SKU。"
        reasons = [
            f"当前核心商品数量 {len(core_items)} 个，先围绕主力款做结构优化。",
            "优先补引流款、套餐和搭配品，再处理低效 SKU。",
        ]
        actions = [
            "先删除 1-2 个长期低效 SKU。",
            "围绕主推商品补 1 个低决策成本套餐。",
        ]
        expected = "目标是先改善菜单承接效率，再观察订单结构是否变稳。"
    elif question_type == "product":
        item_name = top_item.get("name") if top_item else "当前主推商品"
        conclusion = f"{item_name} 的问题先看点击和转化，不要先动价格。"
        reasons = [
            hypothesis.get("root_cause") or "当前商品需要先收敛到底是 CTR 还是 CVR 问题。",
            f"主推商品角色：{top_item.get('role')}" if top_item else "先锁定一个主推商品做验证。",
        ]
        actions = [
            "先改主图或标题，只做一个低风险动作。",
            "如果点击改善仍不下单，再补套餐。",
        ]
        expected = "优先在 24 小时内验证 CTR，再决定是否进入第二顺位动作。"
    elif question_type == "growth":
        conclusion = "这一周不要做 20 件事，只推进每天 1 条主动作。"
        reasons = [
            dashboard.get("daily_brief", {}).get("reason") or "先锁定当前最大问题。",
            f"当前待验证动作 {dashboard.get('execution_summary', {}).get('pending_verification', 0)} 条。",
        ]
        actions = [row.get("title") for row in dashboard.get("growth_plan", [])[:2]] or ["先生成今日动作。"]
        expected = "先跑完本周计划，再把有效动作沉淀成经验。"
    else:
        conclusion = hypothesis.get("root_cause") or "现在最大的问题不是流量，而是要先收敛经营主因。"
        reasons = [
            dashboard.get("daily_brief", {}).get("yesterday_change") or "先看最近经营变化。",
            risk.get("title") if risk else "当前没有额外高风险信号。",
        ]
        actions = [tasks[0]["title"]] if tasks else ["先刷新今日诊断，生成主动作。"]
        expected = dashboard.get("daily_brief", {}).get("verify_metric") or "先给出验证指标，再判断动作是否有效。"

    answer = (
        f"老板，我看了一下，{conclusion}"
        f" 主要依据是：{reasons[0]}"
        f" 今天先做：{actions[0]}"
    )
    return {
        "question": question,
        "question_type": question_type,
        "conclusion": conclusion,
        "reasons": reasons[:3],
        "actions": actions[:3],
        "expected": expected,
        "confidence": _confidence_label(hypothesis.get("confidence")),
        "answer": answer,
        "document_alignment": {
            "status": document_alignment.get("status"),
            "alignment_score": document_alignment.get("alignment_score"),
        },
    }


def _create_store_from_intake(db: Session, payload: IntakeSubmitRequest, readiness: dict[str, Any]) -> Store:
    from app.services.org_tree import bind_store_to_merchant_tenants

    merchant = None
    brand = None
    if payload.brand_id:
        brand = db.execute(select(Brand).where(Brand.id == payload.brand_id)).scalar_one_or_none()
        if brand is None:
            raise HTTPException(status_code=404, detail="brand not found")
        merchant = db.execute(select(Merchant).where(Merchant.id == brand.merchant_id)).scalar_one_or_none()
    elif payload.merchant_id:
        merchant = db.execute(select(Merchant).where(Merchant.id == payload.merchant_id)).scalar_one_or_none()
        if merchant is None:
            raise HTTPException(status_code=404, detail="enterprise not found")

    created_merchant = merchant is None
    if merchant is None:
        merchant = Merchant(
            name=payload.merchant_name or payload.store_name,
            brand_name=payload.merchant_name,
            category=payload.category,
            cuisine_type=payload.cuisine_type,
            location=payload.address,
            business_hours=payload.business_hours,
        )
        db.add(merchant)
        db.flush()

    if brand is None:
        brand = Brand(
            merchant_id=merchant.id,
            name=payload.merchant_name or payload.category or payload.store_name,
            category=payload.category or merchant.category,
            cuisine_type=payload.cuisine_type or merchant.cuisine_type,
            business_hours=payload.business_hours or merchant.business_hours,
            status="active",
        )
        db.add(brand)
        db.flush()

    store = Store(
        merchant_id=merchant.id,
        brand_id=brand.id,
        name=payload.store_name,
        address=payload.address,
        area=payload.area,
        city=payload.city,
        status="active",
        platform=payload.platform,
        platform_store_key=str(payload.platform_store_url) if payload.platform_store_url else None,
        primary_audience=payload.audience,
        primary_pain=payload.pain,
    )
    db.add(store)
    db.flush()
    if not created_merchant:
        bind_store_to_merchant_tenants(db, store)

    menu = Menu(store_id=store.id, name="默认菜单", type="delivery", version=1, status="active")
    db.add(menu)
    db.flush()

    created_items: list[MenuItem] = []
    for item in payload.menu_items:
        menu_item = MenuItem(store_id=store.id, menu_id=menu.id, is_active=True)
        db.add(menu_item)
        db.flush()
        version = MenuItemVersion(
            item_id=menu_item.id,
            name=item.name,
            category=item.category,
            price=item.price,
            image_url=item.image_url,
            description=item.description,
            source="intake",
        )
        db.add(version)
        db.flush()
        menu_item.current_version_id = version.id
        db.add(menu_item)
        created_items.append(menu_item)

    expanded_metrics = _expand_intake_metrics(payload)

    for metric in expanded_metrics:
        db.merge(
            ShopFunnelDaily(
                store_id=store.id,
                day=metric["day"],
                impressions=metric["impressions"],
                visits=metric["visits"],
                add_to_cart=metric["add_to_cart"],
                payments=metric["payments"],
                orders=metric["orders"],
                gmv=metric["gmv"],
                aov=metric["aov"],
            )
        )

    if created_items and expanded_metrics:
        primary_weight = 0.58
        secondary_weight = (1.0 - primary_weight) / max(len(created_items) - 1, 1)
        for metric in expanded_metrics:
            store_orders = metric["orders"] or 0
            store_gmv = metric["gmv"] or 0.0
            store_visits = metric["visits"] or 0
            store_impressions = metric["impressions"] or 0
            for index, item in enumerate(created_items):
                weight = primary_weight if index == 0 else secondary_weight
                item_orders = max(1, int(round(store_orders * weight))) if store_orders else 0
                item_impressions = max(item_orders * 8, int(round(store_impressions * weight))) if store_impressions else item_orders * 8
                item_visits = max(item_orders * 2, int(round(store_visits * weight))) if store_visits else item_orders * 2
                if index == 0 and metric["phase"] == "observe":
                    item_visits = max(item_orders, int(item_visits * 0.86))
                if index == 0 and metric["phase"] == "baseline":
                    item_visits = max(item_orders, int(item_visits * 1.04))
                item_gmv = round(store_gmv * weight, 2) if store_gmv else None
                ctr = round(item_visits / item_impressions, 4) if item_impressions else None
                cvr = round(item_orders / item_visits, 4) if item_visits else None
                db.merge(
                    ItemFunnelDaily(
                        item_id=item.id,
                        day=metric["day"],
                        impressions=item_impressions,
                        visits=item_visits,
                        payments=item_orders,
                        orders=item_orders,
                        gmv=item_gmv,
                        ctr=ctr,
                        cvr=cvr,
                    )
                )

    submission = IntakeSubmission(
        store_id=store.id,
        merchant_name=payload.merchant_name or payload.store_name,
        store_name=payload.store_name,
        city=payload.city,
        area=payload.area,
        category=payload.category,
        audience=payload.audience,
        pain=payload.pain,
        platform=payload.platform,
        platform_store_url=str(payload.platform_store_url) if payload.platform_store_url else None,
        readiness=readiness["readiness"],
        missing_fields_json=_json_dumps(readiness["missing_fields"]),
        source_types_json=_json_dumps(readiness["source_types"]),
        notes=(
            f"V1 intake readiness score: {readiness['readiness_score']}; "
            f"synthetic_metrics={sum(1 for row in expanded_metrics if row.get('synthetic'))}"
        ),
    )
    db.add(submission)
    db.flush()

    if any(row.get("synthetic") for row in expanded_metrics):
        db.add(
            IntakeRawAsset(
                submission_id=submission.id,
                asset_type="synthetic_metric_note",
                label="合成基线说明",
                source_url=None,
                raw_text="部分基线/观察漏斗由系统按启发式补齐，仅用于冷启动演示，不作为真实经营事实。",
                parsed_json=_json_dumps({"synthetic_metric_count": sum(1 for row in expanded_metrics if row.get("synthetic"))}),
            )
        )

    for asset in payload.raw_assets:
        db.add(
            IntakeRawAsset(
                submission_id=submission.id,
                asset_type=asset.asset_type,
                label=asset.label,
                source_url=str(asset.source_url) if asset.source_url else None,
                raw_text=asset.raw_text,
                parsed_json=None,
            )
        )

    if payload.platform_store_url:
        db.add(
            IntakeRawAsset(
                submission_id=submission.id,
                asset_type="store_link",
                label="店铺链接",
                source_url=str(payload.platform_store_url),
                raw_text=None,
                parsed_json=_json_dumps({"source": "platform_store_url"}),
            )
        )

    return store


def _append_store_documents(db: Session, store: Store, payload: DocumentSyncRequest) -> IntakeSubmission:
    submission = IntakeSubmission(
        store_id=store.id,
        merchant_name=getattr(store.merchant, "name", store.name),
        store_name=store.name,
        city=store.city,
        area=store.area,
        category=getattr(store.merchant, "category", None),
        audience=store.primary_audience,
        pain=store.primary_pain,
        platform=store.platform,
        platform_store_url=store.platform_store_key,
        readiness="partial",
        missing_fields_json=_json_dumps([]),
        source_types_json=_json_dumps(sorted({asset.asset_type for asset in payload.assets})),
        notes=payload.note or "Document sync",
    )
    db.add(submission)
    db.flush()

    for asset in payload.assets:
        db.add(
            IntakeRawAsset(
                submission_id=submission.id,
                asset_type=asset.asset_type,
                label=asset.label,
                source_url=str(asset.source_url) if asset.source_url else None,
                raw_text=asset.raw_text,
                parsed_json=None,
            )
        )

    return submission


def _build_dashboard_payload(db: Session, store: Store, days: int) -> dict[str, Any]:
    store_state_model = build_store_state(db=db, store_id=store.id, days=days)
    if store_state_model is None:
        raise HTTPException(status_code=404, detail="store not found")
    document_alignment = build_document_alignment(db=db, store_id=store.id)

    rec_stmt = (
        select(Recommendation)
        .where(Recommendation.store_id == store.id)
        .order_by(Recommendation.created_at.desc())
        .limit(6)
    )
    recommendations = db.execute(rec_stmt).scalars().all()
    if not recommendations:
        run_daily_job(db=db, store_id=store.id, days=days)
        recommendations = db.execute(rec_stmt).scalars().all()
    recommendations = sorted(recommendations, key=_recommendation_priority, reverse=True)

    obs_stmt = (
        select(Observation)
        .where(Observation.store_id == store.id)
        .order_by(Observation.created_at.desc())
        .limit(5)
    )
    observations = db.execute(obs_stmt).scalars().all()

    hypothesis_stmt = (
        select(Hypothesis)
        .where(Hypothesis.store_id == store.id)
        .order_by(Hypothesis.created_at.desc())
        .limit(1)
    )
    hypothesis = db.execute(hypothesis_stmt).scalar_one_or_none()

    exp_stmt = (
        select(Experiment)
        .where(Experiment.store_id == store.id)
        .order_by(Experiment.created_at.desc())
        .limit(6)
    )
    experiments = db.execute(exp_stmt).scalars().all()

    store_state = store_state_model.model_dump(mode="json")
    item_names = {item["item_id"]: item["name"] for item in _menu_items(store)}
    store_state["core_items"] = _core_items_with_names(store_state, item_names)

    metric_rows = []
    for key, value in store_state["kpis"].items():
        metric_rows.append(
            {
                "key": key,
                "label": _metric_label(key),
                "value": value.get("value"),
                "baseline_value": value.get("baseline_value"),
                "observed_value": value.get("observed_value"),
                "delta_pct": value.get("delta_pct"),
                "confidence": value.get("confidence"),
            }
        )

    recommendation_lookup = {rec.id: rec for rec in recommendations}
    menu_items = _menu_items(store)
    action_packages = [_action_package(rec, item_names) for rec in recommendations]
    experiments_payload = [_serialize_experiment(exp, recommendation_lookup) for exp in experiments]
    daily_brief = _build_daily_brief(store_state=store_state, today_action=action_packages[0] if action_packages else None, hypothesis=hypothesis)
    growth_plan = _build_growth_plan(store_state=store_state, action_packages=action_packages, experiments=experiments)

    primary_problem = store_state.get("primary_problem") or {}
    competition_view = {
        "benchmark_group": "同商圈 / 同价格带 / 同用户群",
        "strategy": (
            "先赢点击，再考虑价格动作。"
            if primary_problem.get("type") == "store_ctr_down"
            else "先修转化承接，再决定要不要扩活动。"
        ),
        "market_focus": store_state["market"].get("market_type", []),
        "evidence": _json_loads_list(hypothesis.evidence_refs) if hypothesis else [],
    }

    execution_summary = {
        "proposed": sum(1 for rec in recommendations if rec.status == "proposed"),
        "adopted": sum(1 for rec in recommendations if rec.status == "adopted"),
        "executed": sum(1 for rec in recommendations if rec.status == "executed"),
        "pending_verification": sum(1 for exp in experiments if exp.result == "pending"),
    }
    score_breakdown = _score_breakdown(store_state)
    today_tasks = _today_tasks(action_packages)
    today_opportunity = _today_opportunity(action_packages, store_state)
    today_risk = _today_risk(store_state)
    product_focus = _product_focus(store_state=store_state, menu_items=menu_items, action_packages=action_packages)

    dashboard = {
        "store": {
            "id": store.id,
            "name": store.name,
            "city": store.city,
            "area": store.area,
            "category": getattr(store.brand, "category", None) or getattr(store.merchant, "category", None),
            "audience": store.primary_audience,
            "pain": store.primary_pain,
            "alignment_score": document_alignment.get("alignment_score"),
        },
        "health_score": _health_score(store_state["kpis"]),
        "score_breakdown": score_breakdown,
        "store_state": store_state,
        "document_alignment": document_alignment,
        "metrics": metric_rows,
        "trend": _recent_trend(db, store.id, max(days * 2, 14)),
        "menu_items": menu_items,
        "observations": [
            {
                "id": obs.id,
                "metric": obs.metric,
                "what_happened": obs.what_happened,
                "baseline_value": obs.baseline_value,
                "observed_value": obs.observed_value,
                "delta_pct": obs.delta_pct,
                "confidence": obs.confidence,
                "evidence": _json_loads_dict(obs.evidence_json),
                "created_at": obs.created_at,
            }
            for obs in observations
        ],
        "hypothesis": (
            {
                "id": hypothesis.id,
                "funnel_stage": hypothesis.funnel_stage,
                "root_cause": hypothesis.root_cause,
                "confidence": hypothesis.confidence,
                "competing_explanations": _json_loads_list(hypothesis.competing_explanations),
                "evidence_refs": _json_loads_list(hypothesis.evidence_refs),
                "created_at": hypothesis.created_at,
            }
            if hypothesis
            else None
        ),
        "competition": competition_view,
        "action_packages": action_packages,
        "today_action": action_packages[0] if action_packages else None,
        "today_opportunity": today_opportunity,
        "today_risk": today_risk,
        "today_tasks": today_tasks,
        "product_focus": product_focus,
        "daily_brief": daily_brief,
        "growth_plan": growth_plan,
        "experiments": experiments_payload,
        "execution_summary": execution_summary,
        "question_examples": _question_examples(),
        "meta": {
            "days": days,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    agents_payload = build_store_agents(db=db, store_id=store.id, days=days)
    return _merge_dashboard_with_agents(dashboard, agents_payload)


@router.post("/intake/preview")
def preview_intake(payload: IntakePreviewRequest):
    readiness = _estimate_intake_readiness(payload)
    document_preview = preview_document_alignment(
        {
            "store_name": payload.store_name,
            "category": payload.category,
            "area": payload.area,
            "audience": payload.audience,
            "pain": payload.pain,
            "city": payload.city,
            "business_hours": None,
            "raw_assets": [
                {
                    "asset_type": asset.asset_type,
                    "label": asset.label,
                    "source_url": str(asset.source_url) if asset.source_url else None,
                    "raw_text": asset.raw_text,
                }
                for asset in payload.raw_assets
            ],
        }
    )
    return {
        "store_profile": _build_store_profile_preview(payload),
        "readiness": readiness["readiness"],
        "readiness_score": readiness["readiness_score"],
        "missing_fields": readiness["missing_fields"],
        "source_types": readiness["source_types"],
        "can_generate_report": readiness["can_generate_report"],
        "document_insights": document_preview,
        "message": (
            "当前资料已经足够生成第一份增长报告。"
            if readiness["can_generate_report"]
            else "当前资料还不足，先补菜单或最近 7-30 天经营数据。"
        ),
    }


@router.post("/intake/submit")
def submit_intake(payload: IntakeSubmitRequest, db: Session = Depends(get_db)):
    readiness = _estimate_intake_readiness(payload)
    store = _create_store_from_intake(db, payload, readiness)
    if payload.referral_artifact_id:
        from app.services.commercial.growth import attach_referral_store

        attach_referral_store(db, artifact_id=payload.referral_artifact_id, to_store_id=store.id)
    db.commit()
    db.refresh(store)
    if settings.is_dev:
        from app.services.test_store_access import open_test_store_access

        open_test_store_access(db, store)
        db.refresh(store)
    dashboard = _build_dashboard_payload(db=db, store=store, days=7)
    return {
        "store_id": store.id,
        "readiness": readiness["readiness"],
        "readiness_score": readiness["readiness_score"],
        "dashboard": dashboard,
    }


@router.get("/stores")
def list_stores(db: Session = Depends(get_db)):
    stmt = _store_query().order_by(Store.created_at.desc())
    stores = db.execute(stmt).scalars().all()
    return {
        "stores": [
            {
                "id": store.id,
                "name": store.name,
                "city": store.city,
                "area": store.area,
                "category": getattr(store.brand, "category", None) or getattr(store.merchant, "category", None),
                "audience": store.primary_audience,
                "pain": store.primary_pain,
                "merchant_id": store.merchant_id,
                "merchant_name": getattr(store.merchant, "name", None),
                "brand_id": store.brand_id,
                "brand_name": getattr(store.brand, "name", None) or getattr(store.merchant, "brand_name", None),
            }
            for store in stores
        ]
    }


@router.post("/bootstrap")
def bootstrap_workspace(db: Session = Depends(get_db)):
    stmt = _store_query().order_by(Store.created_at.desc())
    stores = db.execute(stmt).scalars().all()
    created = False
    payload: dict[str, Any] = {}
    if not stores:
        payload = seed_demo(db)
        stores = db.execute(stmt).scalars().all()
        created = True
        if stores:
            from app.services.test_store_access import open_test_store_access

            open_test_store_access(db, stores[0])
    default_store = stores[0] if stores else None
    return {
        "created": created,
        "default_store_id": payload.get("store_id") if created else (default_store.id if default_store else None),
        "store_count": len(stores),
    }


@router.get("/stores/{store_id}/notifications")
def get_store_notifications(
    store_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """获取门店未读通知（需 token；已从 /public 迁出）。"""
    from app.services.notification_service import get_unread_notifications

    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return {"notifications": get_unread_notifications(db, store_id, limit)}


@router.post("/notifications/{notification_id}/read")
def read_store_notification(notification_id: str, db: Session = Depends(get_db)):
    """标记通知已读。"""
    from app.services.notification_service import mark_notification_read

    ok = mark_notification_read(db, notification_id)
    return {"ok": ok}


@router.post("/platforms/oauth/{platform}/start")
def start_platform_oauth(request: Request, platform: str, store_id: str = Query(default="")):
    """平台 OAuth 入口。"""
    from app.services.platform_oauth import build_oauth_state, get_oauth_url, is_oauth_configured

    enforce_store_access(getattr(request.state, "principal", None), store_id or None)
    key = (platform or "").strip().lower()
    if key not in {"meituan", "eleme"}:
        raise HTTPException(status_code=400, detail="unsupported platform")
    if not is_oauth_configured(key):
        raise HTTPException(
            status_code=501,
            detail="OAuth not configured for this platform; use connect-code flow instead",
        )
    state = build_oauth_state(key, store_id=store_id)
    url = get_oauth_url(key, state=state)
    if not url:
        raise HTTPException(status_code=501, detail="OAuth URL unavailable")
    return {"ok": True, "platform": key, "oauth_url": url, "state": state}


@router.get("/platforms/oauth/{platform}/callback")
def platform_oauth_callback(
    platform: str,
    code: str = Query(default=""),
    state: str = Query(default=""),
    db: Session = Depends(get_db),
):
    from app.services.platform_oauth import (
        exchange_code_for_token,
        oauth_connected_message,
        parse_oauth_state,
        persist_oauth_connection,
    )

    key = (platform or "").strip().lower()
    if key not in {"meituan", "eleme"}:
        raise HTTPException(status_code=400, detail="unsupported platform")
    if not code.strip():
        raise HTTPException(status_code=400, detail="missing code")
    parsed = parse_oauth_state(state)
    store_id = str(parsed.get("store_id") or "").strip()
    if not store_id:
        raise HTTPException(status_code=400, detail="missing store_id in state")
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    try:
        token_payload = exchange_code_for_token(key, code.strip())
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not token_payload:
        raise HTTPException(status_code=502, detail="oauth exchange failed")
    row = persist_oauth_connection(db, store_id=store_id, platform=key, token_payload=token_payload)
    db.commit()
    db.refresh(row)
    return {
        "ok": True,
        "store_id": store_id,
        "platform": key,
        "message": oauth_connected_message(key, row),
        "link": {
            "platform": row.platform,
            "status": row.status,
            "connector_mode": row.connector_mode,
            "external_store_id": row.external_store_id,
            "auth_expires_at": row.auth_expires_at.isoformat() if row.auth_expires_at else None,
        },
    }


@router.get("/stores/{store_id}/dashboard")
def get_store_dashboard(
    store_id: str,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    from app.services.llm_engine.request_budget import homepage_read_scope

    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    with homepage_read_scope():
        return _build_dashboard_payload(db=db, store=store, days=days)


@router.get("/stores/{store_id}/document-alignment")
def get_store_document_alignment(store_id: str, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return build_document_alignment(db=db, store_id=store_id)


@router.post("/stores/{store_id}/documents")
def sync_store_documents(
    store_id: str,
    payload: DocumentSyncRequest,
    db: Session = Depends(get_db),
):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    if not payload.assets:
        raise HTTPException(status_code=400, detail="assets required")
    submission = _append_store_documents(db=db, store=store, payload=payload)
    db.commit()
    return {
        "store_id": store_id,
        "submission_id": submission.id,
        "documents_count": len(payload.assets),
        "document_alignment": build_document_alignment(db=db, store_id=store_id),
    }


@router.post("/stores/{store_id}/ask")
def ask_store_manager(
    store_id: str,
    payload: AskRequest,
    db: Session = Depends(get_db),
):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    result = _route_answer_store_manager(
        db=db,
        store_id=store_id,
        question=payload.question,
        shortcut_question=payload.question,
        days=payload.days,
        use_shortcuts=True,
        work_thread_id=payload.work_thread_id,
    )
    return _attach_runtime_context(store_id, db, result)


@router.post("/stores/{store_id}/ask-rich")
async def ask_store_manager_rich(
    store_id: str,
    question: str = Form(default=""),
    days: int = Form(default=7),
    work_thread_id: str = Form(default=""),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    try:
        parsed_files = await parse_upload_files(files)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    attachment_context = build_attachment_context(parsed_files)
    if parsed_files:
        from app.services.mue.engine import ingest_attachment_knowledge
        from app.services.loop_ingest import ingest_operating_attachments

        ingest_attachment_knowledge(db, store_id, parsed_files)
        try:
            ingest_operating_attachments(db, store_id, parsed_files)
        except Exception:
            logger.exception("operating ingest failed for store %s", store_id)
        try:
            from app.services.metrics_ingest import ingest_funnel_from_attachments

            ingest_funnel_from_attachments(db, store_id, parsed_files)
        except Exception:
            logger.exception("funnel ingest failed for store %s", store_id)
    base_question = (question or "").strip() or "请先帮我读取这些附件，提炼重点，再告诉我接下来该怎么处理。"
    enriched_question = base_question if not attachment_context else f"{base_question}\n\n{attachment_context}"
    result = _route_answer_store_manager(
        db=db,
        store_id=store_id,
        question=enriched_question,
        shortcut_question=base_question,
        days=max(1, int(days or 7)),
        use_shortcuts=True,
        work_thread_id=work_thread_id or None,
    )
    result["attachments"] = [item.to_public_dict() for item in parsed_files]
    return _attach_runtime_context(store_id, db, result)


@router.get("/stores/{store_id}/read-file")
@router.post("/stores/{store_id}/read-file")
def read_file_by_path(
    store_id: str,
    file_path: str = Query(..., description="服务端文件路径"),
    question: str = Query(default=""),
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    """给文件路径→读取→蒸馏→接入对话。

    老板可以给一个路径（如成本表/菜单图/报表），
    系统直接读取→解析→蒸馏→作为对话上下文回答问题。

    支持：.txt .md .csv .xlsx .pdf .json .xml .html
    """
    from app.services.chat_attachments import read_file_by_path as _read

    result = _read(file_path)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "读取失败"))

    # 如果有问题，把文件内容作为上下文调 ask
    if question.strip():
        context = result.get("context_for_chat", "")
        combined_question = f"{question}\n\n参考文件内容：\n{context[:4000]}"
        store = _load_store(db, store_id)
        if store is not None:
            answer = _route_answer_store_manager(
                db=db,
                store_id=store_id,
                question=combined_question,
                shortcut_question=question.strip(),
                days=days,
                use_shortcuts=True,
            )
            result["answer"] = answer

    return _attach_runtime_context(store_id, db, result)


def _work_thread_question(question: str, db: Session, store_id: str, work_thread_id: str | None = None) -> str:
    hint_id = str(work_thread_id or "").strip()
    if not hint_id:
        return question
    loop = None
    try:
        from app.services.closed_loop import get_loop

        loop = get_loop(db, store_id, hint_id)
    except Exception:
        loop = None
    if loop is not None and loop.title:
        return f"当前继续同一经营事项「{loop.title}」。\n{question}"
    from app.models.thread import OperatingThread

    thread = db.get(OperatingThread, hint_id)
    if thread is not None and thread.store_id == store_id and thread.title:
        return f"当前继续同一经营线程「{thread.title}」。\n{question}"
    return question


def _route_answer_store_manager(
    *,
    db: Session,
    store_id: str,
    question: str,
    shortcut_question: str | None = None,
    days: int,
    use_shortcuts: bool,
    work_thread_id: str | None = None,
) -> dict[str, Any]:
    from app.services.ai_assist import answer_assist_question

    scoped_question = _work_thread_question(question, db, store_id, work_thread_id)
    shortcut_input = (shortcut_question or question or "").strip()

    # 第一道：产品引导类问题（部署/平台/设置/装修入口）由 ai_assist 拦截
    assisted = answer_assist_question(shortcut_input, db=db, store=_load_store(db, store_id)) if use_shortcuts else None
    if assisted is not None:
        return {
            "conclusion": assisted.get("conclusion"),
            "actions": assisted.get("actions") or [],
            "intent": assisted.get("intent"),
            "guide": assisted.get("guide"),
            "expected": None,
            "confidence": "high",
            "answer": assisted.get("conclusion"),
        }

    # 第二道：POIE Intent — 目标类指令直接落库 Goal + WorkThread
    from app.services.poie import handle_user_intent

    intent_hit = handle_user_intent(db, store_id, shortcut_input) if use_shortcuts else None
    if intent_hit is not None:
        return intent_hit

    # 第三道：经营类问题交给 chief_agent（ReAct 调度专业 agent）
    from app.services.chief_agent import answer_as_chief

    result = answer_as_chief(db, store_id, scoped_question, days=days).model_dump(mode="json")
    if work_thread_id:
        result["work_thread_id"] = work_thread_id
    return result


def _attach_runtime_context(store_id: str, db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.api.routes_runtime import _build_daily_plan_payload, _build_workspace_payload

    result = dict(payload)
    result["workspace"] = _build_workspace_payload(store_id, db)
    result["daily_plan"] = _build_daily_plan_payload(store_id, db)
    return result


@router.post("/stores/{store_id}/refresh")
def refresh_store_dashboard(
    store_id: str,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    result = run_daily_job(db=db, store_id=store_id, days=days)
    if result is None:
        raise HTTPException(status_code=404, detail="store not found")
    store = _load_store(db, store_id)
    return _build_dashboard_payload(db=db, store=store, days=days)


def _ensure_experiment(db: Session, rec: Recommendation) -> Experiment:
    stmt = select(Experiment).where(Experiment.recommendation_id == rec.id).limit(1)
    experiment = db.execute(stmt).scalar_one_or_none()
    if experiment is not None:
        return experiment

    state = build_store_state(db=db, store_id=rec.store_id, days=7)
    metric = state.kpis.get(rec.expected_metric) if state else None
    experiment = Experiment(
        recommendation_id=rec.id,
        store_id=rec.store_id,
        work_thread_id=rec.work_thread_id,
        item_id=rec.object_ref.split(":", 1)[1] if rec.object_ref.startswith("item:") else None,
        baseline_value=metric.observed_value if metric else None,
        observed_value=None,
        lift_pct=None,
        baseline_from=state.window.from_day if state else None,
        baseline_to=state.window.to_day if state else None,
        observe_from=None,
        observe_to=None,
        control_desc="V1 采用 pre/post 对照，等待执行后写回观察窗。",
        attribution_quality="medium",
        result="pending",
        notes="动作已进入验证队列，等待下一观察窗。",
    )
    db.add(experiment)
    return experiment


def _append_recommendation_feedback(rec: Recommendation, feedback: dict[str, Any]) -> None:
    payload = _json_loads_dict(rec.content_json)
    history = payload.get("feedback_history", [])
    if not isinstance(history, list):
        history = []
    history.append(feedback)
    payload["feedback_history"] = history
    rec.content_json = _json_dumps(payload)


@router.post("/recommendations/{recommendation_id}/adopt")
def adopt_recommendation(recommendation_id: str, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    if rec.status == "proposed":
        rec.status = "adopted"
        rec.adopted_at = datetime.now(timezone.utc)
        _append_recommendation_feedback(
            rec,
            {"status": "adopted", "at": rec.adopted_at.isoformat(), "message": "商家已采纳建议"},
        )
        db.commit()
        db.refresh(rec)
    return {"id": rec.id, "status": rec.status, "adopted_at": rec.adopted_at}


@router.post("/recommendations/{recommendation_id}/ignore")
def ignore_recommendation(recommendation_id: str, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    rec.status = "archived"
    _append_recommendation_feedback(
        rec,
        {"status": "ignored", "at": datetime.now(timezone.utc).isoformat(), "message": "商家本轮忽略该建议"},
    )
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "status": rec.status}


@router.post("/recommendations/{recommendation_id}/execute")
def execute_recommendation(recommendation_id: str, db: Session = Depends(get_db)):
    """Action Pipeline 薄入口。不能直接把 recommendation 标成 executed。"""
    from app.services.action_pipeline import ActionPipelineError, run_recommendation_pipeline

    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    now = datetime.now(timezone.utc)
    if rec.status == "proposed":
        rec.status = "adopted"
        rec.adopted_at = now

    try:
        pipeline = run_recommendation_pipeline(db, rec, actor="owner", approved=True)
    except ActionPipelineError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "stage": exc.stage, "message": str(exc), **exc.payload},
        ) from exc

    domain = pipeline.get("domain_execution") or {}
    _append_recommendation_feedback(
        rec,
        {
            "status": "executed",
            "at": now.isoformat(),
            "message": domain.get("detail") or "已在系统内执行",
            "domain_execution": domain,
            "pipeline": {"code": pipeline.get("code"), "stages": pipeline.get("stages")},
        },
    )
    experiment = _ensure_experiment(db, rec)
    db.commit()
    db.refresh(rec)
    db.refresh(experiment)
    return {
        "id": rec.id,
        "status": rec.status,
        "executed_at": rec.executed_at,
        "experiment_id": experiment.id,
        "domain_execution": domain,
        "pipeline": pipeline,
    }


@router.post("/recommendations/{recommendation_id}/no_effect")
def mark_recommendation_no_effect(recommendation_id: str, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    if rec.status != "executed":
        raise HTTPException(
            status_code=409,
            detail={"code": "MUST_EXECUTE_FIRST", "message": "只能对已通过 Action Pipeline 提交的动作反馈无效果。"},
        )
    experiment = _ensure_experiment(db, rec)
    experiment.result = "neutral"
    experiment.attribution_quality = "low"
    experiment.notes = "商家反馈本轮动作无明显效果，建议回到低风险动作重新测试。"
    _append_recommendation_feedback(
        rec,
        {"status": "no_effect", "at": datetime.now(timezone.utc).isoformat(), "message": "商家反馈当前动作无效果"},
    )
    db.add(experiment)
    db.commit()
    db.refresh(rec)
    db.refresh(experiment)
    return {"id": rec.id, "status": rec.status, "experiment_id": experiment.id, "result": experiment.result}


@router.get("/recommendations/{recommendation_id}/preview")
def preview_recommendation(recommendation_id: str, db: Session = Depends(get_db)):
    """P0-B: 执行预览——只读不写，产出 diff。"""
    from app.services.execution_plan import build_change_plan

    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    plan = build_change_plan(db, rec)
    return {
        "recommendation_id": rec.id,
        "mode": plan.mode,
        "action": plan.action,
        "diff": [{"field": c.field, "before": c.before, "after": c.after} for c in plan.changes],
        "detail": plan.detail,
        "expected": plan.expected,
        "reversible": plan.reversible,
        "platform_sync_required": plan.platform_sync_required,
        "confirm_hint": "确认后立即生效，可随时回滚" if plan.reversible else "确认后进入观察窗",
    }


@router.post("/recommendations/{recommendation_id}/rollback")
def rollback_recommendation_route(recommendation_id: str, db: Session = Depends(get_db)):
    """P0-B: 回滚已执行的系统内动作。"""
    from app.services.execution_plan import rollback_recommendation

    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    result = rollback_recommendation(db, rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, **result}


@router.post("/experiments/{experiment_id}/evaluate")
def evaluate_experiment(
    experiment_id: str,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    """手动评估实验。复用 experiment_attribution 服务，与 celery beat 自动归因同口径。

    手动调用默认 force=True（重算），便于商家在观察窗中途强制刷新。
    """
    from app.services.experiment_attribution import evaluate_experiment as _evaluate

    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    outcome = _evaluate(db, experiment, days=days, force=True)
    db.commit()
    db.refresh(experiment)
    return {
        "id": experiment.id,
        "result": experiment.result,
        "lift_pct": experiment.lift_pct,
        "observed_value": experiment.observed_value,
        "attribution_quality": experiment.attribution_quality,
        "notes": experiment.notes,
        "skipped": outcome.skipped,
        "reason": outcome.reason,
        # strategy_memory 已在 evaluate_experiment 内部 upsert
    }


@router.get("/stores/{store_id}/today-agenda")
def get_today_agenda(
    store_id: str,
    db: Session = Depends(get_db),
):
    """WP4a: 今日决策流时间线——节律 + 已跑 phase + 未读通知。"""
    from zoneinfo import ZoneInfo

    from app.services.decision_flow import PHASE_META, resolve_operating_phase
    from app.services.operating_rhythm import is_in_quiet_hours, resolve_store_rhythm

    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    day = now.strftime("%Y-%m-%d")
    hour = now.hour
    rhythm = resolve_store_rhythm(db, store_id)
    current_phase = resolve_operating_phase(rhythm, hour=hour)
    phase_meta = PHASE_META.get(current_phase) or {}

    # 节律驱动的计划时刻
    def _h(t: str) -> int:
        return int(t.split(":", 1)[0])

    lunch_start = _h(rhythm.lunch_peak_start)
    dinner_start = _h(rhythm.dinner_peak_start)
    schedule = [
        ("night_learn", 2),
        ("deep_review", 6),
        ("morning_readiness", max(lunch_start - 2, 7)),
        ("lunch_nba", lunch_start - 1),
        ("lunch_protect", lunch_start),
        ("lunch_review", _h(rhythm.lunch_peak_end)),
        ("dinner_strategy", dinner_start - 1),
        ("dinner_protect", dinner_start),
        ("evening_review", _h(rhythm.dinner_peak_end)),
    ]
    schedule = [(p, h) for p, h in schedule if 0 <= h < 24]

    # 查今日已跑标记
    keys = {f"clock_run:{store_id}:{day}:{p}" for p, _ in schedule}
    ran = {
        row[0]
        for row in db.execute(select(AppSetting.key).where(AppSetting.key.in_(keys))).all()
    }

    def _status(phase: str, at_hour: int) -> str:
        marker = f"clock_run:{store_id}:{day}:{phase}"
        if marker in ran:
            return "done"
        if phase == current_phase or (
            phase == "dinner_protect" and current_phase == "lunch_protect" and hour >= dinner_start
        ):
            return "now"
        if at_hour < hour and phase != current_phase:
            return "missed"
        return "upcoming"

    phases = [
        {
            "phase": p,
            "scheduled_hour": h,
            "scheduled_time": f"{h:02d}:00",
            "status": _status(p, h),
            "in_quiet_hours": is_in_quiet_hours(rhythm, h) if p not in ("night_learn", "deep_review") else False,
        }
        for p, h in schedule
    ]

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    notifications = (
        db.execute(
            select(Notification)
            .where(
                Notification.store_id == store_id,
                Notification.created_at >= today_start,
                Notification.read == False,  # noqa: E712
            )
            .order_by(Notification.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )

    return {
        "date": day,
        "hour": hour,
        "current_phase": current_phase,
        "phase_label": phase_meta.get("label") or current_phase,
        "clock_why": phase_meta.get("clock_why") or "",
        "interrupt_ok": bool(phase_meta.get("interrupt_ok")),
        "protect_mode": bool(phase_meta.get("protect")),
        "rhythm_source": rhythm.source,
        "quiet_hours": rhythm.quiet_hours,
        "phases": phases,
        "unread_notifications": [
            {
                "id": n.id,
                "type": n.notification_type,
                "title": n.title,
                "body": n.body,
                "priority": n.priority,
                "clock_phase": n.clock_phase,
                "created_at": n.created_at,
            }
            for n in notifications
        ],
    }


@router.post("/stores/{store_id}/connect-codes")
def create_mobile_connect_code(
    store_id: str,
    platform: str = Query(default="外卖平台"),
    db: Session = Depends(get_db),
):
    from app.services.connect_codes import create_connect_code

    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return create_connect_code(db, store_id, platform)


@router.get("/stores/{store_id}/connect-codes/{code}")
def get_mobile_connect_code(store_id: str, code: str, db: Session = Depends(get_db)):
    from app.services.connect_codes import get_connect_code

    payload = get_connect_code(db, store_id, code)
    if payload is None:
        raise HTTPException(status_code=404, detail="connect code not found")
    return payload


@router.get("/stores/{store_id}/platform-links")
def list_platform_links(store_id: str, db: Session = Depends(get_db)):
    from app.models.settings import PlatformConnection

    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    rows = db.execute(select(PlatformConnection).where(PlatformConnection.store_id == store_id)).scalars().all()
    return {
        "store_id": store_id,
        "links": [
            {
                "platform": row.platform,
                "status": row.status,
                "connector_mode": row.connector_mode,
                "external_store_id": row.external_store_id,
                "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
                "connected_at": row.connected_at.isoformat() if row.connected_at else None,
                "auth_expires_at": row.auth_expires_at.isoformat() if row.auth_expires_at else None,
            }
            for row in rows
        ],
    }


@router.post("/stores/{store_id}/platform-links/{code}/confirm")
def confirm_platform_link(store_id: str, code: str, db: Session = Depends(get_db)):
    from app.services.connect_codes import confirm_connect_code

    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    result = confirm_connect_code(db, store_id, code, store)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="connect code not found")
    if result.get("error") == "expired":
        raise HTTPException(status_code=410, detail="connect code expired")
    links = list_platform_links(store_id=store_id, db=db)["links"]
    return {"store_id": store_id, "link": result["link"], "links": links}
