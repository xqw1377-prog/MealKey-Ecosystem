from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Menu, MenuItem, MenuItemVersion
from app.models.ohre import Experiment, Recommendation
from app.schemas.agents import (
    AgentWorkflowItem,
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
)
from app.services.agent_narrator import narrate_menu

from .constants import ACTION_HISTORY_DAYS
from .types import _AgentContext, _ItemSnapshot
from .helpers import (
    _agent_meta,
    _as_utc,
    _json_loads_dict,
    _normalize_text,
    _recommendation_in_observation,
)
from .workflow import (
    _current_action,
    _experiment_map,
    _workflow_item,
    _workflow_phase_rank,
    _workflow_phase_summary,
)

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

def apply_menu_patch(db: Session, store_id: str, patch_index: int, days: int = 7) -> MenuPatchApplyResponse | None:
    from .context import _build_context, _invalidate_context_cache
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

    # 绑定 work_thread_id (Track A: 同一件事贯穿三栏)
    from app.services.thread_engine import ensure_thread_for_action
    thread = ensure_thread_for_action(db, store_id, f"菜单优化：{action_type}")
    recommendation.work_thread_id = thread.id
    db.flush()

    metric = ctx.store_state.kpis.get(expected_metric)
    experiment = Experiment(
        recommendation_id=recommendation.id,
        store_id=store_id,
        work_thread_id=thread.id,
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
    from .context import _build_context, _invalidate_context_cache
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

    from app.services.thread_engine import ensure_thread_for_action
    thread = ensure_thread_for_action(db, store_id, "菜单清理优化")
    recommendation.work_thread_id = thread.id
    db.flush()

    metric = ctx.store_state.kpis.get("cvr")
    experiment = Experiment(
        recommendation_id=recommendation.id,
        store_id=store_id,
        work_thread_id=thread.id,
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
    from .context import _build_context, _invalidate_context_cache
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

    from app.services.thread_engine import ensure_thread_for_action
    thread = ensure_thread_for_action(db, store_id, "新增套餐优化")
    recommendation.work_thread_id = thread.id
    db.flush()

    metric = ctx.store_state.kpis.get("cvr")
    experiment = Experiment(
        recommendation_id=recommendation.id,
        store_id=store_id,
        work_thread_id=thread.id,
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
