from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    Menu,
    CompetitorMenuItem,
    CompetitorSnapshot,
    CompetitorStore,
    ItemFunnelDaily,
    MenuItem,
    MenuItemVersion,
    Store,
    StoreCompetitorWatch,
)
from app.models.ohre import Experiment, Hypothesis, Observation, Recommendation
from app.schemas.agents import (
    AdsAgentResult,
    AgentActionCreateResponse,
    AgentKey,
    AgentMeta,
    AgentWorkflowItem,
    CompetitionAgentResult,
    CompetitionChangeView,
    CompetitorBrief,
    CrmAgentResult,
    DiagnosisAgentResult,
    DiagnosisObservationView,
    GrowthActionView,
    GrowthAgentResult,
    GrowthOpportunityView,
    GrowthPlanStep,
    GrowthScoreFactors,
    MenuBundleApplyResponse,
    MenuBundleOpportunity,
    MenuCategorySummary,
    MenuCleanupApplyResponse,
    MenuCleanupCandidate,
    MenuAgentResult,
    MenuPatchApplyResponse,
    MenuPatchSuggestion,
    MenuPricingLadder,
    MenuRoleItem,
    ProductActionCreateResponse,
    ProductAgentResult,
    ProductCandidate,
    ProductHealthDimension,
    ProductRootCause,
    ProductSuggestion,
    PromoAgentResult,
    ReviewAgentResult,
    ServiceAgentResult,
    StoreAgentsResponse,
    StoreMatrixAgentResult,
    StorefrontActionCreateResponse,
    StorefrontAgentResult,
    StorefrontPriorityAction,
)
from app.services.matrix_agents import (
    MatrixAgentInput,
    build_ads_agent,
    build_crm_agent,
    build_promo_agent,
    build_review_agent,
    build_service_agent,
    build_store_matrix_agent,
    create_matrix_action,
)
from app.services.matrix_agents.common import annotate_action_gates
from app.services.profit_gate import evaluate_profit_gate
from app.services.strategy_memory import load_strategy_memory
from app.schemas.strategy_memory import StrategyMemorySnapshot
from app.services.storefront_diagnosis import (
    StorefrontInput,
    attach_storefront_queue,
    build_storefront_diagnosis,
    create_storefront_action as _create_storefront_action_record,
    prioritize_storefront_actions,
)
from app.services.storefront_ai import (
    assist_image_optimize,
    assist_storefront_decorate,
    enrich_action_with_ai,
)
from app.schemas.store_state import StoreState
from app.services.daily_job import run_daily_job
from app.services.diagnosis_analysis import (
    build_diagnosis_comparisons,
    build_diagnosis_root_causes,
    build_diagnosis_signals,
    build_market_comparison,
    diagnosis_score,
)
from app.services.document_alignment import build_document_alignment
from app.services.store_state import build_store_state
from app.services.agent_narrator import (
    narrate_diagnosis,
    narrate_growth,
    narrate_menu,
)
from app.services.action_feedback import find_recent_action_feedback


def _invalidate_context_cache(store_id: str) -> None:
    """动作执行后失效 context 缓存，避免读到过期数据。best-effort，失败不阻塞。"""
    try:
        from app.services.agent_context_cache import invalidate
        invalidate(store_id)
    except Exception:  # noqa: BLE001
        pass

AGENT_LABELS: dict[AgentKey, str] = {
    "competition": "商圈竞争洞察 Agent",
    "menu": "菜单智能分析 Agent",
    "product": "商品优化 Agent",
    "storefront": "线上装修诊断 Agent",
    "diagnosis": "经营诊断 Agent",
    "growth": "增长策略 Agent",
    "promo": "平台活动 Agent",
    "ads": "投流 Agent",
    "crm": "用户关系 Agent",
    "service": "AI 客服 Agent",
    "review": "评分评价 Agent",
    "store_matrix": "线上门店增长 Agent",
}

ACTION_HISTORY_DAYS = 21


@dataclass
class _ItemSnapshot:
    item_id: str
    name: str
    category: Optional[str]
    price: Optional[float]
    description: Optional[str]
    observe_orders: float
    observe_gmv: float
    observe_impressions: float
    observe_visits: float
    observe_ctr: Optional[float]
    observe_cvr: Optional[float]
    baseline_orders: float
    baseline_impressions: float
    baseline_visits: float
    baseline_ctr: Optional[float]
    baseline_cvr: Optional[float]
    orders_delta_pct: Optional[float]
    impressions_delta_pct: Optional[float]
    order_share_pct: Optional[float]
    ctr_delta_pct: Optional[float]
    cvr_delta_pct: Optional[float]
    image_url: Optional[str] = None
    role: str = "Experimental Product"
    rationale: str = ""


@dataclass
class _AgentContext:
    store: Store
    store_state: StoreState
    document_alignment: dict[str, Any]
    observations: list[Observation]
    hypothesis: Optional[Hypothesis]
    recommendations: list[Recommendation]
    experiments: list[Experiment]
    menu_items: list[dict[str, Any]]
    item_snapshots: list[_ItemSnapshot]
    generated_at: datetime
    days: int
    system_mode: str = "operating"  # operating / safe（MOS + Safe Mode）


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


def _store_query():
    return select(Store).options(
        selectinload(Store.merchant),
        selectinload(Store.items).selectinload(MenuItem.current_version),
    )


def _load_store(db: Session, store_id: str) -> Store | None:
    return db.execute(_store_query().where(Store.id == store_id)).scalar_one_or_none()


def _menu_items(store: Store) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in store.items:
        if not item.is_active:
            continue
        current = item.current_version
        items.append(
            {
                "item_id": item.id,
                "name": current.name if current else "未命名商品",
                "category": current.category if current else None,
                "price": current.price if current else None,
                "description": current.description if current else None,
                "image_url": current.image_url if current else None,
                "is_active": item.is_active,
            }
        )
    return items


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


def _document_blockers(ctx: _AgentContext) -> list[str]:
    alignment = ctx.document_alignment or {}
    status = alignment.get("status")
    if status == "conflict":
        return ["资料口径冲突，先统一主数据和原始资料，再继续经营判断。"]
    if status == "missing_documents":
        return ["缺少原始资料，当前只能基于经营数据做保守判断。"]
    if status == "partial":
        return ["资料证据还不完整，建议补齐关键字段后再放大动作。"]
    return []


def _alignment_readiness(ctx: _AgentContext) -> str:
    status = (ctx.document_alignment or {}).get("status")
    return {
        "aligned": "ready",
        "partial": "partial",
        "missing_documents": "limited",
        "conflict": "blocked",
        "missing_store": "blocked",
    }.get(status, "partial")


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


def _document_menu_gaps(ctx: _AgentContext) -> list[str]:
    candidate_names = {_normalize_text(row.get("name")): row for row in (ctx.document_alignment or {}).get("menu_candidates", [])}
    structured_names = {_normalize_text(row.get("name")) for row in ctx.menu_items}
    missing_in_system = [row["name"] for key, row in candidate_names.items() if key and key not in structured_names]
    if not missing_in_system:
        return []
    return [f"文档里出现了 {name}，但结构化菜单里还没有录入。" for name in missing_in_system[:3]]


def _menu_category_summary(items: list[_ItemSnapshot]) -> list[MenuCategorySummary]:
    grouped: dict[str, list[_ItemSnapshot]] = {}
    for item in items:
        category = item.category or "未分类"
        grouped.setdefault(category, []).append(item)

    summaries: list[MenuCategorySummary] = []
    for category, rows in grouped.items():
        prices = [float(row.price) for row in rows if row.price is not None]
        role_counts: dict[str, int] = {}
        for row in rows:
            role_counts[row.role] = role_counts.get(row.role, 0) + 1
        sorted_roles = sorted(role_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        if role_counts.get("Zombie SKU", 0) >= max(1, len(rows) // 2):
            note = "低效 SKU 偏多，建议先清理陈列。"
        elif role_counts.get("Hero Product", 0) == 0 and len(rows) >= 2:
            note = "这个类目还缺主推款，难形成稳定心智。"
        elif role_counts.get("Basket Builder", 0) and role_counts.get("Hero Product", 0):
            note = "适合围绕主推款补套餐承接。"
        else:
            note = "结构基本可用，可继续微调排序和表达。"
        summaries.append(
            MenuCategorySummary(
                category=category,
                item_count=len(rows),
                avg_price=round(sum(prices) / len(prices), 2) if prices else None,
                top_roles=[role for role, _ in sorted_roles[:2]],
                health_note=note,
            )
        )
    summaries.sort(key=lambda row: (-row.item_count, row.category))
    return summaries[:4]


def _menu_pricing_ladder(items: list[_ItemSnapshot]) -> MenuPricingLadder:
    prices = [float(item.price) for item in items if item.price is not None]
    if not prices:
        return MenuPricingLadder(gap_note="还没有有效价格数据，暂时无法判断价格梯度。")

    avg_price = sum(prices) / len(prices)
    low_threshold = avg_price * 0.85
    high_threshold = avg_price * 1.15
    low_band_count = sum(1 for price in prices if price <= low_threshold)
    high_band_count = sum(1 for price in prices if price >= high_threshold)
    mid_band_count = max(0, len(prices) - low_band_count - high_band_count)

    gap_note = None
    if low_band_count == 0:
        gap_note = "缺少低门槛引流价格带，第一波点击承接会偏弱。"
    elif high_band_count == 0:
        gap_note = "缺少利润价格带，容易只剩价格竞争。"
    elif mid_band_count <= 1 and len(prices) >= 4:
        gap_note = "中间价格带过薄，用户从引流款到利润款的过渡不顺。"
    else:
        gap_note = "价格梯度基本完整，可以先通过套餐和排序放大效果。"

    return MenuPricingLadder(
        anchor_min=min(prices),
        anchor_max=max(prices),
        low_band_count=low_band_count,
        mid_band_count=mid_band_count,
        high_band_count=high_band_count,
        gap_note=gap_note,
    )


def _menu_bundle_priority(
    attach: _ItemSnapshot,
    recent_role_feedback: dict[str, dict[str, Any]],
    recent_menu_actions: dict[str, dict[str, Any]],
) -> float:
    score = 0.0
    role_bias = {
        "Basket Builder": 24.0,
        "Traffic Product": 18.0,
        "Profit Product": 16.0,
    }
    score += role_bias.get(attach.role, 8.0)
    score += min(18.0, float(attach.observe_orders or 0) * 1.8)
    score += min(12.0, float(attach.order_share_pct or 0) * 0.6)
    if attach.observe_cvr is not None:
        score += min(10.0, attach.observe_cvr * 40.0)

    role_feedback = recent_role_feedback.get(attach.role)
    if role_feedback:
        if role_feedback.get("action_type") == "menu_cleanup":
            score -= 18.0
        elif role_feedback.get("in_observation"):
            score -= 10.0
        elif role_feedback.get("experiment_result") == "positive":
            score += 12.0
        elif role_feedback.get("experiment_result") == "negative":
            score -= 10.0
        elif role_feedback.get("experiment_result") == "neutral":
            score -= 4.0

    item_feedback = recent_menu_actions.get(attach.item_id)
    if item_feedback:
        if item_feedback.get("action_type") == "menu_cleanup":
            score -= 24.0
        elif item_feedback.get("in_observation"):
            score -= 12.0
        elif item_feedback.get("experiment_result") == "positive":
            score += 8.0
        elif item_feedback.get("experiment_result") == "negative":
            score -= 8.0
        elif item_feedback.get("experiment_result") == "neutral":
            score -= 3.0
    return score


def _menu_bundle_opportunities(ctx: _AgentContext, items: list[_ItemSnapshot]) -> list[MenuBundleOpportunity]:
    heroes = [item for item in items if item.role == "Hero Product"]
    attach_candidates = [item for item in items if item.role in {"Basket Builder", "Traffic Product", "Profit Product"}]
    recent_role_feedback = _recent_menu_role_feedback(ctx)
    recent_menu_actions = _recent_menu_action_state(ctx)
    opportunities: list[MenuBundleOpportunity] = []
    used_pairs: set[tuple[str, str]] = set()

    for hero in heroes[:2]:
        ranked_attach_candidates = sorted(
            attach_candidates,
            key=lambda row: _menu_bundle_priority(row, recent_role_feedback, recent_menu_actions),
            reverse=True,
        )
        for attach in ranked_attach_candidates:
            if attach.item_id == hero.item_id:
                continue
            pair = (hero.item_id, attach.item_id)
            if pair in used_pairs:
                continue
            item_feedback = recent_menu_actions.get(attach.item_id)
            if item_feedback and item_feedback.get("action_type") == "menu_cleanup":
                continue
            used_pairs.add(pair)
            if attach.role == "Basket Builder":
                reason = f"{hero.name} 已有主推势能，搭配 {attach.name} 更适合抬客单。"
                outcome = "优先承接犹豫用户，提升套餐点击和连带购买。"
            elif attach.role == "Traffic Product":
                reason = f"{attach.name} 决策成本更低，适合给 {hero.name} 补一个更轻的入口。"
                outcome = "先把用户拉进来，再把流量导到主推款。"
            else:
                reason = f"{attach.name} 更接近利润款，可和 {hero.name} 形成更稳的价值锚点。"
                outcome = "改善套餐价值感，避免只拼低价。"
            role_feedback = recent_role_feedback.get(attach.role)
            if role_feedback and role_feedback.get("experiment_result") == "positive":
                outcome = f"{outcome} 最近同类结构验证过有效，可以优先放大。"
            elif item_feedback and item_feedback.get("in_observation"):
                outcome = f"{outcome} 但 {attach.name} 仍在观察窗内，建议只作为次优组合。"
            opportunities.append(
                MenuBundleOpportunity(
                    primary_item_id=hero.item_id,
                    primary_item_name=hero.name,
                    attach_item_id=attach.item_id,
                    attach_item_name=attach.name,
                    reason=reason,
                    expected_outcome=outcome,
                )
            )
            break
    return opportunities[:3]


def _menu_cleanup_priority(item: _ItemSnapshot, recent_action: dict[str, Any] | None) -> float:
    score = 0.0
    if item.order_share_pct is not None:
        score += max(0.0, 12.0 - float(item.order_share_pct))
    score += max(0.0, 4.0 - float(item.observe_orders)) * 6.0
    if item.ctr_delta_pct is not None and item.ctr_delta_pct < 0:
        score += min(18.0, abs(float(item.ctr_delta_pct)) * 0.45)
    if recent_action:
        if recent_action.get("in_observation"):
            score -= 26.0
        elif recent_action.get("experiment_result") == "positive":
            score -= 22.0
        elif recent_action.get("experiment_result") == "neutral":
            score -= 6.0
        elif recent_action.get("experiment_result") == "negative":
            score += 14.0
    return score


def _menu_cleanup_candidates(ctx: _AgentContext, items: list[_ItemSnapshot]) -> list[MenuCleanupCandidate]:
    recent_menu_actions = _recent_menu_action_state(ctx)
    candidates: list[MenuCleanupCandidate] = []
    for item in items:
        recent_action = recent_menu_actions.get(item.item_id)
        if recent_action and (
            recent_action.get("in_observation")
            or recent_action.get("experiment_result") == "positive"
        ):
            continue
        low_share = item.order_share_pct is not None and item.order_share_pct < 5
        low_orders = item.observe_orders <= 2
        if item.role != "Zombie SKU" and not (low_share and low_orders):
            continue
        reason_bits: list[str] = []
        if item.order_share_pct is not None:
            reason_bits.append(f"订单占比 {item.order_share_pct:.1f}%")
        if item.ctr_delta_pct is not None:
            reason_bits.append(f"CTR 变化 {item.ctr_delta_pct:.1f}%")
        if recent_action and recent_action.get("experiment_result") == "negative":
            reason_bits.append("最近同项测试结果偏弱")
        reason = "，".join(reason_bits) if reason_bits else item.rationale or "持续低效"
        action = "先降权观察，再决定是否下架。"
        if item.observe_orders <= 1 and (item.order_share_pct is None or item.order_share_pct < 3):
            action = "可以优先进入下架测试名单。"
        if recent_action and recent_action.get("experiment_result") == "negative":
            action = "最近测试已经证明承接偏弱，可以优先进入下架测试名单。"
        candidates.append(
            MenuCleanupCandidate(
                item_id=item.item_id,
                name=item.name,
                role=item.role,
                reason=reason,
                action=action,
            )
        )
    candidates.sort(
        key=lambda row: _menu_cleanup_priority(
            next(item for item in items if item.item_id == row.item_id),
            recent_menu_actions.get(row.item_id),
        ),
        reverse=True,
    )
    return candidates[:3]


def _menu_workflow(ctx: _AgentContext) -> tuple[list[AgentWorkflowItem], AgentWorkflowItem | None]:
    experiment_map = _experiment_map(ctx)
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    queue = sorted(
        [
        _workflow_item(rec, experiment_map, item_names)
        for rec in ctx.recommendations
        if rec.action_type in {"add_set_meal", "menu_patch", "menu_cleanup"}
        ],
        key=_workflow_phase_rank,
    )[:3]
    return queue, _current_action(queue)


def _ensure_active_menu(db: Session, store_id: str) -> Menu:
    stmt = (
        select(Menu)
        .where(Menu.store_id == store_id, Menu.status == "active")
        .order_by(Menu.version.desc(), Menu.created_at.desc())
        .limit(1)
    )
    menu = db.execute(stmt).scalar_one_or_none()
    if menu is not None:
        return menu
    menu = Menu(store_id=store_id, name="默认菜单", type="delivery", version=1, status="active")
    db.add(menu)
    db.flush()
    return menu


def _menu_patch_action_type(patch: MenuPatchSuggestion) -> str:
    if patch.patch_type == "create_bundle" or patch.target_role == "Basket Builder":
        return "add_set_meal"
    return "menu_patch"


def _menu_patch_expected_metric(patch: MenuPatchSuggestion) -> str:
    if patch.target_role == "Traffic Product":
        return "ctr"
    if patch.target_role in {"Basket Builder", "Profit Product"}:
        return "cvr"
    return "orders"


def _menu_patch_rollback_rule(patch: MenuPatchSuggestion) -> str:
    if patch.target_role == "Traffic Product":
        return "观察 72 小时 CTR；若无改善则下调该新入口权重。"
    if patch.target_role == "Basket Builder":
        return "观察 7 天套餐点击与连带单；若无改善则撤回套餐。"
    if patch.target_role == "Profit Product":
        return "观察 7 天利润款承接；若无改善则回到基础款结构。"
    return "观察 7 天订单与点击；若无改善则回到原结构。"


def _menu_cleanup_rollback_rule() -> str:
    return "观察 7 天整体转化和订单结构；若无改善则恢复该 SKU 上架。"


def _bundle_target_price(opportunity: MenuBundleOpportunity, ctx: _AgentContext) -> Optional[float]:
    price_lookup = {row["item_id"]: row.get("price") for row in ctx.menu_items}
    primary_price = price_lookup.get(opportunity.primary_item_id) if opportunity.primary_item_id else None
    attach_price = price_lookup.get(opportunity.attach_item_id) if opportunity.attach_item_id else None
    if primary_price is None and attach_price is None:
        return None
    total = float(primary_price or 0) + float(attach_price or 0)
    return round(total * 0.92, 2)


def _recent_menu_action_state(ctx: _AgentContext) -> dict[str, dict[str, Any]]:
    cutoff = ctx.generated_at - timedelta(days=14)
    experiment_map = _experiment_map(ctx)
    latest_by_item: dict[str, dict[str, Any]] = {}
    for rec in ctx.recommendations:
        if not rec.object_ref.startswith("item:"):
            continue
        if rec.action_type not in {"menu_patch", "menu_cleanup", "add_set_meal"}:
            continue
        event_at = _as_utc(rec.executed_at or rec.adopted_at or rec.created_at)
        if event_at is None or event_at < cutoff or rec.status == "archived":
            continue
        item_id = rec.object_ref.split(":", 1)[1]
        payload = _json_loads_dict(rec.content_json)
        experiment = experiment_map.get(rec.id)
        experiment_result = experiment.result if experiment else None
        in_observation, _ = _recommendation_in_observation(rec, experiment, ctx.generated_at)
        observe_until = event_at + timedelta(hours=rec.window_hours or 168)
        record = {
            "action_type": rec.action_type,
            "status": rec.status,
            "executed_at": event_at,
            "experiment_result": experiment_result,
            "observe_until": observe_until,
            "in_observation": in_observation,
            "menu_patch": payload.get("menu_patch"),
            "menu_bundle": payload.get("menu_bundle"),
            "menu_cleanup": payload.get("menu_cleanup"),
        }
        current = latest_by_item.get(item_id)
        if current is None or event_at > current["executed_at"]:
            latest_by_item[item_id] = record
    return latest_by_item


def _recent_menu_target_names(ctx: _AgentContext) -> set[str]:
    names: set[str] = set()
    cutoff = ctx.generated_at - timedelta(days=ACTION_HISTORY_DAYS)
    for rec in ctx.recommendations:
        if rec.action_type not in {"menu_patch", "menu_cleanup", "add_set_meal"}:
            continue
        event_at = _as_utc(rec.executed_at or rec.adopted_at or rec.created_at)
        if event_at is None or event_at < cutoff or rec.status == "archived":
            continue
        payload = _json_loads_dict(rec.content_json)
        if isinstance(payload.get("menu_patch"), dict) and payload["menu_patch"].get("item_name"):
            names.add(_normalize_text(payload["menu_patch"]["item_name"]))
        if isinstance(payload.get("menu_cleanup"), dict) and payload["menu_cleanup"].get("name"):
            names.add(_normalize_text(payload["menu_cleanup"]["name"]))
        if isinstance(payload.get("menu_bundle"), dict):
            primary = payload["menu_bundle"].get("primary_item_name")
            attach = payload["menu_bundle"].get("attach_item_name")
            if primary and attach:
                names.add(_normalize_text(f"{primary}+{attach}套餐"))
    return {name for name in names if name}


def _menu_role_label(role: str) -> str:
    labels = {
        "Hero Product": "主推款",
        "Traffic Product": "引流款",
        "Profit Product": "利润款",
        "Basket Builder": "搭配品",
        "Zombie SKU": "低效 SKU",
        "Experimental Product": "观察位 SKU",
    }
    return labels.get(role, role)


def _menu_action_role(rec: Recommendation, payload: dict[str, Any]) -> str | None:
    menu_patch = payload.get("menu_patch")
    if isinstance(menu_patch, dict) and menu_patch.get("target_role"):
        return str(menu_patch["target_role"])
    menu_cleanup = payload.get("menu_cleanup")
    if isinstance(menu_cleanup, dict) and menu_cleanup.get("role"):
        return str(menu_cleanup["role"])
    if isinstance(payload.get("menu_bundle"), dict) or rec.action_type == "add_set_meal":
        return "Basket Builder"
    return None


def _recent_menu_origin_role(
    ctx: _AgentContext,
    object_ref: str,
    before_at: datetime,
) -> str | None:
    latest_role = None
    latest_at = None
    for rec in ctx.recommendations:
        if rec.object_ref != object_ref or rec.status == "archived":
            continue
        event_at = _as_utc(rec.executed_at or rec.adopted_at or rec.created_at)
        if event_at is None or event_at >= before_at:
            continue
        role = _menu_action_role(rec, _json_loads_dict(rec.content_json))
        if not role or role == "Zombie SKU":
            continue
        if latest_at is None or event_at > latest_at:
            latest_role = role
            latest_at = event_at
    return latest_role


def _recent_menu_role_feedback(ctx: _AgentContext) -> dict[str, dict[str, Any]]:
    experiment_map = _experiment_map(ctx)
    cutoff = ctx.generated_at - timedelta(days=ACTION_HISTORY_DAYS)
    latest_by_role: dict[str, dict[str, Any]] = {}
    for rec in ctx.recommendations:
        if rec.action_type not in {"menu_patch", "menu_cleanup", "add_set_meal"}:
            continue
        event_at = _as_utc(rec.executed_at or rec.adopted_at or rec.created_at)
        if event_at is None or event_at < cutoff or rec.status == "archived":
            continue
        payload = _json_loads_dict(rec.content_json)
        target_role = _menu_action_role(rec, payload)
        if rec.action_type == "menu_cleanup" and target_role == "Zombie SKU" and rec.object_ref.startswith("item:"):
            target_role = _recent_menu_origin_role(ctx, rec.object_ref, event_at) or target_role
        if not target_role:
            continue
        experiment = experiment_map.get(rec.id)
        experiment_result = experiment.result if experiment else None
        in_observation, _ = _recommendation_in_observation(rec, experiment, ctx.generated_at)
        observe_until = event_at + timedelta(hours=rec.window_hours or 168)
        note = None
        suppress_gap = False
        if rec.action_type == "menu_cleanup":
            note = f"最近刚清理过{_menu_role_label(target_role)}相关 SKU，先看清理后整体承接。"
            suppress_gap = True
        elif in_observation:
            note = f"最近刚上线{_menu_role_label(target_role)}测试，先等观察窗再决定是否继续补。"
            suppress_gap = True
        elif experiment_result == "negative":
            note = f"最近试过{_menu_role_label(target_role)}动作但效果偏弱，先复盘再重复上新。"
            suppress_gap = True
        current = latest_by_role.get(target_role)
        if current is None or event_at > current["event_at"]:
            latest_by_role[target_role] = {
                "role": target_role,
                "action_type": rec.action_type,
                "status": rec.status,
                "experiment_result": experiment_result,
                "event_at": event_at,
                "observe_until": observe_until,
                "in_observation": in_observation,
                "suppress_gap": suppress_gap,
                "note": note,
            }
    return latest_by_role


def _menu_gap_profile(ctx: _AgentContext, items: list[_ItemSnapshot]) -> tuple[dict[str, int], list[str], list[str], dict[str, dict[str, Any]]]:
    role_distribution: dict[str, int] = {}
    for item in items:
        role_distribution[item.role] = role_distribution.get(item.role, 0) + 1

    recent_role_feedback = _recent_menu_role_feedback(ctx)
    gaps: list[str] = []
    deferred_notes: list[str] = []
    role_gap_map = {
        "Traffic Product": "缺少明确引流款，第一波点击承接偏弱。",
        "Basket Builder": "缺少搭配品，客单和套餐承接空间不足。",
        "Profit Product": "利润款不够明显，结构容易被爆品牵着走。",
    }
    for role, gap in role_gap_map.items():
        if role_distribution.get(role, 0):
            continue
        feedback = recent_role_feedback.get(role)
        if feedback and feedback.get("suppress_gap"):
            if feedback.get("note"):
                deferred_notes.append(str(feedback["note"]))
            continue
        gaps.append(gap)

    if role_distribution.get("Zombie SKU", 0) >= max(2, len(items) // 3 or 1):
        gaps.append("低效 SKU 偏多，首页和菜单结构会被稀释。")
    if len(items) < 3:
        gaps.append("菜单过窄，难以覆盖不同消费场景。")
    return role_distribution, gaps, list(dict.fromkeys(deferred_notes))[:3], recent_role_feedback


def _menu_pricing_gap_note(
    pricing_ladder: MenuPricingLadder,
    recent_role_feedback: dict[str, dict[str, Any]],
) -> str | None:
    note = pricing_ladder.gap_note
    if not note:
        return None
    if "低门槛引流价格带" in note and recent_role_feedback.get("Traffic Product", {}).get("suppress_gap"):
        return None
    if "利润价格带" in note and recent_role_feedback.get("Profit Product", {}).get("suppress_gap"):
        return None
    return note


def _menu_feedback_action_note(feedback: dict[str, Any]) -> str | None:
    role_label = _menu_role_label(str(feedback.get("role") or "该结构位"))
    if feedback.get("action_type") == "menu_cleanup":
        return f"最近刚清理过{role_label}相关 SKU，先看清理后整体承接。"
    if feedback.get("in_observation"):
        return f"最近刚上线{role_label}测试，先等观察窗再决定是否继续补。"
    result = feedback.get("experiment_result")
    if result == "positive":
        return f"最近验证过{role_label}结构有效，可以继续放大同类动作。"
    if result == "neutral":
        return f"最近验证过{role_label}结构，但效果一般，先避免重复堆同类 SKU。"
    if result == "negative":
        return f"最近试过{role_label}动作但效果偏弱，先复盘再重复上新。"
    return None


def _menu_role_strategy_notes(recent_role_feedback: dict[str, dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for role in ("Traffic Product", "Basket Builder", "Profit Product"):
        feedback = recent_role_feedback.get(role)
        if not feedback:
            continue
        note = _menu_feedback_action_note(feedback)
        if note:
            notes.append(note)
    return list(dict.fromkeys(notes))[:3]


def _menu_patch_priority(
    patch: MenuPatchSuggestion,
    gaps: list[str],
    recent_role_feedback: dict[str, dict[str, Any]],
) -> float:
    score = float(patch.evidence_count or 0)
    role_gap_bonus = {
        "Traffic Product": 28.0 if any("引流款" in gap for gap in gaps) else 0.0,
        "Basket Builder": 28.0 if any("搭配品" in gap for gap in gaps) else 0.0,
        "Profit Product": 28.0 if any("利润款" in gap for gap in gaps) else 0.0,
    }
    score += role_gap_bonus.get(patch.target_role, 0.0)
    patch_bias = {
        "create_bundle": 7.0,
        "derive_premium_bundle": 6.0,
        "create_sku": 5.0,
        "derive_entry_sku": 4.0,
    }
    score += patch_bias.get(patch.patch_type, 0.0)

    feedback = recent_role_feedback.get(patch.target_role)
    if not feedback:
        return score
    if feedback.get("action_type") == "menu_cleanup":
        return score - 18.0
    if feedback.get("in_observation"):
        return score - 14.0
    result = feedback.get("experiment_result")
    if result == "positive":
        return score + 16.0
    if result == "neutral":
        return score - 6.0
    if result == "negative":
        return score - 12.0
    return score


def _menu_patch_suggestions(
    ctx: _AgentContext,
    items: list[_ItemSnapshot],
    pricing_ladder: MenuPricingLadder,
    gaps: list[str],
) -> list[MenuPatchSuggestion]:
    suggestions: list[MenuPatchSuggestion] = []
    structured_names = {_normalize_text(row.get("name")) for row in ctx.menu_items}
    recent_target_names = _recent_menu_target_names(ctx)
    recent_role_feedback = _recent_menu_role_feedback(ctx)
    categories = [item.category for item in items if item.category]
    default_category = categories[0] if categories else "待归类"
    avg_price_values = [float(item.price) for item in items if item.price is not None]
    avg_price = sum(avg_price_values) / len(avg_price_values) if avg_price_values else None

    for candidate in (ctx.document_alignment or {}).get("menu_candidates", [])[:6]:
        normalized = _normalize_text(candidate.get("name"))
        if not normalized or normalized in structured_names or normalized in recent_target_names:
            continue
        candidate_price = float(candidate["price"]) if candidate.get("price") is not None else None
        name = str(candidate.get("name") or "待补录商品")
        if any(token in name for token in ("套餐", "组合", "双人", "单人餐")):
            target_role = "Basket Builder"
            patch_type = "create_bundle"
            expected_outcome = "补一条更低决策成本的套餐入口，承接犹豫用户。"
        elif candidate_price is not None and avg_price is not None and candidate_price <= avg_price * 0.85:
            target_role = "Traffic Product"
            patch_type = "create_sku"
            expected_outcome = "补齐低门槛价格带，先把用户拉进来。"
        elif candidate_price is not None and avg_price is not None and candidate_price >= avg_price * 1.15:
            target_role = "Profit Product"
            patch_type = "create_sku"
            expected_outcome = "补齐利润价格带，避免只剩低价竞争。"
        else:
            target_role = "Experimental Product"
            patch_type = "create_sku"
            expected_outcome = "先作为候选 SKU 补录，再看是否值得进入主推位。"
        suggestions.append(
            MenuPatchSuggestion(
                patch_type=patch_type,
                target_role=target_role,
                item_name=name,
                suggested_category=default_category,
                suggested_price=candidate_price,
                reason=f"文档里已出现 {name}，但结构化菜单里还没有录入；当前证据 {candidate.get('evidence_count', 0)} 条。",
                expected_outcome=expected_outcome,
                evidence_count=int(candidate.get("evidence_count") or 0),
                sources=[str(row) for row in (candidate.get("sources") or [])[:3]],
            )
        )

    if not any(row.target_role == "Traffic Product" for row in suggestions) and any("引流款" in gap for gap in gaps):
        hero = next((item for item in items if item.role == "Hero Product"), items[0] if items else None)
        fallback_price = round((avg_price or hero.price or 0) * 0.78, 2) if (avg_price or (hero and hero.price)) else None
        derived_name = f"{hero.name} 轻量版" if hero else "低门槛引流款"
        if _normalize_text(derived_name) not in recent_target_names:
            suggestions.append(
                MenuPatchSuggestion(
                    patch_type="derive_entry_sku",
                    target_role="Traffic Product",
                    item_name=derived_name,
                    suggested_category=hero.category if hero and hero.category else default_category,
                    suggested_price=fallback_price,
                    reason="当前缺少明确引流款，需要从现有主推款衍生一个更低门槛入口。",
                    expected_outcome="先补齐第一波点击承接，再把流量导向主推款。",
                )
            )
    if not any(row.target_role == "Profit Product" for row in suggestions) and pricing_ladder.high_band_count == 0 and items:
        hero = next((item for item in items if item.role == "Hero Product"), items[0])
        base_price = hero.price if hero.price is not None else avg_price
        premium_name = f"{hero.name} 升级套餐"
        if _normalize_text(premium_name) not in recent_target_names:
            suggestions.append(
                MenuPatchSuggestion(
                    patch_type="derive_premium_bundle",
                    target_role="Profit Product",
                    item_name=premium_name,
                    suggested_category=hero.category or default_category,
                    suggested_price=round(base_price * 1.18, 2) if base_price is not None else None,
                    reason="当前缺少利润价格带，可以围绕主推款做价值升级版本。",
                    expected_outcome="建立更稳的价格锚点，减少只拼低价的压力。",
                )
            )
    suggestions.sort(
        key=lambda row: (
            _menu_patch_priority(row, gaps, recent_role_feedback),
            row.evidence_count,
            row.item_name,
        ),
        reverse=True,
    )
    return suggestions[:4]


def _workflow_generated_content(rec: Recommendation, object_name: str) -> dict[str, Any]:
    payload = _json_loads_dict(rec.content_json)
    base = {
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
    }.get(rec.action_type, {})
    if rec.action_type in {"menu_patch", "menu_cleanup", "add_set_meal"}:
        review_note = payload.get("review_note") or _menu_action_review_note(rec.action_type, payload)
        observe_focus = payload.get("observe_focus") or _menu_action_observe_focus(rec.action_type, payload)
        if review_note:
            payload["review_note"] = review_note
        if observe_focus:
            payload["observe_focus"] = observe_focus
    if isinstance(payload.get("feedback_history"), list) and payload["feedback_history"]:
        payload["feedback_count"] = len(payload["feedback_history"])
    return {**base, **payload}


def _menu_action_review_note(action_type: str, payload: dict[str, Any]) -> str | None:
    menu_patch = payload.get("menu_patch")
    menu_cleanup = payload.get("menu_cleanup")
    menu_bundle = payload.get("menu_bundle")
    if action_type == "menu_patch" and isinstance(menu_patch, dict):
        role_label = _menu_role_label(str(menu_patch.get("target_role") or "观察位 SKU"))
        item_name = str(menu_patch.get("item_name") or "该菜单项")
        return f"这次先推 {item_name}，因为它对应当前最缺的{role_label}结构位。"
    if action_type == "menu_cleanup" and isinstance(menu_cleanup, dict):
        item_name = str(menu_cleanup.get("name") or "该 SKU")
        return f"这次先处理 {item_name}，因为它已经持续低效，继续占坑只会稀释菜单承接。"
    if action_type == "add_set_meal" and isinstance(menu_bundle, dict):
        primary = str(menu_bundle.get("primary_item_name") or "主推 SKU")
        attach = str(menu_bundle.get("attach_item_name") or "搭配品")
        return f"这次先补 {primary}+{attach} 套餐，因为它最适合承接犹豫用户并放大现有主推势能。"
    if action_type == "add_set_meal" and isinstance(menu_patch, dict):
        item_name = str(menu_patch.get("item_name") or "该套餐")
        return f"这次先补 {item_name}，因为它能先填上套餐承接位，再验证是否值得长期保留。"
    return None


def _menu_action_observe_focus(action_type: str, payload: dict[str, Any]) -> list[str]:
    menu_patch = payload.get("menu_patch")
    menu_cleanup = payload.get("menu_cleanup")
    menu_bundle = payload.get("menu_bundle")
    if action_type == "menu_patch" and isinstance(menu_patch, dict):
        target_role = str(menu_patch.get("target_role") or "Experimental Product")
        item_name = str(menu_patch.get("item_name") or "该菜单项")
        if target_role == "Traffic Product":
            return [f"看 {item_name} 的 CTR 和首屏点击承接", "看主推款是否被导流放大", "72 小时后决定是否保留引流入口"]
        if target_role in {"Basket Builder", "Profit Product"}:
            return [f"看 {item_name} 的 CVR 和连带单", "看是否抬升整体客单与价格锚点", "7 天后决定是否继续放大"]
        return [f"看 {item_name} 的订单和点击是否稳定", "看它是否值得从观察位进入常规结构", "7 天后再决定是否保留"]
    if action_type == "menu_cleanup" and isinstance(menu_cleanup, dict):
        item_name = str(menu_cleanup.get("name") or "该 SKU")
        return [f"看停用 {item_name} 后整体 CVR 是否回升", "看主推款和核心套餐是否承接更多流量", "7 天后决定是否恢复或永久移除"]
    if action_type == "add_set_meal" and isinstance(menu_bundle, dict):
        primary = str(menu_bundle.get("primary_item_name") or "主推 SKU")
        attach = str(menu_bundle.get("attach_item_name") or "搭配品")
        return [f"看 {primary}+{attach} 套餐点击率", "看连带单和整体 CVR 是否上升", "7 天后决定是否继续放大套餐入口"]
    if action_type == "add_set_meal" and isinstance(menu_patch, dict):
        item_name = str(menu_patch.get("item_name") or "该套餐")
        return [f"看 {item_name} 的套餐点击和连带单", "看是否带动整体 CVR 和客单", "7 天后决定是否继续放大套餐入口"]
    return []


def _workflow_next_decision(rec: Recommendation, experiment: Experiment | None) -> str:
    payload = _json_loads_dict(rec.content_json)
    if rec.status == "proposed":
        return "先确认是否采纳，再进入执行。"
    if rec.status == "adopted":
        return "建议尽快执行，并锁定观察窗。"
    if rec.status == "archived":
        return "本轮已忽略，除非证据变化否则不再优先推进。"
    if experiment is None:
        focus = _menu_action_observe_focus(rec.action_type, payload)
        return focus[0] if focus else "动作已执行，等待生成实验记录。"
    if experiment.result == "positive":
        return "效果为正，可以继续放大或沉淀为标准动作。"
    if experiment.result == "negative":
        return "效果为负，按回滚规则处理。"
    if experiment.result == "neutral":
        return "效果不明显，回到低风险单变量测试。"
    focus = _menu_action_observe_focus(rec.action_type, payload)
    return focus[0] if focus else "继续等待观察窗完成。"


def _workflow_phase(rec: Recommendation, experiment: Experiment | None) -> tuple[str, str]:
    if rec.status == "proposed":
        return "execute_now", "建议先确认采纳并尽快执行。"
    if rec.status == "adopted":
        return "execute_now", "动作已采纳，当前应进入执行。"
    if rec.status == "archived":
        return "archived", "本轮已归档，除非证据变化否则不再推进。"
    if experiment is None:
        return "observe", "动作已执行，当前先等实验记录和观察窗。"
    if experiment.result in {None, "pending"}:
        return "observe", "动作已执行，当前先盯观察指标，不要追加同类动作。"
    if experiment.result == "positive":
        return "review", "效果为正，当前更适合复盘后再决定是否放大。"
    if experiment.result == "negative":
        return "review", "效果为负，当前应先处理回滚或复盘。"
    if experiment.result == "neutral":
        return "review", "效果一般，当前先复盘再决定是否继续。"
    return "observe", "继续等待观察窗完成。"


def _workflow_item(
    rec: Recommendation,
    experiment_map: dict[str, Experiment],
    item_names: dict[str, str],
) -> AgentWorkflowItem:
    payload = _json_loads_dict(rec.content_json)
    if rec.object_ref.startswith("item:"):
        object_name = item_names.get(rec.object_ref.split(":", 1)[1], "当前主推商品")
        menu_patch = payload.get("menu_patch")
        menu_cleanup = payload.get("menu_cleanup")
        if object_name == "当前主推商品" and isinstance(menu_patch, dict) and menu_patch.get("item_name"):
            object_name = str(menu_patch["item_name"])
        if object_name == "当前主推商品" and isinstance(menu_cleanup, dict) and menu_cleanup.get("name"):
            object_name = str(menu_cleanup["name"])
    else:
        object_name = "门店整体"
    experiment = experiment_map.get(rec.id)
    execution_phase, phase_reason = _workflow_phase(rec, experiment)
    return AgentWorkflowItem(
        recommendation_id=rec.id,
        title=_recommendation_title(rec.action_type),
        action_type=rec.action_type,
        object_ref=rec.object_ref,
        object_name=object_name,
        status=rec.status,
        execution_phase=execution_phase,
        phase_reason=phase_reason,
        expected_metric=rec.expected_metric,
        window_hours=rec.window_hours,
        confidence=float(rec.confidence),
        rollback_rule=rec.rollback_rule,
        evidence=_json_loads_list(rec.evidence_json)[:4],
        generated_content=_workflow_generated_content(rec, object_name),
        experiment_id=experiment.id if experiment else None,
        experiment_result=experiment.result if experiment else None,
        experiment_lift_pct=experiment.lift_pct if experiment else None,
        experiment_notes=experiment.notes if experiment else None,
        next_decision=_workflow_next_decision(rec, experiment),
    )


def _experiment_map(ctx: _AgentContext) -> dict[str, Experiment]:
    return {exp.recommendation_id: exp for exp in ctx.experiments}


def _workflow_phase_rank(item: AgentWorkflowItem) -> tuple[int, int, float]:
    phase_rank = {
        "execute_now": 0,
        "review": 1,
        "observe": 2,
        "deferred": 3,
        "archived": 4,
    }.get(item.execution_phase, 2)
    status_rank = {
        "adopted": 0,
        "proposed": 1,
        "executed": 2,
        "archived": 3,
    }.get(item.status, 4)
    return phase_rank, status_rank, -float(item.confidence)


def _workflow_phase_summary(item: AgentWorkflowItem) -> str:
    if item.execution_phase == "execute_now":
        return f"当前主动作是 {item.title}，建议现在执行。"
    if item.execution_phase == "observe":
        return f"当前先观察 {item.object_name}，不要马上叠加第二个同类动作。"
    if item.execution_phase == "review":
        return f"当前先复盘 {item.object_name} 这条动作，再决定是否继续放大。"
    return f"{item.title} 当前已归档，除非证据变化否则不再推进。"


def _current_action(queue: list[AgentWorkflowItem]) -> AgentWorkflowItem | None:
    if not queue:
        return None
    return sorted(queue, key=_workflow_phase_rank)[0]


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


def _dedupe_workflow_items(queue: list[AgentWorkflowItem]) -> list[AgentWorkflowItem]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[AgentWorkflowItem] = []
    for item in queue:
        key = (
            item.action_type,
            _normalize_text(item.title),
            _normalize_text(item.object_name),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dedupe_growth_actions(actions: list[GrowthActionView]) -> list[GrowthActionView]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[GrowthActionView] = []
    for action in actions:
        key = (
            action.action_type,
            _normalize_text(action.title),
            _normalize_text(action.object_name),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _growth_is_discount_action(action_type: str | None) -> bool:
    return action_type in {
        "store_discount",
        "join_lunch_campaign",
        "match_competitor_promo",
        "launch_value_bundle_promo",
        "boost_hero_item_ads",
        "shift_ads_to_high_cvr_item",
    }


def _growth_action_bias(action_type: str | None) -> tuple[int, int]:
    if action_type in {
        "change_main_image",
        "change_title",
        "refresh_hero_image",
        "refresh_signature_card",
        "fix_top_review_theme",
        "batch_reply_negative_reviews",
    }:
        return (0, 0)
    if action_type in {
        "menu_patch",
        "menu_cleanup",
        "add_set_meal",
        "adjust_price_value",
        "surface_set_meal",
        "recall_churn_risk_users",
        "nurture_new_customers",
    }:
        return (0, 1)
    if action_type in {"diagnosis_priority", "competition_response", "pin_positive_review_themes"}:
        return (0, 2)
    if action_type in {
        "open_lunch_online_store",
        "open_night_online_store",
        "open_value_online_store",
    }:
        return (1, 4)
    if _growth_is_discount_action(action_type):
        return (1, 3)
    return (0, 4)


def _growth_synthetic_current_action(ctx: _AgentContext, selected: GrowthOpportunityView) -> AgentWorkflowItem:
    focus_note = (
        f"当前先推进 {selected.title}，折扣动作保留作后备，只有前序低风险动作无效时再考虑。"
        if not _growth_is_discount_action(selected.action_type)
        else "当前先推进这条动作，并在观察窗结束后再决定是否切换。"
    )
    confidence = 0.7
    if selected.factors is not None:
        confidence = max(0.3, min(0.95, float(selected.factors.confidence) / 5.0))
    return AgentWorkflowItem(
        recommendation_id=selected.recommendation_id or selected.key,
        title=selected.title,
        action_type=selected.action_type,
        object_ref=f"synthetic:{selected.key}",
        object_name=selected.object_name,
        status="proposed",
        execution_phase="execute_now",
        phase_reason=focus_note,
        expected_metric=selected.expected_metric,
        window_hours=72,
        confidence=confidence,
        evidence=selected.evidence[:4],
        generated_content={
            "source_agent": selected.source_agent,
            "synthetic": True,
            "selection_reason": focus_note,
        },
        next_decision=f"先看 {selected.expected_metric} 是否进入正向变化，再决定要不要切到折扣动作。",
    )


def _growth_sync_queue_with_selection(
    ctx: _AgentContext,
    queue: list[AgentWorkflowItem],
    selected: GrowthOpportunityView | None,
) -> tuple[list[AgentWorkflowItem], AgentWorkflowItem | None]:
    current_action = _current_action(queue)
    if (
        current_action is None
        or selected is None
        or not _growth_is_discount_action(current_action.action_type)
        or current_action.execution_phase != "execute_now"
        or _growth_is_discount_action(selected.action_type)
    ):
        return queue, current_action

    deferred_reason = (
        f"这条折扣动作先保留在队列里，但今天先推进 {selected.title}。"
        " 只有前序低风险动作无效时，再考虑启用折扣。"
    )
    synced_queue: list[AgentWorkflowItem] = []
    for item in queue:
        if item.recommendation_id == current_action.recommendation_id:
            synced_queue.append(
                item.model_copy(
                    update={
                        "execution_phase": "deferred",
                        "phase_reason": deferred_reason,
                        "next_decision": f"先看 {selected.expected_metric} 的变化，再决定是否需要折扣。",
                        "generated_content": {
                            **item.generated_content,
                            "deferred_reason": deferred_reason,
                            "is_backup": True,
                        },
                    }
                )
            )
        else:
            synced_queue.append(item)

    selected_queue_item = None
    if selected.recommendation_id:
        selected_queue_item = next(
            (item for item in synced_queue if item.recommendation_id == selected.recommendation_id),
            None,
        )
    if selected_queue_item is None:
        selected_queue_item = _growth_synthetic_current_action(ctx, selected)
    return synced_queue, selected_queue_item


def _product_synthetic_current_action(
    item: _ItemSnapshot | None,
    suggestion: ProductSuggestion,
) -> AgentWorkflowItem:
    item_name = item.name if item else "当前主推商品"
    phase_reason = (
        f"当前先推进 {item_name} 的{suggestion.title}，先用低风险单变量动作验证。"
    )
    return AgentWorkflowItem(
        recommendation_id=f"synthetic:product:{suggestion.action_type}:{_normalize_text(item_name)}",
        title=_recommendation_title(suggestion.action_type),
        action_type=suggestion.action_type,
        object_ref=f"synthetic:item:{item.item_id}" if item else "synthetic:item:focus",
        object_name=item_name,
        status="proposed",
        execution_phase="execute_now",
        phase_reason=phase_reason,
        expected_metric=suggestion.expected_metric,
        window_hours=suggestion.window_hours,
        confidence=0.76 if suggestion.risk_level == "low" else 0.68,
        rollback_rule=suggestion.rollback_rule,
        evidence=[suggestion.detail],
        generated_content={
            **suggestion.generated_content,
            "synthetic": True,
            "source_agent": "product",
            "suggestion_title": suggestion.title,
            "selection_reason": phase_reason,
        },
        next_decision=f"{suggestion.window_hours}h 看 {suggestion.expected_metric} 是否改善，再决定是否切到后备动作。",
    )


def _product_sync_queue_with_suggestions(
    item: _ItemSnapshot | None,
    queue: list[AgentWorkflowItem],
    suggestions: list[ProductSuggestion],
) -> tuple[list[AgentWorkflowItem], AgentWorkflowItem | None]:
    deduped_queue = _dedupe_workflow_items(queue)
    current_action = _current_action(deduped_queue)
    top_suggestion = suggestions[0] if suggestions else None
    if top_suggestion is None:
        return deduped_queue, current_action
    if (
        current_action is not None
        and not _growth_is_discount_action(current_action.action_type)
    ):
        return deduped_queue, current_action

    synthetic_current = _product_synthetic_current_action(item, top_suggestion)
    if current_action is None:
        return deduped_queue, synthetic_current

    deferred_reason = (
        f"这条{current_action.title}先保留作后备，但当前先推进 {synthetic_current.object_name} 的{top_suggestion.title}。"
        " 只有低风险商品动作无效时，再考虑启用它。"
    )
    synced_queue: list[AgentWorkflowItem] = []
    for queued in deduped_queue:
        if queued.recommendation_id == current_action.recommendation_id:
            synced_queue.append(
                queued.model_copy(
                    update={
                        "execution_phase": "deferred",
                        "phase_reason": deferred_reason,
                        "next_decision": synthetic_current.next_decision,
                        "generated_content": {
                            **queued.generated_content,
                            "deferred_reason": deferred_reason,
                            "is_backup": True,
                        },
                    }
                )
            )
        else:
            synced_queue.append(queued)
    return synced_queue, synthetic_current


def _build_item_snapshots(
    db: Session,
    store_state: StoreState,
    menu_items: list[dict[str, Any]],
    recent_menu_actions: dict[str, dict[str, Any]],
) -> list[_ItemSnapshot]:
    total_orders = sum(float(item.order_share_pct or 0) for item in store_state.core_items) or 0
    store_ctr = store_state.kpis.get("ctr").observed_value if "ctr" in store_state.kpis else None
    avg_price_values = [float(item["price"]) for item in menu_items if item.get("price") is not None]
    avg_price = sum(avg_price_values) / len(avg_price_values) if avg_price_values else None
    core_map = {row.item_id: row for row in store_state.core_items}
    snapshots: list[_ItemSnapshot] = []

    for item in menu_items:
        observe = _sum_item_window(db, item["item_id"], store_state.window.from_day, store_state.window.to_day)
        baseline = _sum_item_window(db, item["item_id"], store_state.window.compare_from_day, store_state.window.compare_to_day)
        core = core_map.get(item["item_id"])
        share = core.order_share_pct if core else None
        ctr_delta = _delta_pct(baseline["ctr"], observe["ctr"])
        snapshot = _ItemSnapshot(
            item_id=item["item_id"],
            name=item["name"],
            category=item.get("category"),
            price=item.get("price"),
            description=item.get("description"),
            observe_orders=observe["orders"],
            observe_gmv=observe["gmv"],
            observe_impressions=observe["impressions"],
            observe_visits=observe["visits"],
            observe_ctr=observe["ctr"],
            observe_cvr=observe["cvr"],
            baseline_orders=baseline["orders"],
            baseline_impressions=baseline["impressions"],
            baseline_visits=baseline["visits"],
            baseline_ctr=baseline["ctr"],
            baseline_cvr=baseline["cvr"],
            orders_delta_pct=_delta_pct(baseline["orders"], observe["orders"]),
            impressions_delta_pct=_delta_pct(baseline["impressions"], observe["impressions"]),
            order_share_pct=share,
            ctr_delta_pct=ctr_delta if ctr_delta is not None else (core.ctr_delta_pct if core else None),
            cvr_delta_pct=_delta_pct(baseline["cvr"], observe["cvr"]),
            image_url=item.get("image_url"),
        )
        recent_action = recent_menu_actions.get(item["item_id"])
        if (
            recent_action
            and share is None
            and snapshot.observe_orders <= 2
            and snapshot.observe_impressions <= 50
        ):
            menu_patch = recent_action.get("menu_patch")
            menu_bundle = recent_action.get("menu_bundle")
            if recent_action["action_type"] == "menu_patch" and isinstance(menu_patch, dict):
                target_role = str(menu_patch.get("target_role") or "Experimental Product")
                snapshot.role = target_role
                snapshot.rationale = "这是最近刚创建的菜单修正项，仍在观察窗内，先不要按低效 SKU 处理。"
                snapshots.append(snapshot)
                continue
            if recent_action["action_type"] == "add_set_meal" and isinstance(menu_bundle, dict):
                snapshot.role = "Basket Builder"
                snapshot.rationale = "这是最近刚创建的套餐项，仍在观察窗内，先看连带和转化表现。"
                snapshots.append(snapshot)
                continue

        if share is not None and share >= 35:
            snapshot.role = "Hero Product"
            snapshot.rationale = "订单贡献最高，是当前菜单的核心爆品。"
        elif avg_price and snapshot.price is not None and snapshot.price <= avg_price * 0.72 and (
            snapshot.observe_ctr is not None and (store_ctr is None or snapshot.observe_ctr >= store_ctr * 0.95)
        ):
            snapshot.role = "Traffic Product"
            snapshot.rationale = "价格门槛更低，适合承接第一波点击。"
        elif avg_price and snapshot.price is not None and snapshot.price >= avg_price * 1.12 and (
            snapshot.observe_cvr is not None and snapshot.observe_cvr >= 0.16
        ):
            snapshot.role = "Profit Product"
            snapshot.rationale = "价格带更高且仍能成交，具备利润款特征。"
        elif avg_price and snapshot.price is not None and snapshot.price <= avg_price * 0.58 and snapshot.observe_orders >= 3:
            snapshot.role = "Basket Builder"
            snapshot.rationale = "低决策成本，适合做搭配品提升客单。"
        elif (share is not None and share < 5) or snapshot.observe_orders <= 2:
            snapshot.role = "Zombie SKU"
            snapshot.rationale = "订单贡献持续偏低，需要考虑降权或下架测试。"
        else:
            snapshot.role = "Experimental Product"
            snapshot.rationale = "目前信号不够稳定，先放在观察位。"

        snapshots.append(snapshot)

    snapshots.sort(key=lambda row: (row.order_share_pct or 0, row.observe_orders), reverse=True)
    return snapshots


def _build_context(db: Session, store_id: str, days: int) -> _AgentContext | None:
    store = _load_store(db, store_id)
    if store is None:
        return None

    store_state = build_store_state(db=db, store_id=store_id, days=days)
    if store_state is None:
        return None
    document_alignment = build_document_alignment(db=db, store_id=store_id)

    generated_at = datetime.now(timezone.utc)
    history_cutoff = generated_at - timedelta(days=ACTION_HISTORY_DAYS)
    obs_stmt = select(Observation).where(Observation.store_id == store_id).order_by(Observation.created_at.desc()).limit(6)
    rec_stmt = (
        select(Recommendation)
        .where(
            Recommendation.store_id == store_id,
            func.coalesce(Recommendation.executed_at, Recommendation.adopted_at, Recommendation.created_at) >= history_cutoff,
        )
        .order_by(Recommendation.created_at.desc())
    )
    hypothesis_stmt = select(Hypothesis).where(Hypothesis.store_id == store_id).order_by(Hypothesis.created_at.desc()).limit(1)
    exp_stmt = (
        select(Experiment)
        .where(
            Experiment.store_id == store_id,
            Experiment.created_at >= history_cutoff,
        )
        .order_by(Experiment.created_at.desc())
    )

    observations = db.execute(obs_stmt).scalars().all()
    recommendations = db.execute(rec_stmt).scalars().all()
    hypothesis = db.execute(hypothesis_stmt).scalar_one_or_none()
    experiments = db.execute(exp_stmt).scalars().all()

    if not observations or not recommendations:
        run_daily_job(db=db, store_id=store_id, days=days)
        observations = db.execute(obs_stmt).scalars().all()
        recommendations = db.execute(rec_stmt).scalars().all()
        hypothesis = db.execute(hypothesis_stmt).scalar_one_or_none()
        experiments = db.execute(exp_stmt).scalars().all()

    recommendations = sorted(recommendations, key=_recommendation_priority, reverse=True)
    menu_items = _menu_items(store)
    temp_ctx = _AgentContext(
        store=store,
        store_state=store_state,
        document_alignment=document_alignment,
        observations=observations,
        hypothesis=hypothesis,
        recommendations=recommendations,
        experiments=experiments,
        menu_items=menu_items,
        item_snapshots=[],
        generated_at=generated_at,
        days=days,
    )
    recent_menu_actions = _recent_menu_action_state(temp_ctx)
    item_snapshots = _build_item_snapshots(db, store_state, menu_items, recent_menu_actions)

    # 加载 system_mode（MOS + Safe Mode）
    system_mode = "operating"
    try:
        from app.services.mue import ensure_understanding

        mu = ensure_understanding(db, store_id=store_id, agents=None)
        from app.services.mos_engine import determine_system_mode

        system_mode = determine_system_mode(mu)
    except Exception:  # noqa: BLE001
        pass

    return _AgentContext(
        store=store,
        store_state=store_state,
        document_alignment=document_alignment,
        observations=observations,
        hypothesis=hypothesis,
        recommendations=recommendations,
        experiments=experiments,
        menu_items=menu_items,
        item_snapshots=item_snapshots,
        generated_at=temp_ctx.generated_at,
        days=days,
        system_mode=system_mode,
    )


# 公共别名：供 agent_context_cache / chief_agent 复用（_build_context 保持私有别名）
build_agent_context = _build_context


def build_single_agent_cached(
    db: Session,
    store_id: str,
    agent_key: AgentKey,
    *,
    ctx: _AgentContext | None = None,
    days: int = 7,
    use_cache: bool = True,
    item_id: str | None = None,
) -> dict[str, Any] | None:
    """真正的单 agent 调用（区别于旧的 build_single_agent 全跑 13 个）。

    - ctx 可复用（chief_agent 多轮调用时传入同一个 context，省去重建成本）；
    - use_cache=True 时走 agent_context_cache，TTL 5 分钟；
    - growth 是例外：它依赖 competition/menu/product/diagnosis，单跑时会先按需构建这 4 个依赖。
    - item_id：product agent 可指定焦点商品。
    """
    if ctx is None:
        if use_cache:
            from app.services.agent_context_cache import get_context

            ctx = get_context(db, store_id, days=days)
        else:
            ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None

    result = _build_one_agent(db, ctx, agent_key, focus_item_id=item_id)
    if result is None:
        return None
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


def _build_one_agent(
    db: Session,
    ctx: _AgentContext,
    agent_key: AgentKey,
    *,
    focus_item_id: str | None = None,
) -> Any:
    """按 agent_key 构建单个 agent。growth 需要额外依赖。"""
    if agent_key == "competition":
        return _build_competition_agent(db, ctx)
    if agent_key == "menu":
        return _build_menu_agent(ctx)
    if agent_key == "product":
        return _build_product_agent(ctx, focus_item_id=focus_item_id)
    if agent_key == "storefront":
        return _build_storefront_agent(db, ctx)
    if agent_key == "diagnosis":
        return _build_diagnosis_agent(db, ctx)

    # 6 个矩阵 agent：需要 MatrixAgentInput
    if agent_key in {"promo", "ads", "crm", "service", "review", "store_matrix"}:
        matrix_input = _build_matrix_input(db, ctx)
        builders = {
            "promo": build_promo_agent,
            "ads": build_ads_agent,
            "crm": build_crm_agent,
            "service": build_service_agent,
            "review": build_review_agent,
            "store_matrix": build_store_matrix_agent,
        }
        return builders[agent_key](db, matrix_input, ctx.recommendations)

    # growth 依赖 competition/menu/product/diagnosis
    if agent_key == "growth":
        competition = _build_competition_agent(db, ctx)
        menu = _build_menu_agent(ctx)
        product = _build_product_agent(ctx)
        diagnosis = _build_diagnosis_agent(db, ctx)
        return _build_growth_agent(
            ctx, competition, menu, product, diagnosis
        )

    return None


def _agent_meta(key: AgentKey, generated_at: datetime, confidence: Optional[float]) -> AgentMeta:
    return AgentMeta(key=key, label=AGENT_LABELS[key], confidence=confidence, generated_at=generated_at)


def _price_band(menu_items: list[dict[str, Any]]) -> Optional[str]:
    prices = [float(row["price"]) for row in menu_items if row.get("price") is not None]
    if not prices:
        return None
    return f"{int(min(prices))}-{int(max(prices))}"


def _distance_m(
    origin_lat: Optional[float],
    origin_lng: Optional[float],
    target_lat: Optional[float],
    target_lng: Optional[float],
) -> Optional[int]:
    if None in (origin_lat, origin_lng, target_lat, target_lng):
        return None
    earth_radius_m = 6_371_000
    lat1, lat2 = math.radians(origin_lat), math.radians(target_lat)
    delta_lat = math.radians(target_lat - origin_lat)
    delta_lng = math.radians(target_lng - origin_lng)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    return int(round(earth_radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))))


def _positioning(
    store_price_band: Optional[str],
    competitor_min: Optional[float],
    competitor_max: Optional[float],
) -> str:
    if not store_price_band or competitor_min is None or competitor_max is None:
        return "同商圈替代选择"
    store_low, store_high = (float(part) for part in store_price_band.split("-"))
    store_mid = (store_low + store_high) / 2
    competitor_mid = (competitor_min + competitor_max) / 2
    if competitor_mid <= store_mid * 0.85:
        return "低价快餐"
    if competitor_mid >= store_mid * 1.18:
        return "品质溢价"
    return "同价格带竞争"


def _latest_competitor_menu(db: Session, snapshot_id: str) -> list[CompetitorMenuItem]:
    stmt = (
        select(CompetitorMenuItem)
        .where(CompetitorMenuItem.snapshot_id == snapshot_id)
        .order_by(CompetitorMenuItem.rating.desc().nullslast(), CompetitorMenuItem.name)
    )
    return list(db.execute(stmt).scalars().all())


def _build_competition_agent(db: Session, ctx: _AgentContext) -> CompetitionAgentResult:
    store = ctx.store
    store_price_band = _price_band(ctx.menu_items)
    market_focus = list(ctx.store_state.market.market_type or [])
    primary_problem = ctx.store_state.primary_problem.type if ctx.store_state.primary_problem else None
    top_competitors: list[CompetitorBrief] = []

    watched_ids = list(
        db.execute(
            select(StoreCompetitorWatch.c_store_id).where(
                StoreCompetitorWatch.store_id == store.id,
                StoreCompetitorWatch.active.is_(True),
            )
        ).scalars()
    )
    competitor_stmt = (
        select(CompetitorStore)
        .where(CompetitorStore.id.in_(watched_ids))
        .limit(5)
    )
    competitors = db.execute(competitor_stmt).scalars().all()
    change_by_competitor: dict[str, list[Any]] = {}
    for change in ctx.store_state.competition_changes:
        change_by_competitor.setdefault(change.c_store_id, []).append(change)

    threat_signals: list[str] = []
    completeness_scores: list[float] = []
    for competitor in competitors:
        snapshot_stmt = (
            select(CompetitorSnapshot)
            .where(CompetitorSnapshot.c_store_id == competitor.id)
            .order_by(CompetitorSnapshot.captured_at.desc())
            .limit(1)
        )
        snapshot = db.execute(snapshot_stmt).scalar_one_or_none()
        competitor_menu = _latest_competitor_menu(db, snapshot.id) if snapshot else []
        distance_m = _distance_m(
            store.latitude,
            store.longitude,
            competitor.latitude,
            competitor.longitude,
        )
        category_overlap = 1.0 if competitor.category and store.merchant and competitor.category == store.merchant.category else 0.72
        if distance_m is None:
            location_overlap = 0.72 if competitor.area == store.area else 0.45
        elif distance_m <= 500:
            location_overlap = 1.0
        elif distance_m <= 1000:
            location_overlap = 0.88
        elif distance_m <= (store.delivery_radius_m or 2500):
            location_overlap = 0.72
        else:
            location_overlap = 0.42
        price_overlap = 0.65
        price_band = None
        if snapshot and snapshot.price_band_min is not None and snapshot.price_band_max is not None:
            price_band = f"{int(snapshot.price_band_min)}-{int(snapshot.price_band_max)}"
            if store_price_band:
                low, high = [int(part) for part in store_price_band.split("-")]
                overlap_low = max(low, int(snapshot.price_band_min))
                overlap_high = min(high, int(snapshot.price_band_max))
                price_overlap = 1.0 if overlap_low <= overlap_high else 0.45
        rating_strength = min(1.0, float(snapshot.rating) / 5.0) if snapshot and snapshot.rating else 0.62
        menu_strength = min(1.0, len(competitor_menu) / 12) if competitor_menu else 0.45
        score = int(
            round(
                100
                * (
                    0.30 * category_overlap
                    + 0.25 * price_overlap
                    + 0.25 * location_overlap
                    + 0.12 * rating_strength
                    + 0.08 * menu_strength
                )
            )
        )
        positioning = _positioning(
            store_price_band,
            snapshot.price_band_min if snapshot else None,
            snapshot.price_band_max if snapshot else None,
        )
        set_meals = [
            item
            for item in competitor_menu
            if any(token in item.name for token in ("套餐", "组合", "双人", "单人餐"))
        ]
        strengths: list[str] = []
        if price_overlap >= 1:
            strengths.append("价格带与本店高度重合")
        if snapshot and snapshot.rating and snapshot.rating >= 4.6:
            strengths.append("用户评分较高")
        if set_meals:
            strengths.append(f"套餐供给较完整（{len(set_meals)} 个）")
        if distance_m is not None and distance_m <= 800:
            strengths.append("距离近，配送客群重合")
        weaknesses: list[str] = []
        if snapshot and snapshot.rating and snapshot.rating < 4.5:
            weaknesses.append("评分承接偏弱")
        if len(competitor_menu) < 5:
            weaknesses.append("菜单选择较少")
        if not set_meals:
            weaknesses.append("套餐结构不明显")
        advantage = strengths[0] if strengths else "在同商圈形成直接替代选择"
        completeness_scores.append(
            sum(
                (
                    0.25,
                    0.20 if distance_m is not None else 0,
                    0.25 if snapshot else 0,
                    0.30 if competitor_menu else 0,
                )
            )
        )

        # recent moves come from real detected changes
        own_changes = change_by_competitor.get(competitor.id, [])
        if any(c.type == "price_down" for c in own_changes):
            recent_move = "近期主动调低了价格带，正在用价格抢单。"
            threat_signals.append(f"{competitor.name} 近期降价抢单")
        elif any(c.type == "price_up" for c in own_changes):
            recent_move = "近期上探更高价格带，正在抢中高端心智。"
            threat_signals.append(f"{competitor.name} 冲向中高端市场")
        elif any(c.type == "rating_up" for c in own_changes):
            recent_move = "评价近期回升，转化威胁上升。"
            threat_signals.append(f"{competitor.name} 口碑在回升")
        elif any(c.type == "rating_down" for c in own_changes):
            recent_move = "评价近期回落，口碑窗口正在打开。"
        elif any(c.type == "product_added" for c in own_changes):
            added = next(c for c in own_changes if c.type == "product_added")
            recent_move = added.summary
            threat_signals.append(added.summary)
        elif any(c.type == "image_changed" for c in own_changes):
            changed = next(c for c in own_changes if c.type == "image_changed")
            recent_move = changed.summary
            threat_signals.append(changed.summary)
        elif any(c.type == "product_price_changed" for c in own_changes):
            changed = next(c for c in own_changes if c.type == "product_price_changed")
            recent_move = changed.summary
            threat_signals.append(changed.summary)
        else:
            recent_move = "最近快照已更新，建议紧盯图文和套餐变化。"
        top_competitors.append(
            CompetitorBrief(
                competitor_id=competitor.id,
                name=competitor.name,
                score=max(35, min(96, score)),
                distance_m=distance_m,
                price_band=price_band,
                rating=snapshot.rating if snapshot else None,
                positioning=positioning,
                advantage=advantage,
                strengths=strengths[:3],
                weaknesses=weaknesses[:2],
                featured_products=[item.name for item in competitor_menu[:3]],
                menu_item_count=len(competitor_menu),
                set_meal_count=len(set_meals),
                recent_move=recent_move,
            )
        )

    top_competitors.sort(key=lambda row: row.score, reverse=True)
    changes = [
        CompetitionChangeView(type=row.type, summary=row.summary, price=row.price)
        for row in ctx.store_state.competition_changes[:3]
    ]

    competition_score = top_competitors[0].score if top_competitors else (78 if primary_problem == "store_ctr_down" else 66)
    if primary_problem == "store_ctr_down":
        conclusion = "当前更像是在第一眼竞争里输给了同商圈替代选项。"
        actions = [
            "先盯主图和标题的竞争力，再决定要不要动价格。",
            "优先看同价格带门店最近有没有上新套餐或改图。",
        ]
    else:
        conclusion = "当前竞争问题更偏承接能力，而不是单纯曝光不足。"
        actions = [
            "先核对套餐和评价短板，不要直接打折。",
            "先看同商圈高评分门店怎么做承接和搭配。",
        ]

    # 当检测到真实威胁信号时，把动作升级为更具体的应对
    pricedown = [c for c in ctx.store_state.competition_changes if c.type == "price_down"]
    rating_conflict_competitors = [c for c in ctx.store_state.competition_changes if c.type == "rating_up"]
    if pricedown:
        conclusion = f"有竞品（{pricedown[0].summary.split('近期')[0]}）正在用价格抢你的核心客群，第一眼竞争压力上升。"
        actions = [
            "不要跟着硬降价，先用套餐结构和图文价值感回击。",
            "把主推 SKU 的锚点提到竞品之上，用价值感而非低价应对。",
            "盯住该竞品近 72 小时的爆品与评价变化。",
        ]
    elif rating_conflict_competitors and primary_problem == "store_cvr_down":
        conclusion = f"有竞品（{rating_conflict_competitors[0].summary.split('近期')[0]}）口碑在回升，正在抢转化和连带订单。"
        actions = [
            "优先补套餐和评价回复，稳住转化承接。",
            "用真实分量/包装亮点对冲竞品口碑回升。",
            "将差评主题收敛成 1 个改进点，别分散动作。",
        ]

    reasons = [
        f"商圈聚焦：{' / '.join(market_focus) if market_focus else '同商圈、同价格带'}。",
        top_competitors[0].name + " 是当前最值得盯的竞品。" if top_competitors else "当前还没有竞品快照，先用商圈和价格带做保守判断。",
        changes[0].summary if changes else "暂无显式变更记录，优先补 competitor snapshot。",
    ]
    reasons = list(dict.fromkeys(reasons))[:3]
    blockers = _document_blockers(ctx)
    if not top_competitors:
        blockers.append("缺少同商圈竞品快照，当前竞争判断偏保守。")
    readiness = "ready" if top_competitors and _alignment_readiness(ctx) == "ready" else _alignment_readiness(ctx)
    confidence = (
        round(sum(completeness_scores) / len(completeness_scores), 2)
        if completeness_scores
        else 0.35
    )
    evidence = [
        f"资料对齐状态：{ctx.document_alignment.get('status')} / {ctx.document_alignment.get('alignment_score')} 分。",
        *reasons,
        *threat_signals[:2],
    ]

    return CompetitionAgentResult(
        meta=_agent_meta("competition", ctx.generated_at, confidence),
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        benchmark_group="同商圈 / 同价格带 / 同用户群",
        competition_score=competition_score,
        nearby_total=len(watched_ids) or len(top_competitors),
        market_focus=market_focus,
        top_competitors=top_competitors[:3],
        changes=changes,
        conclusion=conclusion,
        reasons=reasons[:3],
        evidence=list(dict.fromkeys(evidence))[:5],
        actions=actions[:3],
        expected_impact="预计降低同价格带竞品分流风险，并为后续 CTR/CVR 实验建立可验证基线。",
        threat_signals=threat_signals[:3],
    )


def _build_menu_agent(ctx: _AgentContext) -> MenuAgentResult:
    items = ctx.item_snapshots
    role_distribution, gaps, deferred_notes, recent_role_feedback = _menu_gap_profile(ctx, items)
    strategy_notes = _menu_role_strategy_notes(recent_role_feedback)

    role_coverage = sum(1 for key in ("Hero Product", "Traffic Product", "Profit Product", "Basket Builder") if role_distribution.get(key))
    health_score = 70 + role_coverage * 5 - role_distribution.get("Zombie SKU", 0) * 6
    menu_health_score = max(38, min(95, health_score))
    category_summary = _menu_category_summary(items)
    pricing_ladder = _menu_pricing_ladder(items)
    pricing_gap_note = _menu_pricing_gap_note(pricing_ladder, recent_role_feedback)
    bundle_opportunities = _menu_bundle_opportunities(ctx, items)
    cleanup_candidates = _menu_cleanup_candidates(ctx, items)
    suggested_patches = _menu_patch_suggestions(ctx, items, pricing_ladder, gaps)
    action_queue, current_action = _menu_workflow(ctx)

    # 注入菜单诊断 12 引擎 findings（从旁路端点升级为主链路诊断内核）
    diagnosis_findings: list[str] = []
    diagnosis_evidence: list[str] = []
    try:
        from app.schemas.menu_diagnosis import DiagnosisContext, MenuItemInput as DiagMenuItem
        from app.services.menu_diagnosis_engine import run_diagnosis_engines

        diag_items = [
            DiagMenuItem(
                id=snap.item_id,
                name=snap.name,
                category=snap.category or "",
                price=snap.price or 0,
                description=snap.description,
                image_url=snap.image_url,
                role=snap.role,
                order_count=int(snap.observe_orders),
                order_share_pct=snap.order_share_pct,
                ctr=snap.observe_ctr,
                cvr=snap.observe_cvr,
            )
            for snap in items
        ]
        has_cost = any(mi.standard_cost for mi in diag_items)
        diag_ctx = DiagnosisContext(
            store_id=ctx.store.id,
            store_name=ctx.store.name,
            menu_items=diag_items,
            data_level="D2" if has_cost else "D1",
        )
        diag_result = run_diagnosis_engines(diag_ctx)
        # 把 critical/warning findings 注入 gaps + evidence + actions
        for finding in diag_result.findings:
            if finding.severity in ("critical", "warning"):
                diagnosis_findings.append(finding.title)
                diagnosis_evidence.append(f"{finding.title}：{finding.description[:80]}")
                actions.extend(finding.suggested_actions[:1])
    except Exception:  # noqa: BLE001 — 12 引擎失败不阻断 menu agent
        pass

    actions = []
    actions.extend((deferred_notes + strategy_notes)[:2])
    if gaps:
        if any("搭配品" in gap for gap in gaps):
            actions.append("先围绕主力款补一个低决策成本套餐。")
        if any("引流款" in gap for gap in gaps):
            actions.append("补一款更轻决策的引流商品，别全靠爆品带点击。")
        if any("利润款" in gap for gap in gaps):
            actions.append("围绕主推款补一个更高价值版本，先把利润价格带拉开。")
        if any("菜单过窄" in gap for gap in gaps):
            actions.append("先把菜单扩到至少 3 个有效选择，再谈排序优化。")
        if role_distribution.get("Zombie SKU", 0):
            actions.append("挑 1-2 个低效 SKU 做降权或下架测试。")
    else:
        actions.append("结构基本齐了，接下来优先微调主力款和套餐承接。")
    document_gaps = _document_menu_gaps(ctx)
    if document_gaps:
        actions.append("先把文档中出现但系统未录入的 SKU 补进结构化菜单。")
    blockers = _document_blockers(ctx)
    readiness = _alignment_readiness(ctx)
    if not items:
        blockers.append("当前没有结构化菜单，菜单 Agent 无法输出可信建议。")
        readiness = "blocked"
    if pricing_gap_note:
        actions.append(pricing_gap_note)
    if cleanup_candidates:
        actions.append(f"优先处理 {cleanup_candidates[0].name} 这类低效 SKU。")
    if suggested_patches:
        actions.append(f"先处理菜单修正方案：{suggested_patches[0].item_name}。")
    evidence = [
        f"SKU 总数 {len(items)}，角色覆盖 {len([key for key in role_distribution if role_distribution.get(key)])} 类。",
        *(gaps[:2] or ["当前结构缺口不明显。"]),
        *deferred_notes[:2],
        *strategy_notes[:2],
        pricing_gap_note or "",
        *document_gaps[:2],
        *diagnosis_evidence[:3],  # 12 引擎证据注入
    ]
    # 12 引擎 critical/warning findings 注入 structural_gaps
    gaps = list(dict.fromkeys([*gaps, *diagnosis_findings[:3]]))[:6]
    if category_summary:
        evidence.append(f"最大类目是 {category_summary[0].category}，当前有 {category_summary[0].item_count} 个 SKU。")
    if suggested_patches:
        evidence.append(f"已生成 {len(suggested_patches)} 条菜单修正方案。")
    workflow_summary = None
    if deferred_notes and current_action is not None and current_action.execution_phase == "observe":
        next_patch = f" 下一候选是 {suggested_patches[0].item_name}。" if suggested_patches else ""
        workflow_summary = f"{deferred_notes[0]} {_workflow_phase_summary(current_action)}{next_patch}"
    elif deferred_notes and suggested_patches:
        workflow_summary = f"{deferred_notes[0]} 当前更适合推进 {suggested_patches[0].item_name}。"
    elif strategy_notes and suggested_patches:
        workflow_summary = f"{strategy_notes[0]} 当前可以继续推进 {suggested_patches[0].item_name}。"
    elif gaps:
        workflow_summary = f"当前菜单第一优先缺口：{gaps[0]}"
    elif pricing_gap_note:
        workflow_summary = pricing_gap_note
    elif suggested_patches:
        workflow_summary = f"当前优先补录/修正 {suggested_patches[0].item_name}，补齐菜单结构。"
    elif current_action is not None:
        workflow_summary = f"{_workflow_phase_summary(current_action)} {current_action.phase_reason}"
    else:
        workflow_summary = "菜单结构基本齐了，下一步优先微调套餐和低效 SKU。"

    menu_narrative = narrate_menu(
        store_name=ctx.store.name,
        menu_health_score=menu_health_score,
        role_distribution=role_distribution,
        structural_gaps=gaps[:4],
        suggested_patches=[p.model_dump(mode="json") for p in suggested_patches],
        cleanup_candidates=[c.model_dump(mode="json") for c in cleanup_candidates],
        fallback_summary=workflow_summary,
    )
    menu_meta = _agent_meta("menu", ctx.generated_at, 0.72)
    if menu_narrative:
        menu_meta.ai_narrative = menu_narrative
        menu_meta.ai_mode = "llm"
    return MenuAgentResult(
        meta=menu_meta,
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        menu_health_score=menu_health_score,
        role_distribution=role_distribution,
        items=[
            MenuRoleItem(
                item_id=item.item_id,
                name=item.name,
                role=item.role,
                price=item.price,
                order_share_pct=item.order_share_pct,
                ctr_delta_pct=item.ctr_delta_pct,
                cvr=item.observe_cvr,
                rationale=item.rationale,
            )
            for item in items[:6]
        ],
        workflow_summary=workflow_summary,
        category_summary=category_summary,
        pricing_ladder=pricing_ladder,
        bundle_opportunities=bundle_opportunities,
        cleanup_candidates=cleanup_candidates,
        suggested_patches=suggested_patches,
        structural_gaps=gaps[:4],
        document_gaps=document_gaps[:3],
        evidence=[row for row in list(dict.fromkeys(evidence))[:6] if row],
        actions=list(dict.fromkeys(actions))[:4],
        action_queue=action_queue,
        current_action=current_action,
    )


def _bounded_score(value: float) -> int:
    return max(20, min(98, int(round(value))))


def _product_health_dimensions(item: _ItemSnapshot) -> tuple[int, list[ProductHealthDimension]]:
    sales_score = _bounded_score(
        68
        + min(18, max(-18, (item.order_share_pct or 0) - 20) * 0.6)
        + min(12, max(-18, item.orders_delta_pct or 0) * 0.45)
    )
    exposure_score = _bounded_score(72 + min(20, max(-30, item.impressions_delta_pct or 0) * 0.7))
    click_score = _bounded_score(74 + min(20, max(-30, item.ctr_delta_pct or 0) * 0.8))
    conversion_score = _bounded_score(74 + min(20, max(-30, item.cvr_delta_pct or 0) * 0.8))

    def dimension(
        key: str,
        label: str,
        score: int,
        observed: Optional[float],
        baseline: Optional[float],
        delta: Optional[float],
    ) -> ProductHealthDimension:
        status = "strong" if score >= 80 else "watch" if score >= 65 else "weak"
        return ProductHealthDimension(
            key=key,
            label=label,
            score=score,
            observed_value=observed,
            baseline_value=baseline,
            delta_pct=delta,
            status=status,
        )

    dimensions = [
        dimension(
            "sales",
            "销量贡献",
            sales_score,
            item.observe_orders,
            item.baseline_orders,
            item.orders_delta_pct,
        ),
        dimension(
            "exposure",
            "曝光",
            exposure_score,
            item.observe_impressions,
            item.baseline_impressions,
            item.impressions_delta_pct,
        ),
        dimension("ctr", "点击", click_score, item.observe_ctr, item.baseline_ctr, item.ctr_delta_pct),
        dimension("cvr", "转化", conversion_score, item.observe_cvr, item.baseline_cvr, item.cvr_delta_pct),
    ]
    health_score = _bounded_score(
        sales_score * 0.30 + exposure_score * 0.20 + click_score * 0.25 + conversion_score * 0.25
    )
    return health_score, dimensions


def _product_diagnosis(
    item: _ItemSnapshot,
    average_price: Optional[float],
) -> tuple[str, str, str, list[str], list[ProductRootCause]]:
    if item.impressions_delta_pct is not None and item.impressions_delta_pct <= -8:
        stage = "impressions"
        issue = "商品曝光下降"
        diagnosis = "商品首先输在被看见的机会，暂时不是价格或转化问题。"
        decision_path = ["销量变化", "曝光下降", "优先检查排序、流量入口和商品表达完整度"]
        root_causes = [
            ProductRootCause(
                code="traffic_or_ranking",
                stage=stage,
                title="流量入口或排序走弱",
                explanation="曝光先于点击下降，应先恢复商品被看到的机会。",
                confidence=0.82,
                evidence=[f"曝光较基线变化 {item.impressions_delta_pct:.1f}%"],
            )
        ]
    elif item.ctr_delta_pct is not None and item.ctr_delta_pct <= -5:
        stage = "ctr"
        issue = "点击吸引力下降"
        diagnosis = "用户已经看见商品，但主图、标题或第一眼价格感知没有赢下点击。"
        decision_path = ["销量变化", "曝光基本可用", "CTR 下降", "检查主图、标题和价格感知"]
        root_causes = []
        if not item.image_url:
            root_causes.append(
                ProductRootCause(
                    code="missing_image_evidence",
                    stage=stage,
                    title="主图证据缺失或表达不足",
                    explanation="系统没有拿到可验证的商品主图，第一眼竞争力无法被证明。",
                    confidence=0.78,
                    evidence=["商品当前缺少结构化主图地址", f"CTR 变化 {item.ctr_delta_pct:.1f}%"],
                )
            )
        if len(_normalize_text(item.name)) <= 6:
            root_causes.append(
                ProductRootCause(
                    code="generic_title",
                    stage=stage,
                    title="标题卖点不够具体",
                    explanation="标题只有品类名，缺少口味、份量或场景信息，点击理由不充分。",
                    confidence=0.74,
                    evidence=[f"当前标题：{item.name}"],
                )
            )
        if average_price and item.price and item.price >= average_price * 1.12:
            root_causes.append(
                ProductRootCause(
                    code="price_perception",
                    stage=stage,
                    title="第一眼价格感知偏高",
                    explanation="价格高于菜单均价，但标题和主图没有同步证明价值。",
                    confidence=0.69,
                    evidence=[f"商品价 ¥{item.price:.0f}，菜单均价约 ¥{average_price:.0f}"],
                )
            )
        if not root_causes:
            root_causes.append(
                ProductRootCause(
                    code="creative_fatigue",
                    stage=stage,
                    title="第一眼素材竞争力走弱",
                    explanation="曝光没有先下滑而 CTR 明显下降，更符合图文吸引力问题。",
                    confidence=0.71,
                    evidence=[f"CTR 变化 {item.ctr_delta_pct:.1f}%"],
                )
            )
    elif (
        item.cvr_delta_pct is not None
        and item.cvr_delta_pct <= -5
        or item.observe_cvr is not None
        and item.observe_cvr < 0.16
    ):
        stage = "cvr"
        issue = "下单承接偏弱"
        diagnosis = "用户愿意点进来，但价格价值感、套餐结构或信任证据不足。"
        decision_path = ["销量变化", "曝光正常", "CTR 基本正常", "CVR 下降", "检查价格、套餐和评价承接"]
        evidence = [f"当前 CVR {item.observe_cvr * 100:.1f}%"] if item.observe_cvr is not None else []
        if item.cvr_delta_pct is not None:
            evidence.append(f"CVR 较基线变化 {item.cvr_delta_pct:.1f}%")
        root_causes = [
            ProductRootCause(
                code="value_and_bundle",
                stage=stage,
                title="价格价值感与套餐承接不足",
                explanation="点击后没有形成下单，需要先强化份量、搭配和价格锚点，而不是直接全店降价。",
                confidence=0.79,
                evidence=evidence,
            )
        ]
    elif item.orders_delta_pct is not None and item.orders_delta_pct <= -5:
        stage = "orders"
        issue = "销量走弱但漏斗暂未定位"
        diagnosis = "点击与转化没有单点异常，需要继续排查客单、复购、时段和竞争分流。"
        decision_path = ["销量下降", "曝光/CTR/CVR 无显著单点异常", "继续检查客单、复购与竞争"]
        root_causes = [
            ProductRootCause(
                code="demand_or_repurchase",
                stage=stage,
                title="需求或复购变化",
                explanation="当前漏斗证据不足以归因到图、标题或价格，先补时段和复购证据。",
                confidence=0.58,
                evidence=[f"订单较基线变化 {item.orders_delta_pct:.1f}%"],
            )
        ]
    else:
        stage = "stable"
        issue = "商品表现基本稳定"
        diagnosis = "当前没有强异常，适合用单变量低风险实验寻找增量。"
        decision_path = ["销量稳定", "曝光/CTR/CVR 未见强异常", "进入低风险增量实验"]
        root_causes = [
            ProductRootCause(
                code="incremental_opportunity",
                stage=stage,
                title="暂无强根因，存在增量优化空间",
                explanation="不建议同时改多个变量，先做一条可逆实验。",
                confidence=0.61,
                evidence=[item.rationale or "当前商品处于稳定观察位"],
            )
        ]
    return stage, issue, diagnosis, decision_path, root_causes


def _suggested_product_title(item: _ItemSnapshot) -> str:
    name = item.name.strip()
    if any(token in name for token in ("牛肉", "牛腩", "肥牛")) and not any(
        token in name for token in ("厚切", "黑椒", "招牌")
    ):
        return f"黑椒厚切{name}"
    return f"{name}｜现制热卖·分量看得见"


def _product_suggestions(item: _ItemSnapshot, stage: str) -> list[ProductSuggestion]:
    suggestions: list[ProductSuggestion] = []
    if stage in {"impressions", "ctr", "stable"}:
        suggestions.extend(
            [
                ProductSuggestion(
                    type="image",
                    action_type="change_main_image",
                    title="主图优化",
                    detail="放大主菜主体，突出真实份量和热气，背景降噪，不叠加营销贴纸。",
                    priority=1,
                    expected_metric="ctr",
                    expected_lift_pct_low=3,
                    expected_lift_pct_high=10,
                    window_hours=24,
                    rollback_rule="24 小时 CTR 无改善或下降超过 2%，恢复原主图。",
                    generated_content={
                        "visual_brief": f"{item.name} 使用 45° 近景，主菜占画面 70%，突出肉量、酱汁和热气。",
                        "negative_constraints": ["不拼图", "不堆字", "不使用虚假份量"],
                    },
                ),
                ProductSuggestion(
                    type="title",
                    action_type="change_title",
                    title="标题重写",
                    detail="把口味、份量或场景卖点写进标题，避免只有品类名。",
                    priority=2,
                    expected_metric="ctr",
                    expected_lift_pct_low=2,
                    expected_lift_pct_high=8,
                    window_hours=24,
                    rollback_rule="24 小时 CTR 无改善，恢复原标题。",
                    generated_content={
                        "original_title": item.name,
                        "suggested_title": _suggested_product_title(item),
                    },
                ),
            ]
        )
    if stage in {"cvr", "orders"}:
        bundle_price = round(float(item.price or 30) + 6, 0)
        suggestions.extend(
            [
                ProductSuggestion(
                    type="bundle",
                    action_type="add_set_meal",
                    title="补低决策套餐",
                    detail="用主商品加饮品/小食形成清晰价格锚点，优先承接犹豫用户。",
                    priority=1,
                    expected_metric="cvr",
                    expected_lift_pct_low=2,
                    expected_lift_pct_high=9,
                    window_hours=72,
                    risk_level="medium",
                    rollback_rule="72 小时套餐 CVR 或连带单无改善，撤回套餐入口。",
                    generated_content={
                        "bundle_name": f"{item.name}+饮品套餐",
                        "suggested_price": bundle_price,
                        "bundle_logic": "主商品 + 低成本饮品，套餐价比单点合计低约 5%-8%。",
                    },
                ),
                ProductSuggestion(
                    type="price",
                    action_type="adjust_price_value",
                    title="价格价值感校准",
                    detail="先补份量、原料和套餐锚点表达，不直接降低商品基础价。",
                    priority=2,
                    expected_metric="cvr",
                    expected_lift_pct_low=1,
                    expected_lift_pct_high=6,
                    window_hours=72,
                    risk_level="medium",
                    rollback_rule="72 小时 CVR 无改善，撤回价格锚点表达。",
                    generated_content={
                        "current_price": item.price,
                        "value_points": ["真实份量", "现制口感", "套餐比单点更划算"],
                    },
                ),
            ]
        )
    return suggestions[:3]


def _rank_product_suggestions(
    item: _ItemSnapshot | None,
    suggestions: list[ProductSuggestion],
    recommendations: list[Recommendation],
    experiments: list[Experiment],
) -> list[ProductSuggestion]:
    if item is None or not suggestions:
        return suggestions

    ranked: list[tuple[float, int, ProductSuggestion]] = []
    total = len(suggestions)
    object_ref = f"item:{item.item_id}"
    for index, suggestion in enumerate(suggestions):
        action_type = suggestion.action_type or suggestion.type
        feedback = find_recent_action_feedback(
            recommendations,
            experiments,
            action_type=action_type,
            object_ref=object_ref,
        )
        generated_content = dict(suggestion.generated_content)
        if feedback is not None:
            generated_content.update(
                {
                    "feedback_result": feedback.result,
                    "feedback_note": feedback.note,
                    "feedback_lift_pct": feedback.lift_pct,
                }
            )
        ranked.append(
            (
                (total - index) + (feedback.score_delta if feedback is not None else 0.0),
                index,
                suggestion.model_copy(update={"generated_content": generated_content}),
            )
        )
    return [row[2] for row in sorted(ranked, key=lambda row: (-row[0], row[1]))]


def _product_candidates(ctx: _AgentContext) -> list[ProductCandidate]:
    average_price_values = [float(row.price) for row in ctx.item_snapshots if row.price is not None]
    average_price = sum(average_price_values) / len(average_price_values) if average_price_values else None
    candidates: list[ProductCandidate] = []
    for item in ctx.item_snapshots:
        health_score, _ = _product_health_dimensions(item)
        stage, issue, _, _, _ = _product_diagnosis(item, average_price)
        suggestions = _rank_product_suggestions(
            item,
            _product_suggestions(item, stage),
            ctx.recommendations,
            ctx.experiments,
        )
        importance = min(20, max(0, (item.order_share_pct or 0) * 0.35))
        opportunity_score = _bounded_score((100 - health_score) * 0.78 + importance + 25)
        candidates.append(
            ProductCandidate(
                item_id=item.item_id,
                name=item.name,
                role=item.role,
                health_score=health_score,
                opportunity_score=opportunity_score,
                diagnosis_stage=stage,
                issue=issue,
                recommended_action=suggestions[0].title if suggestions else "继续观察",
                order_share_pct=item.order_share_pct,
                ctr_delta_pct=item.ctr_delta_pct,
                cvr_delta_pct=item.cvr_delta_pct,
            )
        )
    candidates.sort(key=lambda row: (row.opportunity_score, row.order_share_pct or 0), reverse=True)
    return candidates[:6]


def _focus_item(ctx: _AgentContext, focus_item_id: str | None = None) -> _ItemSnapshot | None:
    if focus_item_id:
        return next((row for row in ctx.item_snapshots if row.item_id == focus_item_id), None)
    candidates = _product_candidates(ctx)
    if candidates:
        candidate_id = candidates[0].item_id
        return next((row for row in ctx.item_snapshots if row.item_id == candidate_id), None)
    return ctx.item_snapshots[0] if ctx.item_snapshots else None


def _build_product_agent(ctx: _AgentContext, focus_item_id: str | None = None) -> ProductAgentResult:
    item = _focus_item(ctx, focus_item_id=focus_item_id)
    experiment_map = _experiment_map(ctx)
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    stage = "unknown"
    issue = "主推商品需要先建立足够证据。"
    diagnosis = "先从一个低风险动作开始验证。"
    health_score = 0
    health_dimensions: list[ProductHealthDimension] = []
    decision_path: list[str] = []
    root_causes: list[ProductRootCause] = []
    average_price_values = [float(row.price) for row in ctx.item_snapshots if row.price is not None]
    average_price = sum(average_price_values) / len(average_price_values) if average_price_values else None
    if item:
        health_score, health_dimensions = _product_health_dimensions(item)
        stage, issue, diagnosis, decision_path, root_causes = _product_diagnosis(item, average_price)
    recommendations: list[ProductSuggestion] = []
    if item:
        recommendations = _rank_product_suggestions(
            item,
            _product_suggestions(item, stage),
            ctx.recommendations,
            ctx.experiments,
        )

    related_actions = _dedupe_strings([
        _recommendation_title(rec.action_type)
        for rec in ctx.recommendations
        if not item or rec.object_ref.endswith(item.item_id) or rec.object_ref.startswith("store:")
    ])[:3]
    action_queue = [
        _workflow_item(rec, experiment_map, item_names)
        for rec in ctx.recommendations
        if not item or rec.object_ref.endswith(item.item_id) or rec.object_ref.startswith("store:")
    ][:3]
    action_queue, current_action = _product_sync_queue_with_suggestions(item, action_queue, recommendations)
    blockers = _document_blockers(ctx)
    readiness = _alignment_readiness(ctx)
    if not item:
        blockers.append("当前还没有明确主推商品，商品优化无法精准落点。")
        readiness = "blocked"
    why_now = None
    if item:
        weakest = min(health_dimensions, key=lambda row: row.score) if health_dimensions else None
        why_now = (
            f"{item.name} 健康度 {health_score} 分，当前最弱环节是{weakest.label}（{weakest.score} 分）。"
            if weakest
            else f"{item.name} 已进入商品优化优先队列。"
        )
    evidence = []
    if item:
        evidence.extend(
            [
                f"主推商品：{item.name}，订单占比 {item.order_share_pct:.1f}%。" if item.order_share_pct is not None else f"主推商品：{item.name}。",
                f"CTR 变化 {item.ctr_delta_pct:.1f}%。" if item.ctr_delta_pct is not None else "CTR 变化证据不足。",
                item.rationale,
            ]
        )
    for rec in ctx.recommendations[:2]:
        evidence.extend(_recommendation_evidence(rec))

    return ProductAgentResult(
        meta=_agent_meta("product", ctx.generated_at, ctx.hypothesis.confidence if ctx.hypothesis else 0.7),
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        focus_item_id=item.item_id if item else None,
        focus_item_name=item.name if item else "当前主推商品",
        health_score=health_score,
        health_dimensions=health_dimensions,
        diagnosis_stage=stage,
        issue=issue,
        diagnosis=diagnosis,
        why_now=why_now,
        metrics={
            "order_share_pct": item.order_share_pct if item else None,
            "orders": item.observe_orders if item else None,
            "orders_delta_pct": item.orders_delta_pct if item else None,
            "impressions": item.observe_impressions if item else None,
            "impressions_delta_pct": item.impressions_delta_pct if item else None,
            "ctr": item.observe_ctr if item else None,
            "ctr_delta_pct": item.ctr_delta_pct if item else None,
            "cvr": item.observe_cvr if item else None,
            "cvr_delta_pct": item.cvr_delta_pct if item else None,
            "price": item.price if item else None,
        },
        root_causes=root_causes,
        decision_path=decision_path,
        item_candidates=_product_candidates(ctx),
        evidence=list(dict.fromkeys(evidence))[:5],
        recommendations=recommendations,
        related_actions=related_actions,
        experiment_guardrail="一次只改一个变量；CTR 动作观察 24 小时，CVR/套餐动作观察 72 小时，再决定保留或回滚。",
        action_queue=action_queue,
        current_action=current_action,
    )


def _build_diagnosis_agent(db: Session, ctx: _AgentContext) -> DiagnosisAgentResult:
    primary_problem = ctx.store_state.primary_problem.type if ctx.store_state.primary_problem else "unknown"
    hypothesis = ctx.hypothesis
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    experiment_map = _experiment_map(ctx)
    full_action_queue = _dedupe_workflow_items(sorted(
        [_workflow_item(rec, experiment_map, item_names) for rec in ctx.recommendations],
        key=_workflow_phase_rank,
    ))
    current_action = _current_action(full_action_queue)
    action_queue = full_action_queue[:4]
    metric_key = "orders"
    if primary_problem == "store_ctr_down":
        metric_key = "ctr"
    elif primary_problem == "store_cvr_down":
        metric_key = "cvr"

    metric_row = ctx.store_state.kpis.get(metric_key)
    delta = metric_row.delta_pct if metric_row else None
    delta_text = f"{delta:.1f}%" if delta is not None else "暂无明显变化"
    daily_summary = f"{_metric_label(metric_key)} {delta_text}，{hypothesis.root_cause if hypothesis else _problem_summary(primary_problem)}"
    reasons = _json_loads_list(hypothesis.evidence_refs) if hypothesis else []
    if not reasons:
        reasons = [obs.what_happened for obs in ctx.observations[:2]] or [_problem_summary(primary_problem)]
    next_actions = (
        _dedupe_strings([item.title for item in action_queue[:3]])
        if action_queue
        else _dedupe_strings([_recommendation_title(rec.action_type) for rec in ctx.recommendations[:3]])
    )
    blockers = _document_blockers(ctx)
    workflow_summary = None
    if current_action is not None:
        workflow_summary = f"{_workflow_phase_summary(current_action)} {current_action.phase_reason}"
    if blockers:
        workflow_summary = blockers[0]
    readiness = _alignment_readiness(ctx)
    evidence = [
        f"主问题：{primary_problem}",
        f"{_metric_label(metric_key)} 变化：{delta_text}",
        *(reasons[:2]),
        ctx.document_alignment.get("summary", ""),
    ]
    comparisons = build_diagnosis_comparisons(db, ctx.store.id)
    metric_signals, data_gaps = build_diagnosis_signals(db, ctx.store_state)
    root_causes = build_diagnosis_root_causes(ctx.store_state, metric_signals)
    market_comparison = build_market_comparison(ctx.store_state)
    score = diagnosis_score(metric_signals, data_gaps)
    primary_root = root_causes[0] if root_causes else None
    executive_summary = (
        f"经营诊断 {score} 分。首要问题是{primary_root.title}；"
        f"{primary_root.explanation}"
        if primary_root
        else f"经营诊断 {score} 分，当前未发现单一强异常。"
    )
    priority_map = {
        "traffic_decline": "先排查流量入口、排序和时段曝光，不要直接改价格。",
        "first_impression": "先优化主推商品主图或标题，只执行一个 CTR 动作。",
        "conversion_weakness": "先修套餐、价格价值感与评价承接，观察 72 小时 CVR。",
        "aov_decline": "围绕主推款补搭配品或套餐，先验证客单与连带单。",
        "rating_decline": "先收敛差评主题并修正一个服务问题，再观察评分和 CVR。",
        "competition_pressure": "继续采集竞品快照，用真实变化辅助判断，不跟随盲目降价。",
        "no_strong_anomaly": "保持当前动作节奏，补齐退款、复购和商圈趋势数据。",
    }
    action_priorities = [priority_map[row.code] for row in root_causes if row.code in priority_map]
    if market_comparison.availability != "ready":
        data_gaps.append(market_comparison.note)

    diagnosis_narrative = narrate_diagnosis(
        store_name=ctx.store.name,
        diagnosis_score=score,
        primary_problem=primary_problem,
        daily_summary=daily_summary,
        root_causes=[r.model_dump(mode="json") for r in root_causes],
        metric_signals=[m.model_dump(mode="json") for m in metric_signals],
        next_actions=next_actions[:3],
        fallback_summary=executive_summary,
    )
    diagnosis_meta = _agent_meta("diagnosis", ctx.generated_at, hypothesis.confidence if hypothesis else 0.68)
    if diagnosis_narrative:
        diagnosis_meta.ai_narrative = diagnosis_narrative
        diagnosis_meta.ai_mode = "llm"
    return DiagnosisAgentResult(
        meta=diagnosis_meta,
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        diagnosis_score=score,
        executive_summary=executive_summary,
        daily_summary=daily_summary,
        primary_problem=primary_problem,
        root_cause=primary_root.title if primary_root else hypothesis.root_cause if hypothesis else None,
        comparisons=comparisons,
        metric_signals=metric_signals,
        root_causes=root_causes,
        market_comparison=market_comparison,
        data_gaps=list(dict.fromkeys(data_gaps))[:5],
        observations=[
            DiagnosisObservationView(
                metric=obs.metric,
                what_happened=obs.what_happened,
                delta_pct=obs.delta_pct,
                confidence=obs.confidence,
            )
            for obs in ctx.observations[:4]
        ],
        reasons=reasons[:3],
        evidence=[row for row in list(dict.fromkeys(evidence))[:5] if row],
        next_actions=next_actions[:3],
        action_priorities=list(dict.fromkeys(action_priorities))[:3],
        workflow_summary=workflow_summary,
        action_queue=action_queue,
        current_action=current_action,
    )


def _action_view(rec: Recommendation, item_names: dict[str, str]) -> GrowthActionView:
    object_name = "门店整体"
    if rec.object_ref.startswith("item:"):
        object_name = item_names.get(rec.object_ref.split(":", 1)[1], "当前主推商品")
    return GrowthActionView(
        action_type=rec.action_type,
        title=_recommendation_title(rec.action_type),
        object_name=object_name,
        summary=_recommendation_summary(rec.action_type),
        expected_metric=rec.expected_metric,
        window_hours=rec.window_hours,
        confidence=float(rec.confidence),
        score=round(_recommendation_priority(rec), 2),
    )


def _growth_score(
    expected_impact: float,
    confidence: float,
    ease: float,
    strategic_fit: float,
    risk: float,
) -> tuple[float, GrowthScoreFactors]:
    factors = GrowthScoreFactors(
        expected_impact=round(expected_impact, 2),
        confidence=round(confidence, 2),
        ease_of_execution=round(ease, 2),
        strategic_fit=round(strategic_fit, 2),
        risk=round(max(1.0, risk), 2),
    )
    score = expected_impact * confidence * ease * strategic_fit / max(1.0, risk) / 6.25
    return round(min(100.0, score), 1), factors


def _recommendation_source(action_type: str) -> str:
    if action_type in {"menu_patch", "menu_cleanup"}:
        return "menu"
    if action_type in {"change_main_image", "change_title", "add_set_meal", "adjust_price_value"}:
        return "product"
    if action_type in {
        "refresh_hero_image",
        "refresh_signature_card",
        "optimize_category_ia",
        "surface_set_meal",
        "reinforce_rating_zone",
    }:
        return "storefront"
    if action_type in {"join_lunch_campaign", "launch_value_bundle_promo", "match_competitor_promo"}:
        return "promo"
    if action_type in {"boost_hero_item_ads", "shift_ads_to_high_cvr_item", "pause_broad_ads"}:
        return "ads"
    if action_type in {"recall_churn_risk_users", "nurture_new_customers", "reward_vip_repeat"}:
        return "crm"
    if action_type in {
        "batch_reply_negative_reviews",
        "publish_service_reply_scripts",
        "escalate_portion_complaints",
    }:
        return "service"
    if action_type in {
        "fix_top_review_theme",
        "pin_positive_review_themes",
        "reply_rating_critical_reviews",
    }:
        return "review"
    if action_type in {
        "open_lunch_online_store",
        "open_night_online_store",
        "open_value_online_store",
    }:
        return "store_matrix"
    return "diagnosis"


def _append_matrix_opportunities(
    pool: list[GrowthOpportunityView],
    *,
    agent_key: str,
    actions: list[Any],
    unlock_ready: bool = True,
    store_name: str,
    strategy_memory: StrategyMemorySnapshot | None = None,
) -> None:
    if not actions:
        return
    action = actions[0]
    if agent_key in {"promo", "ads", "store_matrix"} and not unlock_ready:
        return
    impact = min(5.0, max(1.0, float(getattr(action, "expected_lift_pct_high", 4) or 4) / 2.5))
    risk = 3.5 if agent_key in {"promo", "ads", "store_matrix"} else 1.4
    ease = 4.5 if agent_key in {"service", "review"} else 3.0
    fit = 4.0 if unlock_ready else 2.5
    fit_delta, risk_delta = _memory_fit_bias(action.action_type, strategy_memory)
    fit = min(5.0, max(1.0, fit + fit_delta))
    risk = min(5.0, max(1.0, risk + risk_delta))
    score, factors = _growth_score(impact, 3.4, ease, fit, risk)
    pool.append(
        GrowthOpportunityView(
            key=f"{agent_key}:{action.action_type}:{action.object_name}",
            source_agent=agent_key,
            title=action.title,
            problem=action.detail,
            action_type=action.action_type,
            object_name=action.object_name or store_name,
            expected_metric=action.expected_metric,
            expected_lift_pct_low=action.expected_lift_pct_low,
            expected_lift_pct_high=action.expected_lift_pct_high,
            score=score,
            factors=factors,
            evidence=list(action.evidence or [])[:3],
            executable=True,
        )
    )


def _memory_fit_bias(action_type: str, memory: StrategyMemorySnapshot | None) -> tuple[float, float]:
    """Return (fit_delta, risk_delta) from Strategy Memory lessons."""
    if memory is None or not memory.items:
        return 0.0, 0.0
    fit_delta = 0.0
    risk_delta = 0.0
    for item in memory.items:
        if item.action_type != action_type:
            continue
        if item.result == "positive":
            fit_delta += 0.6
            risk_delta -= 0.3
        elif item.result == "negative":
            fit_delta -= 0.8
            risk_delta += 1.2
        elif item.result == "neutral":
            fit_delta -= 0.2
    return max(-1.5, min(1.5, fit_delta)), max(-1.0, min(2.0, risk_delta))


def _growth_opportunity_pool(
    ctx: _AgentContext,
    competition: CompetitionAgentResult,
    menu: MenuAgentResult,
    product: ProductAgentResult,
    diagnosis: DiagnosisAgentResult,
    promo: PromoAgentResult | None = None,
    ads: AdsAgentResult | None = None,
    crm: CrmAgentResult | None = None,
    service: ServiceAgentResult | None = None,
    review: ReviewAgentResult | None = None,
    store_matrix: StoreMatrixAgentResult | None = None,
    strategy_memory: StrategyMemorySnapshot | None = None,
) -> list[GrowthOpportunityView]:
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    primary_metric = "ctr" if product.diagnosis_stage == "ctr" else "cvr" if product.diagnosis_stage == "cvr" else "orders"
    ease_map = {
        "change_main_image": 5.0,
        "change_title": 5.0,
        "refresh_hero_image": 5.0,
        "refresh_signature_card": 4.8,
        "optimize_category_ia": 4.4,
        "reinforce_rating_zone": 4.2,
        "surface_set_meal": 3.4,
        "menu_cleanup": 4.3,
        "menu_patch": 3.6,
        "add_set_meal": 3.2,
        "adjust_price_value": 3.0,
        "store_discount": 2.0,
        "fix_top_review_theme": 4.0,
        "batch_reply_negative_reviews": 4.8,
        "pin_positive_review_themes": 4.5,
        "reply_rating_critical_reviews": 4.6,
        "recall_churn_risk_users": 3.5,
        "nurture_new_customers": 3.6,
        "reward_vip_repeat": 4.0,
        "publish_service_reply_scripts": 4.7,
        "escalate_portion_complaints": 3.4,
        "launch_value_bundle_promo": 2.8,
        "join_lunch_campaign": 2.2,
        "match_competitor_promo": 2.0,
        "boost_hero_item_ads": 2.0,
        "shift_ads_to_high_cvr_item": 2.3,
        "pause_broad_ads": 4.5,
        "open_lunch_online_store": 1.6,
        "open_night_online_store": 1.5,
        "open_value_online_store": 1.5,
    }
    risk_map = {
        "change_main_image": 1.0,
        "change_title": 1.0,
        "refresh_hero_image": 1.0,
        "refresh_signature_card": 1.1,
        "optimize_category_ia": 1.3,
        "reinforce_rating_zone": 1.2,
        "surface_set_meal": 1.8,
        "menu_cleanup": 1.8,
        "menu_patch": 1.6,
        "add_set_meal": 2.0,
        "adjust_price_value": 2.2,
        "store_discount": 4.0,
        "fix_top_review_theme": 1.5,
        "batch_reply_negative_reviews": 1.0,
        "pin_positive_review_themes": 1.1,
        "reply_rating_critical_reviews": 1.1,
        "recall_churn_risk_users": 2.0,
        "nurture_new_customers": 1.8,
        "reward_vip_repeat": 1.4,
        "publish_service_reply_scripts": 1.0,
        "escalate_portion_complaints": 1.8,
        "launch_value_bundle_promo": 2.8,
        "join_lunch_campaign": 3.6,
        "match_competitor_promo": 3.8,
        "boost_hero_item_ads": 4.0,
        "shift_ads_to_high_cvr_item": 3.5,
        "pause_broad_ads": 1.2,
        "open_lunch_online_store": 4.2,
        "open_night_online_store": 4.3,
        "open_value_online_store": 4.3,
    }
    experiment_map = _experiment_map(ctx)
    pool: list[GrowthOpportunityView] = []
    for rec in ctx.recommendations:
        action = _action_view(rec, item_names)
        experiment = experiment_map.get(rec.id)
        impact = min(5.0, max(1.0, float(rec.expected_lift_pct_high or rec.expected_lift_pct_low or 4) / 2.5))
        confidence = min(5.0, max(1.0, float(rec.confidence or 0.5) * 5))
        fit = 5.0 if rec.expected_metric == primary_metric else 4.0 if rec.object_ref.startswith("item:") else 3.2
        risk = risk_map.get(rec.action_type, 2.0)
        if experiment and experiment.result == "positive":
            confidence = min(5.0, confidence + 0.7)
            fit = min(5.0, fit + 0.5)
        elif experiment and experiment.result == "negative":
            confidence = max(1.0, confidence - 1.8)
            risk = min(5.0, risk + 2.0)
        elif experiment and experiment.result == "neutral":
            confidence = max(1.0, confidence - 0.8)
        fit_delta, risk_delta = _memory_fit_bias(rec.action_type, strategy_memory)
        fit = min(5.0, max(1.0, fit + fit_delta))
        risk = min(5.0, max(1.0, risk + risk_delta))
        score, factors = _growth_score(
            impact,
            confidence,
            ease_map.get(rec.action_type, 3.0),
            fit,
            risk,
        )
        recommendation_evidence = _recommendation_evidence(rec) or [action.summary]
        if experiment and experiment.result != "pending":
            recommendation_evidence.append(
                f"历史实验结果：{experiment.result}"
                + (f"，lift {experiment.lift_pct:+.1f}%" if experiment.lift_pct is not None else "")
            )
        pool.append(
            GrowthOpportunityView(
                key=f"recommendation:{rec.id}",
                source_agent=_recommendation_source(rec.action_type),
                title=action.title,
                problem=action.summary,
                action_type=rec.action_type,
                object_name=action.object_name,
                expected_metric=rec.expected_metric,
                expected_lift_pct_low=rec.expected_lift_pct_low,
                expected_lift_pct_high=rec.expected_lift_pct_high,
                score=score,
                factors=factors,
                evidence=recommendation_evidence,
                recommendation_id=rec.id,
                status=rec.status,
                executable=rec.status in {"proposed", "adopted", "executed"},
            )
        )

    if menu.suggested_patches:
        patch = menu.suggested_patches[0]
        score, factors = _growth_score(3.4, 3.6, 3.3, 4.2, 1.8)
        pool.append(
            GrowthOpportunityView(
                key=f"menu:{patch.patch_type}:{patch.item_name}",
                source_agent="menu",
                title=f"补齐菜单结构：{patch.item_name}",
                problem=patch.reason,
                action_type="menu_patch",
                object_name=patch.item_name,
                expected_metric="orders",
                expected_lift_pct_low=2,
                expected_lift_pct_high=8,
                score=score,
                factors=factors,
                evidence=[patch.reason, patch.expected_outcome],
                executable=True,
            )
        )
    if competition.actions:
        score, factors = _growth_score(
            3.2,
            min(5.0, max(1.0, float(competition.meta.confidence or 0.5) * 5)),
            3.5,
            3.8,
            1.7,
        )
        pool.append(
            GrowthOpportunityView(
                key="competition:response",
                source_agent="competition",
                title="应对商圈竞争变化",
                problem=competition.conclusion,
                action_type="competition_response",
                object_name=ctx.store.name,
                expected_metric="orders",
                expected_lift_pct_low=1,
                expected_lift_pct_high=5,
                score=score,
                factors=factors,
                evidence=competition.evidence[:3],
                executable=True,
            )
        )
    if diagnosis.root_causes:
        root = diagnosis.root_causes[0]
        priority = diagnosis.action_priorities[0] if diagnosis.action_priorities else root.explanation
        score, factors = _growth_score(4.0, root.confidence * 5, 3.8, 5.0, 1.4)
        pool.append(
            GrowthOpportunityView(
                key=f"diagnosis:{root.code}",
                source_agent="diagnosis",
                title=f"先解决：{root.title}",
                problem=priority,
                action_type="diagnosis_priority",
                object_name=ctx.store.name,
                expected_metric=root.affected_metrics[0] if root.affected_metrics else "orders",
                score=score,
                factors=factors,
                evidence=root.evidence,
                executable=root.code != "no_strong_anomaly",
            )
        )

    if review is not None:
        _append_matrix_opportunities(
            pool,
            agent_key="review",
            actions=review.priority_actions,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if service is not None:
        _append_matrix_opportunities(
            pool,
            agent_key="service",
            actions=service.priority_actions,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if crm is not None:
        _append_matrix_opportunities(
            pool,
            agent_key="crm",
            actions=crm.priority_actions,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if promo is not None:
        gated_promo = [
            action
            for action in promo.priority_actions[:2]
            if evaluate_profit_gate(
                ctx.store_state.profit,
                action_type=action.action_type,
                expected_order_lift_pct=float(action.expected_lift_pct_high or 0),
                system_mode=ctx.system_mode,
            ).allowed
        ]
        _append_matrix_opportunities(
            pool,
            agent_key="promo",
            actions=gated_promo,
            unlock_ready=promo.unlock_ready,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if ads is not None:
        gated_ads = [
            action
            for action in ads.priority_actions[:2]
            if evaluate_profit_gate(
                ctx.store_state.profit,
                action_type=action.action_type,
                expected_order_lift_pct=float(action.expected_lift_pct_high or 0),
                system_mode=ctx.system_mode,
            ).allowed
        ]
        _append_matrix_opportunities(
            pool,
            agent_key="ads",
            actions=gated_ads,
            unlock_ready=ads.unlock_ready,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if store_matrix is not None:
        _append_matrix_opportunities(
            pool,
            agent_key="store_matrix",
            actions=store_matrix.priority_actions,
            unlock_ready=store_matrix.unlock_ready,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )

    unique: dict[tuple[str, str], GrowthOpportunityView] = {}
    for opportunity in sorted(pool, key=lambda row: row.score, reverse=True):
        unique.setdefault((opportunity.action_type, opportunity.object_name), opportunity)
    return list(unique.values())[:8]


def _growth_today_priority(
    current_action: AgentWorkflowItem | None,
    top_actions: list[GrowthActionView],
    selected: GrowthOpportunityView | None,
    weekly_plan: list[GrowthPlanStep],
) -> str | None:
    if current_action is not None:
        if current_action.execution_phase == "execute_now" and not _growth_is_discount_action(current_action.action_type):
            return current_action.title
        if current_action.execution_phase in {"observe", "review"}:
            return current_action.next_decision or current_action.phase_reason or current_action.title
    if selected is not None and not _growth_is_discount_action(selected.action_type):
        return selected.title
    if top_actions:
        preferred = next((action for action in top_actions if not _growth_is_discount_action(action.action_type)), None)
        return (preferred or top_actions[0]).title
    return weekly_plan[0].title if weekly_plan else None


def _build_growth_plan(
    ctx: _AgentContext,
    top_actions: list[GrowthActionView],
    current_action: AgentWorkflowItem | None,
    selected: GrowthOpportunityView | None,
    opportunity_pool: list[GrowthOpportunityView],
) -> list[GrowthPlanStep]:
    focus = (
        f"先改善 {selected.expected_metric}"
        if selected
        else "先修点击吸引力"
        if ctx.store_state.primary_problem and ctx.store_state.primary_problem.type == "store_ctr_down"
        else "先修转化承接"
    )
    pending_count = sum(1 for exp in ctx.experiments if exp.result == "pending")
    backup = next((row for row in opportunity_pool if selected and row.key != selected.key), None)
    plan: list[GrowthPlanStep] = []

    if current_action is not None and current_action.execution_phase == "observe":
        plan.append(
            GrowthPlanStep(
                day=1,
                title="先观察当前主动作",
                goal="避免在观察窗里叠加第二个同类动作",
                instruction=current_action.phase_reason or "当前主动作已执行，先盯观察指标。",
                verify=current_action.next_decision or "确认观察窗完成前不追加同类动作。",
                status="active",
                recommendation_id=current_action.recommendation_id,
                source_agent=selected.source_agent if selected else None,
                stop_condition=current_action.rollback_rule,
            )
        )
    elif current_action is not None and current_action.execution_phase == "review":
        plan.append(
            GrowthPlanStep(
                day=1,
                title="先复盘当前主动作",
                goal="根据结果决定放大还是回滚",
                instruction=current_action.phase_reason or "当前动作已经进入复盘阶段。",
                verify=current_action.next_decision or "确认下一步是放大、回滚还是切换策略。",
                status="review",
                recommendation_id=current_action.recommendation_id,
                source_agent=selected.source_agent if selected else None,
            )
        )
    elif selected:
        plan.append(
            GrowthPlanStep(
                day=1,
                title=selected.title,
                goal=focus,
                instruction=f"先推进 {selected.object_name} 的这一条动作，不叠加第二个高风险动作。",
                verify=f"按观察窗检查 {selected.expected_metric} 是否进入正向变化。",
                source_agent=selected.source_agent,
                recommendation_id=selected.recommendation_id,
                stop_condition="指标下降超过 2% 或触发动作回滚规则时立即停止。",
            )
        )
    plan.extend(
        [
            GrowthPlanStep(
                day=2,
                title="保持单变量观察",
                goal="保护实验归因",
                instruction="不改价格、不叠加活动，只记录流量、点击和转化变化。",
                verify=f"确认 {(selected.expected_metric if selected else '核心指标')} 口径稳定。",
                dependency="Day 1 动作已执行",
                stop_condition="数据口径异常时暂停判断并补资料。",
            ),
            GrowthPlanStep(
                day=3,
                title="第一次效果判断",
                goal="决定继续、回滚或等待",
                instruction="正向则保持；负向按回滚规则恢复；变化不足则继续观察。",
                verify="检查 Experiment result、lift 和 attribution quality。",
                dependency="至少完成 24-72 小时观察",
            ),
            GrowthPlanStep(
                day=4,
                title=backup.title if backup else "准备第二顺位动作",
                goal="只准备，不同时执行",
                instruction=(
                    f"准备 {backup.object_name} 的备选方案，但仅在第一动作无效时启用。"
                    if backup
                    else "复核前四个 Agent 是否出现新的高置信度机会。"
                ),
                verify=f"备选机会分 {backup.score:.1f}" if backup else "确认是否出现新机会。",
                source_agent=backup.source_agent if backup else None,
                recommendation_id=backup.recommendation_id if backup else None,
                dependency="Day 3 判断第一动作无效或已完成",
            ),
        GrowthPlanStep(
            day=5,
                title="执行或放弃备选动作",
                goal="避免无效动作堆积",
                instruction="只有第一动作无效且备选证据仍成立时才执行，否则维持有效动作。",
                verify="执行后重新建立独立观察窗。",
                dependency="Day 4 备选方案通过复核",
                stop_condition="第一动作仍在改善时，不切换动作。",
            ),
            GrowthPlanStep(
                day=6,
                title="沉淀本周实验结果",
                goal="形成可复用经验",
                instruction="记录建议、执行、基线、结果和是否有效。",
                verify=f"当前待验证实验 {pending_count} 条。",
            ),
        ]
    )

    plan.append(
        GrowthPlanStep(
            day=7,
            title="形成下周唯一优先级",
            goal="把有效动作变成策略",
            instruction="保留正向动作、回滚负向动作，只把一个最高分机会带到下周。",
            verify="下周计划仍保持一天一条主动作。",
        )
    )
    deduplicated = {step.day: step for step in plan}
    return [deduplicated[day] for day in sorted(deduplicated)[:7]]


def _build_matrix_input(db: Session, ctx: _AgentContext) -> MatrixAgentInput:
    siblings = db.execute(select(Store).where(Store.merchant_id == ctx.store.merchant_id)).scalars().all()
    primary = ctx.store_state.primary_problem.type if ctx.store_state.primary_problem else None
    return MatrixAgentInput(
        store=ctx.store,
        menu_items=ctx.menu_items,
        item_snapshots=ctx.item_snapshots,
        competition_changes=ctx.store_state.competition_changes,
        kpis=ctx.store_state.kpis,
        document_alignment=ctx.document_alignment,
        primary_problem_type=primary,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        generated_at=ctx.generated_at,
        days=ctx.days,
        sibling_stores=list(siblings),
        experiments=ctx.experiments,
    )


def _build_growth_agent(
    ctx: _AgentContext,
    competition: CompetitionAgentResult,
    menu: MenuAgentResult,
    product: ProductAgentResult,
    diagnosis: DiagnosisAgentResult,
    promo: PromoAgentResult | None = None,
    ads: AdsAgentResult | None = None,
    crm: CrmAgentResult | None = None,
    service: ServiceAgentResult | None = None,
    review: ReviewAgentResult | None = None,
    store_matrix: StoreMatrixAgentResult | None = None,
    strategy_memory: StrategyMemorySnapshot | None = None,
) -> GrowthAgentResult:
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    experiment_map = _experiment_map(ctx)
    top_actions = _dedupe_growth_actions([_action_view(rec, item_names) for rec in ctx.recommendations])[:3]
    full_action_queue = _dedupe_workflow_items(sorted(
        [_workflow_item(rec, experiment_map, item_names) for rec in ctx.recommendations],
        key=_workflow_phase_rank,
    ))
    current_action = _current_action(full_action_queue)
    action_queue = full_action_queue[:4]
    hypothesis_reason = ctx.hypothesis.root_cause if ctx.hypothesis else _problem_summary(
        ctx.store_state.primary_problem.type if ctx.store_state.primary_problem else None
    )
    blockers = _document_blockers(ctx)
    readiness = _alignment_readiness(ctx)
    execution_mode = "experiment"
    opportunity_pool = _growth_opportunity_pool(
        ctx,
        competition,
        menu,
        product,
        diagnosis,
        promo=promo,
        ads=ads,
        crm=crm,
        service=service,
        review=review,
        store_matrix=store_matrix,
        strategy_memory=strategy_memory,
    )
    ranked_executable_opportunities = sorted(
        [row for row in opportunity_pool if row.executable],
        key=lambda row: (_growth_action_bias(row.action_type), -(row.score or 0.0)),
    )
    locked_current_opportunity = next(
        (
            row
            for row in opportunity_pool
            if current_action
            and row.recommendation_id == current_action.recommendation_id
            and (
                not _growth_is_discount_action(current_action.action_type)
                or current_action.execution_phase in {"observe", "review"}
            )
        ),
        None,
    )
    selected = (
        locked_current_opportunity
        or (ranked_executable_opportunities[0] if ranked_executable_opportunities else None)
        or (opportunity_pool[0] if opportunity_pool else None)
    )
    action_queue, current_action = _growth_sync_queue_with_selection(ctx, action_queue, selected)
    weekly_plan = _build_growth_plan(ctx, top_actions, current_action, selected, opportunity_pool)
    reason = (
        f"{selected.title} 是当前最高分的可执行机会（{selected.score:.1f}），且最符合经营主问题。"
        if selected
        else hypothesis_reason
    )
    if current_action is not None and current_action.execution_phase == "observe":
        reason = f"{hypothesis_reason} 当前先观察已执行动作，避免连续叠加第二个同类实验。"
    elif current_action is not None and current_action.execution_phase == "review":
        reason = f"{hypothesis_reason} 当前先复盘已有结果，再决定是否继续放大。"
    evidence = [
        ctx.document_alignment.get("summary", ""),
        f"待验证实验 {sum(1 for exp in ctx.experiments if exp.result == 'pending')} 条。",
        *(selected.evidence[:2] if selected else []),
    ]
    if ctx.document_alignment.get("status") in {"conflict", "missing_documents"}:
        execution_mode = "alignment_first"
        reason = "资料还没对齐，先修正事实源，再推进经营动作。"
        weekly_plan = [
            GrowthPlanStep(
                day=1,
                title="统一资料口径",
                goal="让 5 个 agent 说的是同一家店",
                instruction=(ctx.document_alignment.get("recommendations") or ["先补齐原始资料。"])[0],
                verify="对齐状态至少进入 partial，再继续经营动作。",
                stop_condition="对齐状态未达到 partial 时，不得执行经营动作。",
            ),
            GrowthPlanStep(
                day=2,
                title="补齐关键证据",
                goal="补门店、菜单、商圈等关键字段",
                instruction="把截图备注、菜单说明、复盘笔记补进系统。",
                verify="alignment_score 提升，并消除高优先级冲突。",
                dependency="Day 1 已完成事实源检查",
            ),
            GrowthPlanStep(
                day=3,
                title="重新计算机会分",
                goal="用对齐后的事实重排优先级",
                instruction="重新汇总竞争、菜单、商品和诊断 Agent 的候选机会。",
                verify="确认最高分机会具备证据、执行对象与预期指标。",
                dependency="资料状态至少进入 partial",
            ),
            GrowthPlanStep(
                day=4,
                title=selected.title if selected else "执行唯一主动作",
                goal="启动本周单变量实验",
                instruction=(
                    f"资料通过复核后，只推进 {selected.object_name} 这一条动作。"
                    if selected
                    else "只执行重新排序后的第一顺位动作。"
                ),
                verify=f"观察 {selected.expected_metric}" if selected else "建立明确观察指标。",
                source_agent=selected.source_agent if selected else None,
                recommendation_id=selected.recommendation_id if selected else None,
                dependency="Day 3 机会排序完成",
                stop_condition="资料仍有高优先级冲突时继续暂停。",
            ),
            GrowthPlanStep(
                day=5,
                title="保持单变量观察",
                goal="保护实验归因",
                instruction="不叠加第二个动作，记录流量、点击和转化变化。",
                verify="确认数据口径稳定。",
                dependency="Day 4 动作已执行",
            ),
            GrowthPlanStep(
                day=6,
                title="判断继续或回滚",
                goal="让结果决定下一步",
                instruction="正向则保持，负向按回滚规则恢复，证据不足则继续观察。",
                verify="记录 lift、result 与 attribution quality。",
            ),
            GrowthPlanStep(
                day=7,
                title="形成下周唯一优先级",
                goal="把结果沉淀成策略",
                instruction="保留有效动作、回滚负向动作，只带一个机会进入下周。",
                verify="建议、执行、基线和结果均已记录。",
            ),
        ]
        current_action = None
    experiments_summary = {
        "pending": sum(1 for exp in ctx.experiments if exp.result == "pending"),
        "positive": sum(1 for exp in ctx.experiments if exp.result == "positive"),
        "neutral": sum(1 for exp in ctx.experiments if exp.result == "neutral"),
        "negative": sum(1 for exp in ctx.experiments if exp.result == "negative"),
    }
    completed = experiments_summary["positive"] + experiments_summary["neutral"] + experiments_summary["negative"]
    total_experiments = completed + experiments_summary["pending"]
    plan_progress_pct = round(completed / total_experiments * 100) if total_experiments else 0
    if strategy_memory and strategy_memory.positive_patterns:
        learning_summary = f"经验库提示优先复用：{strategy_memory.positive_patterns[0]}"
    elif strategy_memory and strategy_memory.negative_patterns:
        learning_summary = f"经验库提示避免：{strategy_memory.negative_patterns[0]}"
    elif experiments_summary["positive"]:
        learning_summary = f"已有 {experiments_summary['positive']} 条动作验证有效，优先放大同类低风险动作。"
    elif experiments_summary["negative"]:
        learning_summary = f"已有 {experiments_summary['negative']} 条动作效果为负，先回滚并降低同类动作优先级。"
    elif experiments_summary["pending"]:
        learning_summary = f"当前有 {experiments_summary['pending']} 条实验等待观察，暂不叠加新的高风险动作。"
    else:
        learning_summary = "还没有完成实验，请先执行今日唯一主动作建立第一条有效经验。"
    weekly_goal = (
        "提升主推商品点击率"
        if selected and selected.expected_metric == "ctr"
        else "提升下单转化率"
        if selected and selected.expected_metric == "cvr"
        else "稳住订单并改善经营结构"
    )


    growth_narrative = narrate_growth(
        store_name=ctx.store.name,
        selected_title=selected.title if selected else None,
        weekly_goal=weekly_goal,
        experiments_summary=experiments_summary,
        learning_summary=learning_summary,
        do_not_do=[
            "不要在一个观察窗里频繁切换高风险动作。",
            "不要在还没看清 CTR/CVR 之前直接降价。",
            "不要同时执行两个来源不同的 Agent 动作，避免无法归因。",
        ],
        fallback_reason=reason,
    )
    growth_meta = _agent_meta("growth", ctx.generated_at, ctx.hypothesis.confidence if ctx.hypothesis else 0.7)
    if growth_narrative:
        growth_meta.ai_narrative = growth_narrative
        growth_meta.ai_mode = "llm"
    return GrowthAgentResult(
        meta=growth_meta,
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        execution_mode=execution_mode,
        strategy_score=round(selected.score) if selected else 0,
        weekly_goal=weekly_goal,
        today_priority=(
            _growth_today_priority(current_action, top_actions, selected, weekly_plan)
            if execution_mode == "experiment"
            else weekly_plan[0].title
            if weekly_plan
            else None
        ),
        reason=reason,
        evidence=[row for row in list(dict.fromkeys(evidence))[:5] if row],
        opportunity_pool=opportunity_pool,
        selected_opportunity=selected,
        action_queue=action_queue if execution_mode == "experiment" else [],
        current_action=current_action if execution_mode == "experiment" else None,
        experiments_summary=experiments_summary,
        learning_summary=learning_summary,
        plan_progress_pct=plan_progress_pct,
        top_actions=top_actions,
        weekly_plan=weekly_plan,
        do_not_do=[
            "不要在一个观察窗里频繁切换高风险动作。",
            "不要在还没看清 CTR/CVR 之前直接降价。",
            "不要同时执行两个来源不同的 Agent 动作，避免无法归因。",
        ],
    )


def _build_storefront_agent(db: Session, ctx: _AgentContext) -> StorefrontAgentResult:
    primary = ctx.store_state.primary_problem.type if ctx.store_state.primary_problem else None
    result = build_storefront_diagnosis(
        db,
        StorefrontInput(
            store=ctx.store,
            menu_items=ctx.menu_items,
            item_snapshots=ctx.item_snapshots,
            competition_changes=ctx.store_state.competition_changes,
            kpis=ctx.store_state.kpis,
            document_alignment=ctx.document_alignment,
            primary_problem_type=primary,
            hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
            generated_at=ctx.generated_at,
        ),
    )
    result = prioritize_storefront_actions(result, ctx.recommendations, ctx.experiments)
    return attach_storefront_queue(result, ctx.recommendations, ctx.experiments)


def create_storefront_action(
    db: Session,
    store_id: str,
    action_index: int,
    days: int = 7,
    with_ai: bool = True,
) -> StorefrontActionCreateResponse | None:
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None
    diagnosis = _build_storefront_agent(db, ctx)
    if action_index < 0 or action_index >= len(diagnosis.priority_actions):
        raise IndexError("storefront action not found")
    action = diagnosis.priority_actions[action_index]
    if with_ai:
        enriched = enrich_action_with_ai(
            action=action.model_dump(mode="json"),
            storefront=diagnosis,
            store_name=ctx.store.name,
            category=getattr(ctx.store.merchant, "category", None) if ctx.store.merchant else None,
        )
        action = StorefrontPriorityAction(**{k: enriched[k] for k in StorefrontPriorityAction.model_fields})
    return _create_storefront_action_record(
        db,
        store_id=store_id,
        action_index=action_index,
        diagnosis=diagnosis,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        action_override=action,
    )


def assist_storefront_renovation(db: Session, store_id: str, days: int = 7) -> dict[str, Any] | None:
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None
    diagnosis = _build_storefront_agent(db, ctx)
    plan = assist_storefront_decorate(
        storefront=diagnosis,
        store_name=ctx.store.name,
        category=getattr(ctx.store.merchant, "category", None) if ctx.store.merchant else None,
        city=ctx.store.city,
        audience=ctx.store.primary_audience,
    )
    return {
        "store_id": store_id,
        "health_score": diagnosis.health_score,
        "assist_type": "decorate",
        "plan": plan,
    }


def assist_storefront_image(
    db: Session,
    store_id: str,
    *,
    item_id: str | None = None,
    item_name: str | None = None,
    problem: str | None = None,
    days: int = 7,
) -> dict[str, Any] | None:
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None
    diagnosis = _build_storefront_agent(db, ctx)

    target_name = item_name
    has_image = False
    ctr_delta = None
    category = getattr(ctx.store.merchant, "category", None) if ctx.store.merchant else None
    if item_id:
        snap = next((row for row in ctx.item_snapshots if row.item_id == item_id), None)
        menu_row = next((row for row in ctx.menu_items if row.get("item_id") == item_id), None)
        if snap:
            target_name = snap.name
            has_image = bool(snap.image_url)
            ctr_delta = snap.ctr_delta_pct
            category = snap.category or category
        elif menu_row:
            target_name = menu_row.get("name")
            has_image = bool(menu_row.get("image_url"))
            category = menu_row.get("category") or category
    if not target_name:
        top = sorted(ctx.item_snapshots, key=lambda row: row.observe_orders or 0, reverse=True)
        if top:
            target_name = top[0].name
            has_image = bool(top[0].image_url)
            ctr_delta = top[0].ctr_delta_pct
            category = top[0].category or category
        else:
            target_name = "招牌主推"

    plan = assist_image_optimize(
        storefront=diagnosis,
        item_name=target_name,
        category=category,
        store_name=ctx.store.name,
        has_image=has_image,
        ctr_delta_pct=ctr_delta,
        problem=problem,
    )
    return {
        "store_id": store_id,
        "item_name": target_name,
        "assist_type": "image_optimize",
        "plan": plan,
    }


def _with_action_gates(agent_key: AgentKey, result, store_state: StoreState):
    unlock_ready = bool(getattr(result, "unlock_ready", True))
    blockers = list(getattr(result, "blockers", None) or [])
    actions = annotate_action_gates(
        list(result.priority_actions or []),
        agent_key=agent_key,
        unlock_ready=unlock_ready,
        blockers=blockers,
        profit_state=store_state.profit if agent_key in {"promo", "ads"} else None,
    )
    return result.model_copy(update={"priority_actions": actions})


def build_store_agents(db: Session, store_id: str, days: int = 7) -> StoreAgentsResponse | None:
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None

    competition = _build_competition_agent(db, ctx)
    menu = _build_menu_agent(ctx)
    product = _build_product_agent(ctx)
    storefront = _build_storefront_agent(db, ctx)
    diagnosis = _build_diagnosis_agent(db, ctx)

    matrix_input = _build_matrix_input(db, ctx)
    promo = _with_action_gates("promo", build_promo_agent(db, matrix_input, ctx.recommendations), ctx.store_state)
    ads = _with_action_gates("ads", build_ads_agent(db, matrix_input, ctx.recommendations), ctx.store_state)
    crm = _with_action_gates("crm", build_crm_agent(db, matrix_input, ctx.recommendations), ctx.store_state)
    service = _with_action_gates("service", build_service_agent(db, matrix_input, ctx.recommendations), ctx.store_state)
    review = _with_action_gates("review", build_review_agent(db, matrix_input, ctx.recommendations), ctx.store_state)
    store_matrix = _with_action_gates(
        "store_matrix",
        build_store_matrix_agent(db, matrix_input, ctx.recommendations),
        ctx.store_state,
    )

    strategy_memory = load_strategy_memory(db, store_id)
    growth = _build_growth_agent(
        ctx,
        competition,
        menu,
        product,
        diagnosis,
        promo=promo,
        ads=ads,
        crm=crm,
        service=service,
        review=review,
        store_matrix=store_matrix,
        strategy_memory=strategy_memory,
    )

    return StoreAgentsResponse(
        store_id=ctx.store.id,
        store_name=ctx.store.name,
        days=days,
        generated_at=ctx.generated_at,
        store_state=ctx.store_state,
        competition=competition,
        menu=menu,
        product=product,
        storefront=storefront,
        diagnosis=diagnosis,
        growth=growth,
        promo=promo,
        ads=ads,
        crm=crm,
        service=service,
        review=review,
        store_matrix=store_matrix,
    )


def create_matrix_agent_action(
    db: Session,
    store_id: str,
    agent_key: AgentKey,
    action_index: int,
    days: int = 7,
) -> AgentActionCreateResponse | None:
    if agent_key not in {"promo", "ads", "crm", "service", "review", "store_matrix"}:
        raise ValueError(f"agent_key does not support matrix actions: {agent_key}")
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None
    matrix_input = _build_matrix_input(db, ctx)
    builders = {
        "promo": build_promo_agent,
        "ads": build_ads_agent,
        "crm": build_crm_agent,
        "service": build_service_agent,
        "review": build_review_agent,
        "store_matrix": build_store_matrix_agent,
    }
    result = _with_action_gates(agent_key, builders[agent_key](db, matrix_input, ctx.recommendations), ctx.store_state)
    return create_matrix_action(
        db,
        store_id=store_id,
        agent_key=agent_key,
        action_index=action_index,
        actions=result.priority_actions,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        extra_content={"health_score": getattr(result, "health_score", None)},
    )


def apply_menu_patch(db: Session, store_id: str, patch_index: int, days: int = 7) -> MenuPatchApplyResponse | None:
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None

    items = ctx.item_snapshots
    _, gaps, _, _ = _menu_gap_profile(ctx, items)
    pricing_ladder = _menu_pricing_ladder(items)
    patches = _menu_patch_suggestions(ctx, items, pricing_ladder, gaps)
    if patch_index < 0 or patch_index >= len(patches):
        raise IndexError("menu patch suggestion not found")
    patch = patches[patch_index]

    normalized_name = _normalize_text(patch.item_name)
    existing = next((row for row in ctx.menu_items if _normalize_text(row.get("name")) == normalized_name), None)
    if existing is not None:
        raise ValueError(f"menu item already exists: {patch.item_name}")

    menu = _ensure_active_menu(db=db, store_id=store_id)
    item = MenuItem(store_id=store_id, menu_id=menu.id, is_active=True)
    db.add(item)
    db.flush()

    version = MenuItemVersion(
        item_id=item.id,
        name=patch.item_name,
        category=patch.suggested_category,
        price=patch.suggested_price,
        description=patch.reason,
        source="menu_agent_patch",
    )
    db.add(version)
    db.flush()

    item.current_version_id = version.id
    db.add(item)

    now = datetime.now(timezone.utc)
    action_type = _menu_patch_action_type(patch)
    expected_metric = _menu_patch_expected_metric(patch)
    action_payload = {"menu_patch": patch.model_dump(mode="json")}
    review_note = _menu_action_review_note(action_type, action_payload)
    observe_focus = _menu_action_observe_focus(action_type, action_payload)
    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        scope="item",
        object_ref=f"item:{item.id}",
        action_type=action_type,
        expected_metric=expected_metric,
        expected_lift_pct_low=3 if expected_metric == "orders" else 2,
        expected_lift_pct_high=10 if expected_metric in {"ctr", "cvr"} else 8,
        window_hours=72 if expected_metric == "ctr" else 168,
        rollback_rule=_menu_patch_rollback_rule(patch),
        confidence=0.76,
        evidence_json=json.dumps(
            [patch.reason, *[f"source:{source}" for source in patch.sources]],
            ensure_ascii=False,
        ),
        content_json=json.dumps(
            {
                **action_payload,
                "review_note": review_note,
                "observe_focus": observe_focus,
                "feedback_history": [
                    {"status": "executed", "at": now.isoformat(), "message": "已按菜单 Agent 修正方案落库"}
                ],
            },
            ensure_ascii=False,
        ),
        status="executed",
        adopted_at=now,
        executed_at=now,
    )
    db.add(recommendation)
    db.flush()

    metric = ctx.store_state.kpis.get(expected_metric)
    experiment = Experiment(
        recommendation_id=recommendation.id,
        store_id=store_id,
        item_id=item.id,
        baseline_value=metric.observed_value if metric else None,
        observed_value=None,
        lift_pct=None,
        baseline_from=ctx.store_state.window.from_day,
        baseline_to=ctx.store_state.window.to_day,
        observe_from=None,
        observe_to=None,
        control_desc="菜单修正方案执行后，等待下一观察窗回写。",
        attribution_quality="medium",
        result="pending",
        notes="菜单修正方案已执行，等待下一观察窗。",
    )
    db.add(experiment)
    db.commit()
    _invalidate_context_cache(store_id)
    db.refresh(item)
    db.refresh(recommendation)
    db.refresh(experiment)

    return MenuPatchApplyResponse(
        store_id=store_id,
        patch_index=patch_index,
        item_id=item.id,
        item_name=patch.item_name,
        recommendation_id=recommendation.id,
        experiment_id=experiment.id,
        status="executed",
        message=f"已创建菜单项 {patch.item_name}，并写入 recommendation/experiment 审计。",
        review_note=review_note,
        observe_focus=observe_focus,
        next_decision=observe_focus[0] if observe_focus else None,
        patch=patch,
    )


def apply_menu_cleanup(db: Session, store_id: str, candidate_index: int, days: int = 7) -> MenuCleanupApplyResponse | None:
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None

    candidates = _menu_cleanup_candidates(ctx, ctx.item_snapshots)
    if candidate_index < 0 or candidate_index >= len(candidates):
        raise IndexError("menu cleanup candidate not found")
    candidate = candidates[candidate_index]

    target_item = next((item for item in ctx.store.items if item.id == candidate.item_id), None)
    if target_item is None:
        raise ValueError(f"menu item not found: {candidate.item_name}")
    if not target_item.is_active:
        raise ValueError(f"menu item already inactive: {candidate.item_name}")

    now = datetime.now(timezone.utc)
    target_item.is_active = False
    db.add(target_item)
    action_payload = {"menu_cleanup": candidate.model_dump(mode="json")}
    review_note = _menu_action_review_note("menu_cleanup", action_payload)
    observe_focus = _menu_action_observe_focus("menu_cleanup", action_payload)

    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        scope="item",
        object_ref=f"item:{target_item.id}",
        action_type="menu_cleanup",
        expected_metric="cvr",
        expected_lift_pct_low=1,
        expected_lift_pct_high=6,
        window_hours=168,
        rollback_rule=_menu_cleanup_rollback_rule(),
        confidence=0.72,
        evidence_json=json.dumps([candidate.reason], ensure_ascii=False),
        content_json=json.dumps(
            {
                **action_payload,
                "review_note": review_note,
                "observe_focus": observe_focus,
                "feedback_history": [
                    {"status": "executed", "at": now.isoformat(), "message": "已按菜单 Agent 清理建议停用该 SKU"}
                ],
            },
            ensure_ascii=False,
        ),
        status="executed",
        adopted_at=now,
        executed_at=now,
    )
    db.add(recommendation)
    db.flush()

    metric = ctx.store_state.kpis.get("cvr")
    experiment = Experiment(
        recommendation_id=recommendation.id,
        store_id=store_id,
        item_id=target_item.id,
        baseline_value=metric.observed_value if metric else None,
        observed_value=None,
        lift_pct=None,
        baseline_from=ctx.store_state.window.from_day,
        baseline_to=ctx.store_state.window.to_day,
        observe_from=None,
        observe_to=None,
        control_desc="低效 SKU 停用测试后，观察整体承接和主推款分流变化。",
        attribution_quality="medium",
        result="pending",
        notes="低效 SKU 已停用，等待下一观察窗。",
    )
    db.add(experiment)
    db.commit()
    _invalidate_context_cache(store_id)
    db.refresh(target_item)
    db.refresh(recommendation)
    db.refresh(experiment)

    return MenuCleanupApplyResponse(
        store_id=store_id,
        candidate_index=candidate_index,
        item_id=target_item.id,
        item_name=candidate.name,
        recommendation_id=recommendation.id,
        experiment_id=experiment.id,
        status="executed",
        message=f"已停用 {candidate.name}，并写入 recommendation/experiment 审计。",
        review_note=review_note,
        observe_focus=observe_focus,
        next_decision=observe_focus[0] if observe_focus else None,
        candidate=candidate,
    )


def apply_menu_bundle(db: Session, store_id: str, opportunity_index: int, days: int = 7) -> MenuBundleApplyResponse | None:
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None

    opportunities = _menu_bundle_opportunities(ctx, ctx.item_snapshots)
    if opportunity_index < 0 or opportunity_index >= len(opportunities):
        raise IndexError("menu bundle opportunity not found")
    opportunity = opportunities[opportunity_index]

    normalized_name = _normalize_text(f"{opportunity.primary_item_name}+{opportunity.attach_item_name}套餐")
    existing = next((row for row in ctx.menu_items if _normalize_text(row.get("name")) == normalized_name), None)
    if existing is not None:
        raise ValueError(f"bundle already exists: {opportunity.primary_item_name}+{opportunity.attach_item_name}套餐")

    menu = _ensure_active_menu(db=db, store_id=store_id)
    item = MenuItem(store_id=store_id, menu_id=menu.id, is_active=True)
    db.add(item)
    db.flush()

    bundle_name = f"{opportunity.primary_item_name}+{opportunity.attach_item_name}套餐"
    version = MenuItemVersion(
        item_id=item.id,
        name=bundle_name,
        category="套餐",
        price=_bundle_target_price(opportunity, ctx),
        description=opportunity.reason,
        source="menu_agent_bundle",
    )
    db.add(version)
    db.flush()

    item.current_version_id = version.id
    db.add(item)

    now = datetime.now(timezone.utc)
    action_payload = {"menu_bundle": opportunity.model_dump(mode="json")}
    review_note = _menu_action_review_note("add_set_meal", action_payload)
    observe_focus = _menu_action_observe_focus("add_set_meal", action_payload)
    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        scope="item",
        object_ref=f"item:{item.id}",
        action_type="add_set_meal",
        expected_metric="cvr",
        expected_lift_pct_low=2,
        expected_lift_pct_high=9,
        window_hours=168,
        rollback_rule="观察 7 天套餐点击与连带单；若无改善则撤回该套餐。",
        confidence=0.78,
        evidence_json=json.dumps([opportunity.reason, opportunity.expected_outcome], ensure_ascii=False),
        content_json=json.dumps(
            {
                **action_payload,
                "review_note": review_note,
                "observe_focus": observe_focus,
                "feedback_history": [
                    {"status": "executed", "at": now.isoformat(), "message": "已按菜单 Agent 套餐机会创建套餐"}
                ],
            },
            ensure_ascii=False,
        ),
        status="executed",
        adopted_at=now,
        executed_at=now,
    )
    db.add(recommendation)
    db.flush()

    metric = ctx.store_state.kpis.get("cvr")
    experiment = Experiment(
        recommendation_id=recommendation.id,
        store_id=store_id,
        item_id=item.id,
        baseline_value=metric.observed_value if metric else None,
        observed_value=None,
        lift_pct=None,
        baseline_from=ctx.store_state.window.from_day,
        baseline_to=ctx.store_state.window.to_day,
        observe_from=None,
        observe_to=None,
        control_desc="新套餐上线后，观察套餐点击、连带单和整体转化。",
        attribution_quality="medium",
        result="pending",
        notes="套餐机会已执行，等待下一观察窗。",
    )
    db.add(experiment)
    db.commit()
    _invalidate_context_cache(store_id)
    db.refresh(item)
    db.refresh(recommendation)
    db.refresh(experiment)

    return MenuBundleApplyResponse(
        store_id=store_id,
        opportunity_index=opportunity_index,
        item_id=item.id,
        item_name=bundle_name,
        recommendation_id=recommendation.id,
        experiment_id=experiment.id,
        status="executed",
        message=f"已创建套餐 {bundle_name}，并写入 recommendation/experiment 审计。",
        review_note=review_note,
        observe_focus=observe_focus,
        next_decision=observe_focus[0] if observe_focus else None,
        opportunity=opportunity,
    )


def create_product_action(
    db: Session,
    store_id: str,
    suggestion_index: int,
    days: int = 7,
    item_id: str | None = None,
) -> ProductActionCreateResponse | None:
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None
    product = _build_product_agent(ctx, focus_item_id=item_id)
    if product.focus_item_id is None:
        raise ValueError("product focus item not found")
    if suggestion_index < 0 or suggestion_index >= len(product.recommendations):
        raise IndexError("product suggestion not found")

    suggestion = product.recommendations[suggestion_index]
    action_type = suggestion.action_type or suggestion.type
    object_ref = f"item:{product.focus_item_id}"
    metric_label = _metric_label(suggestion.expected_metric or ("cvr" if suggestion.type in {"bundle", "price"} else "ctr"))
    review_note = f"这次先围绕{metric_label}做单变量验证，观察窗结束后再决定放大还是回退。"
    observe_focus = [
        f"观察 {product.focus_item_name} 的{metric_label}是否进入正向变化。",
        "观察窗内不要叠加第二个同类商品动作。",
    ]
    next_decision = observe_focus[0]
    duplicate_candidates = db.execute(
        select(Recommendation)
        .where(
            Recommendation.store_id == store_id,
            Recommendation.object_ref == object_ref,
            Recommendation.action_type == action_type,
            Recommendation.status.in_(("proposed", "adopted", "executed")),
        )
        .order_by(Recommendation.created_at.desc())
    ).scalars().all()
    duplicate = None
    duplicate_experiment = None
    for candidate in duplicate_candidates:
        candidate_experiment = db.execute(
            select(Experiment)
            .where(Experiment.recommendation_id == candidate.id)
            .order_by(Experiment.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        duplicate_in_observation, _ = _recommendation_in_observation(candidate, candidate_experiment, ctx.generated_at)
        duplicate_is_active = candidate.status in {"proposed", "adopted"} or duplicate_in_observation
        if duplicate_is_active:
            duplicate = candidate
            duplicate_experiment = candidate_experiment
            break
    if duplicate is not None:
        duplicate_payload = _json_loads_dict(duplicate.content_json)
        duplicate_payload.update(
            {
                "source": "product_agent",
                "product_suggestion": suggestion.model_dump(mode="json"),
                "product_health_score": product.health_score,
                "diagnosis_stage": product.diagnosis_stage,
                "root_causes": [row.model_dump(mode="json") for row in product.root_causes],
                "review_note": review_note,
                "observe_focus": observe_focus,
                "next_decision": next_decision,
            }
        )
        duplicate.content_json = json.dumps(duplicate_payload, ensure_ascii=False)
        db.add(duplicate)
        db.commit()
        _invalidate_context_cache(store_id)
        db.refresh(duplicate)
        return ProductActionCreateResponse(
            store_id=store_id,
            item_id=product.focus_item_id,
            item_name=product.focus_item_name,
            suggestion_index=suggestion_index,
            recommendation_id=duplicate.id,
            experiment_id=duplicate_experiment.id if duplicate_experiment else None,
            status=duplicate.status,
            message=f"{product.focus_item_name} 已有同类动作，已返回现有任务，避免重复实验。",
            review_note=review_note,
            observe_focus=observe_focus,
            next_decision=next_decision,
            suggestion=suggestion,
        )

    confidence_values = [row.confidence for row in product.root_causes]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.65
    evidence = [
        product.why_now or product.diagnosis,
        *[evidence for cause in product.root_causes for evidence in cause.evidence[:2]],
    ]
    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        scope="item",
        object_ref=object_ref,
        action_type=action_type,
        expected_metric=suggestion.expected_metric or ("cvr" if suggestion.type in {"bundle", "price"} else "ctr"),
        expected_lift_pct_low=suggestion.expected_lift_pct_low,
        expected_lift_pct_high=suggestion.expected_lift_pct_high,
        window_hours=suggestion.window_hours,
        rollback_rule=suggestion.rollback_rule,
        confidence=round(confidence, 2),
        evidence_json=json.dumps(list(dict.fromkeys(evidence))[:5], ensure_ascii=False),
        content_json=json.dumps(
            {
                "source": "product_agent",
                "product_suggestion": suggestion.model_dump(mode="json"),
                "product_health_score": product.health_score,
                "diagnosis_stage": product.diagnosis_stage,
                "root_causes": [row.model_dump(mode="json") for row in product.root_causes],
                "review_note": review_note,
                "observe_focus": observe_focus,
                "next_decision": next_decision,
                "feedback_history": [
                    {
                        "status": "proposed",
                        "at": datetime.now(timezone.utc).isoformat(),
                        "message": "商品 Agent 已生成可执行动作",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        status="proposed",
    )
    db.add(recommendation)
    db.commit()
    _invalidate_context_cache(store_id)
    db.refresh(recommendation)
    return ProductActionCreateResponse(
        store_id=store_id,
        item_id=product.focus_item_id,
        item_name=product.focus_item_name,
        suggestion_index=suggestion_index,
        recommendation_id=recommendation.id,
        experiment_id=None,
        status=recommendation.status,
        message=f"已为 {product.focus_item_name} 生成「{suggestion.title}」动作，等待商家采纳。",
        review_note=review_note,
        observe_focus=observe_focus,
        next_decision=next_decision,
        suggestion=suggestion,
    )


def apply_product_action(
    db: Session,
    store_id: str,
    suggestion_index: int,
    days: int = 7,
    item_id: str | None = None,
) -> ProductActionCreateResponse | None:
    """执行商品优化动作——在系统内真正修改 MenuItemVersion。

    支持：
    - change_title：重写商品标题（写新 MenuItemVersion）
    - change_main_image：写入优化主图（系统内 Version；平台同步另需授权）
    - add_set_meal：创建套餐商品（新建 MenuItem + Version）
    - adjust_price_value：调整价格（写新 Version 改 price）

    和 menu agent 的 apply 一样，执行后自动建 Recommendation(executed) + Experiment(pending)。
    """
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None
    product = _build_product_agent(ctx, focus_item_id=item_id)
    if product.focus_item_id is None:
        raise ValueError("product focus item not found")
    if suggestion_index < 0 or suggestion_index >= len(product.recommendations):
        raise IndexError("product suggestion not found")

    suggestion = product.recommendations[suggestion_index]
    action_type = suggestion.action_type or suggestion.type
    now = datetime.now(timezone.utc)
    focus_item = next((it for it in ctx.store.items if it.id == product.focus_item_id), None)

    # 根据 action_type 执行不同的系统内修改
    new_item_id = product.focus_item_id
    new_item_name = product.focus_item_name

    if action_type == "add_set_meal":
        # 套餐：新建 MenuItem + Version（类似 menu bundle）
        menu = _ensure_active_menu(db=db, store_id=store_id)
        new_item = MenuItem(store_id=store_id, menu_id=menu.id, is_active=True)
        db.add(new_item)
        db.flush()
        bundle_name = suggestion.generated_content.get("bundle_name") or f"{product.focus_item_name} 套餐"
        price = suggestion.generated_content.get("suggested_price")
        version = MenuItemVersion(
            item_id=new_item.id,
            name=bundle_name,
            category="套餐",
            price=price,
            description=suggestion.detail,
            source="product_agent_set_meal",
        )
        db.add(version)
        db.flush()
        new_item.current_version_id = version.id
        db.add(new_item)
        new_item_id = new_item.id
        new_item_name = bundle_name
        _invalidate_context_cache(store_id)

    elif action_type == "change_title" and focus_item is not None:
        # 改标题：新建一个 Version（保留旧版本做回滚）
        current = focus_item.current_version
        new_title = (
            suggestion.generated_content.get("suggested_title")
            or suggestion.generated_content.get("title_candidate")
            or suggestion.title
        )
        version = MenuItemVersion(
            item_id=focus_item.id,
            name=new_title,
            category=current.category if current else None,
            price=current.price if current else None,
            description=current.description if current else None,
            image_url=current.image_url if current else None,
            source="product_agent_title",
        )
        db.add(version)
        db.flush()
        focus_item.current_version_id = version.id
        db.add(focus_item)
        new_item_name = new_title
        _invalidate_context_cache(store_id)

    elif action_type == "change_main_image" and focus_item is not None:
        current = focus_item.current_version
        image_url = (
            suggestion.generated_content.get("image_url")
            or suggestion.generated_content.get("optimized_image_url")
            or f"mealkey://optimized-main-image/{focus_item.id}"
        )
        version = MenuItemVersion(
            item_id=focus_item.id,
            name=current.name if current else product.focus_item_name,
            category=current.category if current else None,
            price=current.price if current else None,
            description=suggestion.generated_content.get("visual_brief")
            or (current.description if current else suggestion.detail),
            image_url=image_url,
            source="product_agent_main_image",
        )
        db.add(version)
        db.flush()
        focus_item.current_version_id = version.id
        db.add(focus_item)
        _invalidate_context_cache(store_id)

    elif action_type == "adjust_price_value" and focus_item is not None:
        # 调价：新建 Version 改 price
        current = focus_item.current_version
        new_price = suggestion.generated_content.get("suggested_price")
        if new_price is None and current and current.price:
            # 如果没给明确价格，按 suggestion 的方向微调（V1 简化）
            new_price = current.price
        version = MenuItemVersion(
            item_id=focus_item.id,
            name=current.name if current else product.focus_item_name,
            category=current.category if current else None,
            price=new_price,
            description=current.description if current else None,
            image_url=current.image_url if current else None,
            source="product_agent_price",
        )
        db.add(version)
        db.flush()
        focus_item.current_version_id = version.id
        db.add(focus_item)
        _invalidate_context_cache(store_id)

    # 写 Recommendation（executed）+ Experiment（pending）
    object_ref = f"item:{new_item_id}"
    expected_metric = suggestion.expected_metric or ("cvr" if suggestion.type in {"bundle", "price"} else "ctr")
    confidence = round(sum(r.confidence for r in product.root_causes) / len(product.root_causes), 2) if product.root_causes else 0.65
    evidence = [
        product.why_now or product.diagnosis,
        *[ev for cause in product.root_causes for ev in cause.evidence[:2]],
    ]
    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        scope="item",
        object_ref=object_ref,
        action_type=action_type,
        expected_metric=expected_metric,
        expected_lift_pct_low=suggestion.expected_lift_pct_low,
        expected_lift_pct_high=suggestion.expected_lift_pct_high,
        window_hours=suggestion.window_hours,
        rollback_rule=suggestion.rollback_rule,
        confidence=confidence,
        evidence_json=json.dumps(list(dict.fromkeys(evidence))[:5], ensure_ascii=False),
        content_json=json.dumps(
            {
                "product_suggestion": suggestion.model_dump(mode="json"),
                "product_health_score": product.health_score,
                "diagnosis_stage": product.diagnosis_stage,
                "executed_in_system": True,
                "new_item_name": new_item_name,
                "feedback_history": [
                    {"status": "executed", "at": now.isoformat(), "message": f"商品 Agent 已在系统内执行{new_item_name}的{action_type}"}
                ],
            },
            ensure_ascii=False,
        ),
        status="executed",
        adopted_at=now,
        executed_at=now,
    )
    db.add(recommendation)
    db.flush()

    metric = ctx.store_state.kpis.get(expected_metric)
    experiment = Experiment(
        recommendation_id=recommendation.id,
        store_id=store_id,
        item_id=new_item_id,
        baseline_value=metric.observed_value if metric else None,
        observed_value=None,
        lift_pct=None,
        baseline_from=ctx.store_state.window.from_day,
        baseline_to=ctx.store_state.window.to_day,
        observe_from=None,
        observe_to=None,
        control_desc=f"商品{action_type}后观察{expected_metric}变化",
        attribution_quality="high",
        result="pending",
        notes=f"{new_item_name}已执行{action_type}，等待观察窗。",
    )
    db.add(experiment)
    db.commit()
    _invalidate_context_cache(store_id)
    db.refresh(recommendation)
    db.refresh(experiment)

    observe_focus = [f"看 {new_item_name} 的 {expected_metric}", f"{suggestion.window_hours}h 后判断是否有效"]
    return ProductActionCreateResponse(
        store_id=store_id,
        item_id=new_item_id,
        item_name=new_item_name,
        suggestion_index=suggestion_index,
        recommendation_id=recommendation.id,
        experiment_id=experiment.id,
        status="executed",
        message=f"已在系统内执行{new_item_name}的{action_type}，并写入 recommendation/experiment 审计。",
        observe_focus=observe_focus,
        next_decision=observe_focus[0],
        suggestion=suggestion,
    )


def build_single_agent(db: Session, store_id: str, agent_key: AgentKey, days: int = 7) -> dict[str, Any] | None:
    payload = build_store_agents(db=db, store_id=store_id, days=days)
    if payload is None:
        return None
    return getattr(payload, agent_key).model_dump(mode="json")
