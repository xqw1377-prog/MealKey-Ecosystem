from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Store
from app.schemas.agents import AgentActionCreateResponse, AgentKey
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
from app.services.strategy_memory import load_strategy_memory
from app.schemas.store_state import StoreState

from .types import _AgentContext
from .context import _build_context

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
        ads_observed=bool(getattr(ctx.store_state.data_coverage, "ads_observed", False)),
    )

def _with_action_gates(
    agent_key: AgentKey,
    result,
    store_state: StoreState,
    system_mode: str = "operating",
    strategy_memory=None,
):
    unlock_ready = bool(getattr(result, "unlock_ready", True))
    blockers = list(getattr(result, "blockers", None) or [])
    actions = annotate_action_gates(
        list(result.priority_actions or []),
        agent_key=agent_key,
        unlock_ready=unlock_ready,
        blockers=blockers,
        profit_state=store_state.profit if agent_key in {"promo", "ads"} else None,
        system_mode=system_mode,
        strategy_memory=strategy_memory,
    )
    return result.model_copy(update={"priority_actions": actions})

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
    result = _with_action_gates(
        agent_key,
        builders[agent_key](db, matrix_input, ctx.recommendations),
        ctx.store_state,
        getattr(ctx, "system_mode", "operating"),
        load_strategy_memory(db, store_id) if agent_key in {"promo", "ads"} else None,
    )
    return create_matrix_action(
        db,
        store_id=store_id,
        agent_key=agent_key,
        action_index=action_index,
        actions=result.priority_actions,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        extra_content={"health_score": getattr(result, "health_score", None)},
    )
