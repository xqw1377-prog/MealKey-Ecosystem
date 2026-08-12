from __future__ import annotations
from typing import Any
from sqlalchemy.orm import Session
from app.schemas.agents import StorefrontActionCreateResponse, StorefrontAgentResult, StorefrontPriorityAction
from app.services.storefront_diagnosis import (
    StorefrontInput,
    attach_storefront_queue,
    build_storefront_diagnosis,
    create_storefront_action as _create_storefront_action_record,
    prioritize_storefront_actions,
)
from app.services.storefront_ai import assist_image_optimize, assist_storefront_decorate, enrich_action_with_ai

from .types import _AgentContext
from .context import _build_context

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
