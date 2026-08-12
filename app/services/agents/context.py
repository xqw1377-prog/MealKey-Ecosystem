from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.ohre import (
    Experiment,
    Hypothesis,
    Observation,
    Recommendation,
)
from app.schemas.store_state import StoreState
from app.services.daily_job import run_daily_job
from app.services.document_alignment import build_document_alignment
from app.services.store_state import build_store_state

from .constants import ACTION_HISTORY_DAYS
from .types import _AgentContext, _ItemSnapshot
from .helpers import _delta_pct, _recommendation_priority, _sum_item_window
from .store_io import _load_store, _menu_items

def _invalidate_context_cache(store_id: str) -> None:
    """动作执行后失效 context 缓存，避免读到过期数据。best-effort，失败不阻塞。"""
    try:
        from app.services.agent_context_cache import invalidate
        invalidate(store_id)
    except Exception:  # noqa: BLE001
        pass

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
    from .menu import _recent_menu_action_state
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

build_agent_context = _build_context
