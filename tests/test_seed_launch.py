"""上线前 6 块：开店数据通道、人工闭环、每日 SLA、利润诚实、生产底座、手工收款。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.models.closed_loop import ClosedLoopItem
from app.models.entities import MenuItem, Merchant, Store
from app.services.closed_loop import ensure_now_loop, execute_loop_platform_writeback, project_loop
from app.services.commercial.board import (
    activate_by_bank_transfer,
    request_manual_payment,
    review_manual_payment,
    subscribe_cycle,
    topup_wallet,
)
from app.services.execution_pack import build_execution_pack
from app.services.operating_demands.catalog import by_code
from app.services.operating_demands.playbooks import run_playbook
from app.services.platform_connectors import reset_mock_platform_state
from app.services.seed_launch import (
    daily_sla_digest,
    onboarding_playbook,
    production_readiness,
    profit_honesty,
    seed_launch_status,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session) -> Store:
    merchant = Merchant(name="种子商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="老王牛肉饭")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def _title_flow() -> dict:
    pack = build_execution_pack("change_title", object_name="招牌牛肉盖饭", title="改招牌牛肉盖饭标题")
    return {
        "now": {
            "id": "nba-title-seed",
            "source_card_id": "nba-title-seed",
            "title": "改招牌牛肉盖饭标题",
            "why_now": "标题信息弱",
            "ai_already_did": "已经写好一版强调份量的标题",
            "execution_pack": pack,
        }
    }


def test_onboarding_playbook_lists_five_steps_and_cost_not_ready() -> None:
    db = _session()
    store = _store(db)
    play = onboarding_playbook(db, store.id)
    assert play["total"] == 5
    assert play["ready_count"] == 0
    assert play["complete"] is False
    assert [step["key"] for step in play["steps"]] == ["orders", "funnel", "reviews", "ads", "cost"]
    assert all(not step["ready"] for step in play["steps"])
    assert play["next"]["key"] == "orders"
    cost_step = next(step for step in play["steps"] if step["key"] == "cost")
    assert cost_step["ready"] is False
    assert "成本" in cost_step["how"]
    honesty = play["profit"]
    assert honesty["precise_profit"] is False
    assert honesty["join_campaign_allowed"] is False
    assert honesty["budget_up_allowed"] is False


def test_profit_honesty_ready_with_enough_item_costs() -> None:
    db = _session()
    store = _store(db)
    for _ in range(3):
        db.add(MenuItem(store_id=store.id, is_active=True, food_cost=8.5))
    db.commit()
    honesty = profit_honesty(db, store.id)
    assert honesty["cost_ready"] is True
    assert honesty["precise_profit"] is True
    assert honesty["items_with_cost"] == 3


def test_store_loss_without_cost_does_not_claim_precise_profit() -> None:
    verdict = run_playbook(by_code("STORE_LOSS"), {"cost_ready": False, "profit": -18.0})
    assert verdict.blocked is True
    assert "精确利润" in verdict.diagnosis or "亏多少" in verdict.diagnosis
    assert "成本" in verdict.action


def test_join_campaign_blocked_without_cost() -> None:
    verdict = run_playbook(
        by_code("JOIN_CAMPAIGN"),
        {"cost_ready": False, "official_promos": [{"title": "午市满减"}]},
    )
    assert verdict.blocked is True
    assert "报名" in verdict.diagnosis or "成本" in verdict.diagnosis
    assert any("无账" in item for item in verdict.why_not)


def test_budget_up_blocked_without_cost() -> None:
    verdict = run_playbook(by_code("BUDGET_UP_DOWN"), {"cost_ready": False, "ads_roi": 2.4})
    assert verdict.blocked is True
    assert "加预算" in verdict.diagnosis
    assert any("加预算" in item for item in verdict.why_not)


def test_join_campaign_without_cost_flag_still_uses_existing_playbook() -> None:
    verdict = run_playbook(by_code("JOIN_CAMPAIGN"), {"official_promos": [{"title": "午市满减"}]})
    assert "午市满减" in verdict.diagnosis
    assert verdict.blocked is False


def test_human_paste_does_not_claim_platform_write(monkeypatch) -> None:
    reset_mock_platform_state()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "platform_connector_url", "")
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_title_flow(), events=None)
    assert item is not None
    projected = project_loop(item)
    assert projected["writeback_mode"] == "human_paste"
    assert projected["platform_writeable"] is False

    marked = execute_loop_platform_writeback(db, store.id, item.id)
    assert marked.status == "now"
    assert marked.executed_at is None
    pack = json.loads(marked.pack_json or "{}")
    writeback = pack.get("writeback") or {}
    assert writeback.get("mode") == "human_paste"
    assert writeback.get("platform_changed") is False
    assert "还没写到平台" in str(writeback.get("summary") or "")
    assert "已把" not in str(writeback.get("summary") or "")


def test_mock_writeback_still_works_in_dev() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_title_flow(), events=None)
    assert item is not None
    marked = execute_loop_platform_writeback(db, store.id, item.id)
    assert marked.status == "observing"
    assert marked.executor == "PLATFORM"
    pack = json.loads(marked.pack_json or "{}")
    assert pack.get("writeback", {}).get("mode") == "mock"
    assert pack.get("writeback", {}).get("platform_changed") is True


def test_daily_sla_digest_has_three_blocks() -> None:
    db = _session()
    store = _store(db)
    db.add(
        ClosedLoopItem(
            store_id=store.id,
            fingerprint="pending-1",
            title="改招牌标题",
            status="now",
            action_type="change_title",
        )
    )
    db.add(
        ClosedLoopItem(
            store_id=store.id,
            fingerprint="due-1",
            title="回看换主图",
            status="observing",
            action_type="change_main_image",
            observe_until=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )
    db.commit()
    digest = daily_sla_digest(db, store.id)
    assert digest["pending_count"] == 1
    assert digest["due_count"] == 1
    assert digest["pending_confirm"][0]["title"] == "改招牌标题"
    assert digest["due_observe"][0]["title"] == "回看换主图"
    assert "今天三件事" in digest["push_text"]
    assert "成本" in digest["morning_judgment"]


def test_production_subscribe_rejects_demo_direct(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    db = _session()
    store = _store(db)
    try:
        subscribe_cycle(db, store, "monthly")
        raise AssertionError("production must not demo-credit subscription")
    except ValueError as exc:
        assert "演示入账" in str(exc) or "手工开通" in str(exc)


def test_bank_transfer_activates_subscription_and_wallet(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    db = _session()
    store = _store(db)
    paid = activate_by_bank_transfer(
        db,
        store,
        kind="subscription",
        billing_cycle="monthly",
        operator="ops",
        transfer_note="老王牛肉饭",
    )
    db.commit()
    assert paid["current"]["status"] == "paid"
    assert paid["current"]["billed_cny"] == 300
    wallet = activate_by_bank_transfer(
        db,
        store,
        kind="wallet",
        amount_cny=500,
        operator="ops",
        transfer_note="老王牛肉饭-算力",
    )
    db.commit()
    assert wallet["wallet"]["balance_cny"] == 500


def test_bank_transfer_requires_note() -> None:
    db = _session()
    store = _store(db)
    try:
        activate_by_bank_transfer(db, store, transfer_note="  ")
        raise AssertionError("empty transfer note must fail")
    except ValueError:
        pass


def test_manual_payment_request_can_be_reviewed_and_activate_store() -> None:
    db = _session()
    store = _store(db)
    request = request_manual_payment(
        db,
        store,
        kind="subscription",
        billing_cycle="monthly",
        transfer_note="老王牛肉饭-8月首单",
        payer_name="老王",
    )
    db.commit()
    assert request.status == "pending"

    approved = review_manual_payment(
        db,
        request.id,
        approved=True,
        operator="ops_a",
        review_note="凭证已核对",
    )
    db.commit()
    assert approved["status"] == "approved"
    assert approved["board"]["current"]["status"] == "paid"


def test_production_readiness_flags_sqlite_in_prod(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "database_url", "sqlite:///./mealky.db")
    monkeypatch.setattr(settings, "api_token", "")
    monkeypatch.setattr(settings, "jwt_secret", "")
    payload = production_readiness()
    assert payload["ready"] is False
    ids = {item["id"]: item["ok"] for item in payload["checks"]}
    assert ids["not_sqlite_in_prod"] is False
    assert ids["backup_script"] is True
    assert ids["tenant_scope"] is True
    assert ids["no_create_all_in_prod"] is True
    assert ids["secrets_not_in_repo"] is True


def test_seed_launch_status_is_one_board_not_six_buttons() -> None:
    db = _session()
    store = _store(db)
    board = seed_launch_status(db, store.id)
    assert set(board) >= {"onboarding", "profit", "writeback", "daily_sla", "billing"}
    assert board["onboarding"]["total"] == 5
    assert board["profit"]["precise_profit"] is False
    assert board["billing"]["amount_monthly_cny"] == 300
    assert "微信自动扣费" in board["billing"]["instructions_text"]


def test_production_topup_rejects_demo_direct(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    db = _session()
    store = _store(db)
    try:
        topup_wallet(db, store, 500)
        raise AssertionError("production must not demo-credit wallet")
    except ValueError as exc:
        assert "演示入账" in str(exc) or "手工开通" in str(exc)
