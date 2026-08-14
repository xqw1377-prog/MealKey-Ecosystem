"""Operating Demand Library：100 个经营问题 → 1 个 AI 店长。"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.services.intent_compiler import compile_intent
from app.services.operating_demands.catalog import DEMANDS, by_code, coverage_counts
from app.services.operating_demands.golden import featured_cases, smoke_cases
from app.services.operating_demands.playbooks import run_playbook
from app.services.operating_demands.router import match_demand
from app.services.operating_demands.runner import facts_from_store_state, open_demand_loop
from app.services.poie.intent import handle_user_intent


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_library_has_exactly_100_demands() -> None:
    assert len(DEMANDS) == 100
    assert [item.id for item in DEMANDS] == list(range(1, 101))
    assert len({item.code for item in DEMANDS}) == 100


def test_loop_and_coverage_counts() -> None:
    counts = coverage_counts()
    assert counts["A"] == 50
    assert counts["B"] == 40
    assert counts["C"] == 10
    assert counts["green"] == 47
    assert counts["yellow"] == 47
    assert counts["red"] == 6


def test_every_demand_is_a_contract_not_a_chat() -> None:
    for item in DEMANDS:
        assert item.playbook
        assert item.actions
        assert item.execution in {"AUTO", "ASK_APPROVAL", "HUMAN_TASK"}
        assert item.metric
        assert item.window_hours >= 2
        assert item.loop in {"A", "B", "C"}
        assert item.coverage in {"green", "yellow", "red"}
        if item.loop == "C":
            assert item.execution == "HUMAN_TASK"
        if item.coverage == "red":
            assert item.id in {84, 85, 86, 87, 88, 89}
            assert item.blockers


def test_smoke_golden_set_covers_all_100() -> None:
    cases = smoke_cases()
    assert len(cases) == 100
    for case in cases:
        demand = next(item for item in DEMANDS if item.code == case.demand_code)
        verdict = run_playbook(demand, case.facts)
        assert verdict.demand.code == case.demand_code
        for banned in case.forbidden_diagnosis:
            assert banned not in verdict.diagnosis
        for banned in case.forbidden_action:
            assert banned not in verdict.action
        if demand.coverage == "red":
            assert verdict.execution == "HUMAN_TASK"
            assert verdict.blocked is False
            assert "整改" in verdict.action or "派" in verdict.action


def test_order_drop_golden_case() -> None:
    case = featured_cases()[0]
    demand = match_demand(case.question)
    assert demand is not None
    assert demand.code == "ORDER_DROP"
    verdict = run_playbook(demand, case.facts)
    assert case.expected_diagnosis in verdict.diagnosis
    assert case.expected_action in verdict.action
    for banned in case.forbidden_diagnosis:
        assert banned not in verdict.diagnosis
    for banned in case.forbidden_action:
        assert banned not in verdict.action
    assert verdict.execution == "ASK_APPROVAL"
    assert demand.window_hours == 48
    assert "CVR" in demand.guardrail


def test_next_best_is_the_core_product_demand() -> None:
    demand = match_demand("今天所有问题里，我现在只该做哪一件事？")
    assert demand is not None
    assert demand.id == 50
    assert demand.code == "NEXT_BEST"
    verdict = run_playbook(demand, {"ctr": -18.0, "cvr": -1.0, "profit": -2.0})
    assert "点击竞争力" in verdict.diagnosis
    assert "主图" in verdict.action or "首屏" in verdict.action


def test_follow_price_must_pass_profit_gate() -> None:
    demand = match_demand("对手降价了，我们到底要不要跟？")
    assert demand is not None
    assert demand.code == "FOLLOW_PRICE"
    verdict = run_playbook(
        demand,
        {"rival_price_delta": -12.0, "profit_gate_passed": False, "unit_profit": 1.2},
    )
    assert "利润门禁" in verdict.diagnosis or "不立即跟价" in verdict.action
    assert "立即跟价" not in verdict.action
    assert verdict.execution == "ASK_APPROVAL"


def test_compile_ask_attaches_demand_without_changing_kind() -> None:
    compiled = compile_intent("最近订单下降怎么办")
    assert compiled.kind == "ask"
    assert compiled.suggested_agent == "diagnosis"
    assert compiled.slots.get("demand_code") == "ORDER_DROP"


def test_boss_question_opens_operating_demand_not_chat() -> None:
    db = _session()
    seeded = seed_demo(db)
    result = handle_user_intent(db, seeded["store_id"], "今天怎么没单了？")
    assert result is not None
    assert result["mode"] == "operating_demand"
    assert result["demand"]["code"] == "ORDER_DROP"
    assert "平台限流" not in result["demand"]["diagnosis"]
    assert result.get("loop_id")


def test_weather_is_not_an_operating_demand() -> None:
    assert match_demand("今天天气怎么样") is None
    assert handle_user_intent(_session(), "s1", "今天天气怎么样") is None


def test_yellow_and_red_do_not_fake_last_mile() -> None:
    refund = next(item for item in DEMANDS if item.id == 8)
    cook = next(item for item in DEMANDS if item.id == 84)
    refund_verdict = run_playbook(refund, {})
    cook_verdict = run_playbook(cook, {})
    assert refund.coverage == "yellow"
    assert refund_verdict.blocked is True
    assert cook.coverage == "red"
    assert cook_verdict.execution == "HUMAN_TASK"
    assert cook_verdict.blocked is False
    assert "整改" in cook_verdict.action


def test_profit_family_uses_refund_specific_diagnosis() -> None:
    demand = by_code("REFUND_PROFIT")
    verdict = run_playbook(
        demand,
        {"refund_cost": 128.0, "payout_amount": 40.0, "profit": -12.0, "refund_ledger": True},
    )
    assert "退款赔付" in verdict.diagnosis
    assert "量化退款赔付" in verdict.action
    assert verdict.blocked is False


def test_crm_family_is_honest_when_identity_truth_missing() -> None:
    demand = by_code("HIGH_VALUE")
    verdict = run_playbook(
        demand,
        {"repurchase_rate": -6.0, "new_customer_share_pct": 18.0},
    )
    assert verdict.blocked is True
    assert "crm_identity" in verdict.missing_truth
    assert "缺少用户级复购明细" in verdict.diagnosis or "CRM 判断骨架已就位" in verdict.diagnosis


def test_competition_family_admits_proxy_truth_limits() -> None:
    demand = by_code("TRUE_RIVALS")
    verdict = run_playbook(
        demand,
        {"competition_changes_count": 3, "competitor_price_changes": 1},
    )
    assert verdict.blocked is False
    assert "代理快照" in verdict.diagnosis or "竞品判断" in verdict.diagnosis


def test_fulfillment_red_generates_human_task_not_fake_auto_fix() -> None:
    demand = by_code("CAPACITY_PEAK")
    verdict = run_playbook(
        demand,
        {"capacity_util": 0.92, "forecast_orders": 126},
    )
    assert verdict.execution == "HUMAN_TASK"
    assert verdict.blocked is False
    assert "备人备料" in verdict.action or "预警" in verdict.diagnosis


def test_chain_multi_platform_is_blocked_without_platform_truth() -> None:
    demand = by_code("MULTI_PLATFORM_PROFIT")
    verdict = run_playbook(demand, {})
    assert verdict.blocked is True
    assert "multi_platform" in verdict.missing_truth


def test_runner_extracts_nested_store_state_facts() -> None:
    db = _session()
    seeded = seed_demo(db)
    from app.services.store_state import build_store_state

    state = build_store_state(db, seeded["store_id"], days=7)
    facts = facts_from_store_state(state)
    assert "profit" in facts or "take_home_rate" in facts
    assert "recent_bad_review_count" in facts or "reviews" in facts


def test_appeal_pack_demand_opens_appeal_loop() -> None:
    db = _session()
    seeded = seed_demo(db)
    demand = by_code("APPEAL_PACK")
    verdict = run_playbook(
        demand,
        {"recent_bad_review_count": 1, "bad_review_rate": 0.08},
    )
    loop = open_demand_loop(db, seeded["store_id"], verdict)
    assert loop is not None
    # action_type may be "appeal_pack" or "ops_hint" depending on verdict.blocked state
    assert loop.action_type in ("appeal_pack", "ops_hint")
    pack = loop.pack_json or ""
    assert "申诉" in pack or "appeal" in pack.lower()
