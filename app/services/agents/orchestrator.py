from __future__ import annotations
from typing import Any
from sqlalchemy.orm import Session
from app.schemas.agents import AgentKey, StoreAgentsResponse
from app.services.matrix_agents import (
    build_ads_agent,
    build_crm_agent,
    build_promo_agent,
    build_review_agent,
    build_service_agent,
    build_store_matrix_agent,
)
from app.services.strategy_memory import load_strategy_memory

from .types import _AgentContext
from .menu import _build_menu_agent
from .product import _build_product_agent
from .competition import _build_competition_agent
from .diagnosis import _build_diagnosis_agent
from .growth import _build_growth_agent
from .matrix_bridge import _build_matrix_input, _with_action_gates
from .storefront import _build_storefront_agent
from .context import _build_context

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
    strategy_memory = load_strategy_memory(db, store_id)
    promo = _with_action_gates("promo", build_promo_agent(db, matrix_input, ctx.recommendations), ctx.store_state, ctx.system_mode, strategy_memory)
    ads = _with_action_gates("ads", build_ads_agent(db, matrix_input, ctx.recommendations), ctx.store_state, ctx.system_mode, strategy_memory)
    crm = _with_action_gates("crm", build_crm_agent(db, matrix_input, ctx.recommendations), ctx.store_state, ctx.system_mode, strategy_memory)
    service = _with_action_gates("service", build_service_agent(db, matrix_input, ctx.recommendations), ctx.store_state, ctx.system_mode, strategy_memory)
    review = _with_action_gates("review", build_review_agent(db, matrix_input, ctx.recommendations), ctx.store_state, ctx.system_mode, strategy_memory)
    store_matrix = _with_action_gates(
        "store_matrix",
        build_store_matrix_agent(db, matrix_input, ctx.recommendations),
        ctx.store_state,
        ctx.system_mode,
        strategy_memory,
    )
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

def build_single_agent(db: Session, store_id: str, agent_key: AgentKey, days: int = 7) -> dict[str, Any] | None:
    payload = build_store_agents(db=db, store_id=store_id, days=days)
    if payload is None:
        return None
    return getattr(payload, agent_key).model_dump(mode="json")
