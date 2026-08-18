"""PLATFORM-SB-01 golden path: ActionSpec → twin write → read back → incremental L0."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.data_acquisition import IncrementalResultRecord
from app.services.action_registry import build_action_spec
from app.services.platform_sandbox import (
    apply_action,
    contrast,
    inject_world,
    reset_sandbox,
    simulate_tick,
    snapshot,
    spawn_twin,
)


def run_title_golden_path(db: Session | None = None, *, world_id: str = "sb01", seed: int = 2) -> dict[str, Any]:
    reset_sandbox()
    world = spawn_twin(world_id, seed=seed)
    inject_world(world_id, "order_drop")
    spec = build_action_spec(
        "change_title",
        object_name="招牌盖饭",
        reason="午餐订单下降（sandbox fixture）",
        pack={"suggested_title": "黑椒牛肉饭·午餐份", "current_problem": "午餐订单下降"},
    )
    from app.services.action_capability import assert_action_executable

    assert_action_executable(spec.get("registry_key") or "change_title")
    receipt = apply_action(
        world.treatment_store_id,
        "update_product_title",
        {"new_title": spec.get("execution_package", {}).get("copy_text") or "黑椒牛肉饭·午餐份"},
    )
    # 若 copy 为空，用明确测试标题
    if snapshot(world.treatment_store_id)["titles"]["hero_sku"] == "招牌盖饭":
        receipt = apply_action(
            world.treatment_store_id,
            "update_product_title",
            {"new_title": "黑椒牛肉饭·午餐份"},
        )
    simulate_tick(world_id, hours=24)
    report = contrast(world_id)
    if db is not None:
        db.add(
            IncrementalResultRecord(
                experiment_id=f"{world_id}:title",
                store_id=world.treatment_store_id,
                action_type="change_title",
                treatment="change_title",
                control="no_action",
                observed_lift_pct=report.observed_lift_pct,
                incremental_orders=float(report.incremental_orders),
                incremental_profit=None,
                evidence_grade="L0_RESEARCH",
                source="sandbox",
                summary=report.notes,
            )
        )
        db.commit()
    control_title = snapshot(world.control_store_id)["titles"]["hero_sku"]
    treatment_title = snapshot(world.treatment_store_id)["titles"]["hero_sku"]
    return {
        "world": world.model_dump(mode="json"),
        "action_spec": spec,
        "write": receipt.model_dump(),
        "read_back_ok": receipt.ok and receipt.read_back.get("title") == treatment_title,
        "control_unchanged": control_title == "招牌盖饭",
        "contrast": report.model_dump(),
        "may_authorize": report.may_authorize,
        "may_rank_production": report.may_rank_production,
        "executed_action": True,
        "production_truth": False,
    }
