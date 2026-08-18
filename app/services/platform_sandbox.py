"""PLATFORM-SB-01 in-memory Twin Sandbox.

Not a production connector. Results are always L0_RESEARCH.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.schemas.incremental_result import IncrementalResult, TreatmentSpec, may_authorize_action, may_influence_candidate_ranking
from app.schemas.platform_sandbox import ContrastReport, SandboxStoreState, TwinWorld, WriteReceipt

_WORLDS: dict[str, TwinWorld] = {}
_STORES: dict[str, SandboxStoreState] = {}
_BASELINE_ORDERS: dict[str, int] = {}

DEFAULT_SKU = "hero_sku"
DEFAULT_TITLE = "招牌盖饭"


def reset_sandbox() -> None:
    _WORLDS.clear()
    _STORES.clear()
    _BASELINE_ORDERS.clear()


def spawn_twin(world_id: str, *, seed: int = 1) -> TwinWorld:
    if world_id in _WORLDS:
        raise ValueError(f"world already exists: {world_id}")
    treatment_id = f"{world_id}:treatment"
    control_id = f"{world_id}:control"
    now = datetime.now(timezone.utc)
    world = TwinWorld(
        world_id=world_id,
        seed=seed,
        created_at=now,
        treatment_store_id=treatment_id,
        control_store_id=control_id,
    )
    for store_id, role in ((treatment_id, "treatment"), (control_id, "control")):
        _STORES[store_id] = SandboxStoreState(
            store_id=store_id,
            role=role,  # type: ignore[arg-type]
            titles={DEFAULT_SKU: DEFAULT_TITLE},
            images={DEFAULT_SKU: "https://sandbox.local/hero.jpg"},
            orders=20,
            gmv=800.0,
        )
        _BASELINE_ORDERS[store_id] = 20
    _WORLDS[world_id] = world
    return world


def get_store(store_id: str) -> SandboxStoreState:
    state = _STORES.get(store_id)
    if state is None:
        raise KeyError(store_id)
    return state


def apply_action(store_id: str, op: str, payload: dict[str, Any] | None = None) -> WriteReceipt:
    state = get_store(store_id)
    body = payload or {}
    if op == "update_product_title":
        sku = str(body.get("sku") or DEFAULT_SKU)
        new_title = str(body.get("new_title") or "").strip()
        if not new_title:
            raise ValueError("new_title required")
        state.titles[sku] = new_title
        read = state.titles.get(sku)
        if read != new_title:
            raise RuntimeError("read_back mismatch")
        return WriteReceipt(
            ok=True,
            op="update_product_title",
            store_id=store_id,
            expected={"title": new_title},
            applied={"title": new_title},
            read_back={"title": read},
            summary=f"title → {new_title}",
        )
    if op == "update_product_image":
        sku = str(body.get("sku") or DEFAULT_SKU)
        url = str(body.get("new_image_url") or "").strip()
        state.images[sku] = url
        return WriteReceipt(
            ok=True,
            op="update_product_image",
            store_id=store_id,
            expected={"image_url": url},
            applied={"image_url": url},
            read_back={"image_url": state.images.get(sku)},
            summary="image updated",
        )
    raise ValueError(f"sandbox write not allowed: {op}")


def inject(store_id: str, scenario: str, *, delta_orders: int | None = None) -> SandboxStoreState:
    state = get_store(store_id)
    if scenario == "order_drop":
        drop = 8 if delta_orders is None else abs(delta_orders)
        state.orders = max(0, state.orders - drop)
        state.gmv = max(0.0, state.gmv - drop * 40)
    elif scenario == "order_rise":
        rise = 6 if delta_orders is None else abs(delta_orders)
        state.orders += rise
        state.gmv += rise * 40
    elif scenario == "negative_review":
        state.reviews["r-neg"] = {"rating": 2, "content": "太咸", "replied": False}
    elif scenario == "sku_stockout":
        if DEFAULT_SKU not in state.paused_skus:
            state.paused_skus.append(DEFAULT_SKU)
    elif scenario == "price_changed":
        state.reviews.setdefault("_observe", {})["price_changed"] = True
    else:
        raise ValueError(f"unknown scenario: {scenario}")
    return state


def inject_world(world_id: str, scenario: str) -> None:
    world = _WORLDS[world_id]
    inject(world.treatment_store_id, scenario)
    inject(world.control_store_id, scenario)


def simulate_tick(world_id: str, *, hours: int = 24) -> TwinWorld:
    """同一需求过程打到两边；treatment 若标题已改，多获得一小部分订单。

    这是可重复的合成规则，不是生产需求模型。
    """
    world = _WORLDS[world_id]
    world.ticks += max(1, hours // 24)
    base_new = 4 + (world.seed % 3)
    for store_id in (world.control_store_id, world.treatment_store_id):
        state = get_store(store_id)
        extra = 0
        if state.role == "treatment" and state.titles.get(DEFAULT_SKU) != DEFAULT_TITLE:
            extra = 3
        if DEFAULT_SKU in state.paused_skus:
            extra -= 4
        gained = max(0, base_new + extra)
        state.orders += gained
        state.gmv += gained * 40
    return world


def contrast(world_id: str) -> ContrastReport:
    world = _WORLDS[world_id]
    treatment = get_store(world.treatment_store_id)
    control = get_store(world.control_store_id)
    baseline = _BASELINE_ORDERS[world.treatment_store_id]
    observed = None
    if baseline:
        observed = (treatment.orders - baseline) / baseline * 100.0
    incremental = treatment.orders - control.orders
    result = IncrementalResult(
        experiment_id=f"{world_id}:title",
        store_id=world.treatment_store_id,
        action_type="change_title",
        treatment=TreatmentSpec(treatment="change_title", control="no_action"),
        observed_lift_pct=observed,
        incremental_orders=float(incremental),
        evidence_grade="L0_RESEARCH",
        summary="sandbox twin contrast",
    )
    return ContrastReport(
        world_id=world_id,
        treatment_orders=treatment.orders,
        control_orders=control.orders,
        observed_lift_pct=observed,
        incremental_orders=incremental,
        may_authorize=may_authorize_action(result),
        may_rank_production=may_influence_candidate_ranking(result),
        notes="synthetic twin; L0 only",
    )


def snapshot(store_id: str) -> dict[str, Any]:
    return deepcopy(get_store(store_id).model_dump())
