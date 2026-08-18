from app.services.platform_sandbox import (
    apply_action,
    contrast,
    inject_world,
    reset_sandbox,
    simulate_tick,
    snapshot,
    spawn_twin,
)


def test_twin_title_write_and_incremental_is_l0() -> None:
    reset_sandbox()
    world = spawn_twin("w1", seed=2)
    inject_world("w1", "order_drop")

    apply_action(world.treatment_store_id, "update_product_title", {"new_title": "黑椒牛肉饭·新品名"})
    assert snapshot(world.treatment_store_id)["titles"]["hero_sku"] == "黑椒牛肉饭·新品名"
    assert snapshot(world.control_store_id)["titles"]["hero_sku"] == "招牌盖饭"

    simulate_tick("w1", hours=24)
    report = contrast("w1")
    assert report.treatment_orders > report.control_orders
    assert report.incremental_orders > 0
    assert report.evidence_grade == "L0_RESEARCH"
    assert report.may_authorize is False
    assert report.may_rank_production is False


def test_control_must_not_receive_action() -> None:
    reset_sandbox()
    world = spawn_twin("w2")
    apply_action(world.treatment_store_id, "update_product_title", {"new_title": "仅实验组"})
    assert snapshot(world.control_store_id)["titles"]["hero_sku"] != "仅实验组"


def test_same_seed_is_repeatable() -> None:
    reset_sandbox()
    spawn_twin("a", seed=7)
    inject_world("a", "order_drop")
    apply_action("a:treatment", "update_product_title", {"new_title": "A"})
    simulate_tick("a")
    first = contrast("a")

    reset_sandbox()
    spawn_twin("a", seed=7)
    inject_world("a", "order_drop")
    apply_action("a:treatment", "update_product_title", {"new_title": "A"})
    simulate_tick("a")
    second = contrast("a")
    assert first.incremental_orders == second.incremental_orders
    assert first.treatment_orders == second.treatment_orders
