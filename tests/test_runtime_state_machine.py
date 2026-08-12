from app.schemas.runtime import build_daily_operating_state, default_runtime_state_machine
from app.services.runtime_engine import determine_runtime_state


def test_default_runtime_state_machine_has_8_nodes() -> None:
    machine = default_runtime_state_machine()
    assert len(machine.nodes) == 8
    assert any(node.state == "pre_peak_decision" for node in machine.nodes)
    assert any(node.state == "peak_protect" and node.protect_mode for node in machine.nodes)


def test_runtime_state_machine_pre_peak_allows_owner_interrupt() -> None:
    machine = default_runtime_state_machine()
    node = next(node for node in machine.nodes if node.state == "pre_peak_decision")
    assert node.allow_owner_interrupt is True
    assert "TIME" in node.allowed_triggers
    assert "GOAL_DEVIATION" in node.allowed_triggers


def test_build_daily_operating_state_uses_runtime_node_defaults() -> None:
    state = build_daily_operating_state(
        current_state="peak_protect",
        active_goal="午餐利润提升",
        active_threads=["牛肉饭 Top3"],
    )
    assert state.current_node == "lunch_protect"
    assert state.protect_mode is True
    assert state.current_meal_period == "lunch"
    assert state.active_goal == "午餐利润提升"
    assert "ANOMALY" in state.pending_trigger_reasons


def test_determine_runtime_state_matches_daily_clock_windows() -> None:
    assert determine_runtime_state(hour=3) == "night_learn"
    assert determine_runtime_state(hour=7) == "daily_deep_review"
    assert determine_runtime_state(hour=10) == "pre_peak_decision"
    assert determine_runtime_state(hour=12) == "peak_protect"
    assert determine_runtime_state(hour=15) == "inter_peak_strategy"
    assert determine_runtime_state(hour=21) == "post_peak_review"
