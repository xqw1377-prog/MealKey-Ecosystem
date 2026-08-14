from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.commercial import AIWallet, CommissionLedger, Partner, StoreLicense
from app.models.entities import Merchant, Store
from app.services.commercial import customer_bill
from app.services.commercial.board import merchant_board, subscribe_cycle, topup_wallet, wallet_alert
from app.services.commercial.ai_ledger import (
    acquisition_over_cap,
    budget_state,
    charge_ai,
    plan_token_cost_cny,
)
from app.services.commercial.model_router import high_value_continues, route_model
from app.services.commercial.north_star import company_north_star
from app.services.commercial.partner import (
    CommissionDenied,
    assert_direct_only,
    assert_not_self_deal,
    four_year_economics,
    is_90_day_qualified,
    is_bonus_confirmed,
    is_new_qualified,
    requires_service_qualification,
    split_commission,
    true_up_amount,
    true_up_y1_rate,
)
from app.services.commercial.policy import SUBSCRIPTION_FLOOR_CNY, policy_snapshot, y1_partner_rate
from app.services.commercial.pricing import quote_subscription


def test_volume_and_annual_quote() -> None:
    one = quote_subscription(1, "monthly")
    assert one.unit_monthly_cny == 300
    assert one.billed_cny == 300
    assert one.needs_approval is False
    year = quote_subscription(1, "annual")
    assert year.unit_annual_cny == 3000
    assert year.equiv_monthly_cny == 250
    assert year.billed_cny == 3000
    chain = quote_subscription(100, "monthly")
    assert chain.unit_monthly_cny == 260
    huge = quote_subscription(300, "annual")
    assert huge.unit_annual_cny == 2500
    assert huge.equiv_monthly_cny > SUBSCRIPTION_FLOOR_CNY


def test_quarterly_quote_and_floor() -> None:
    quarter = quote_subscription(1, "quarterly")
    assert quarter.billing_cycle == "quarterly"
    assert quarter.unit_quarterly_cny == 825
    assert quarter.billed_cny == 825
    assert quarter.equiv_monthly_cny == 275
    assert quarter.paid_months == 2.75
    assert quarter.used_months == 3
    chain = quote_subscription(300, "quarterly")
    assert chain.equiv_monthly_cny >= SUBSCRIPTION_FLOOR_CNY
    assert quote_subscription(1, "q").billing_cycle == "quarterly"


def test_floor_requires_approval() -> None:
    quote = quote_subscription(1, "monthly")
    assert quote.equiv_monthly_cny >= SUBSCRIPTION_FLOOR_CNY
    # 政策红线：任何组合不得把等效月价做到 200 以下还不审批
    assert quote_subscription(300, "annual").equiv_monthly_cny >= 200


def test_customer_bill_is_subscription_plus_ai() -> None:
    bill = customer_bill(active_stores=1, billing_cycle="monthly")
    assert bill["subscription"]["billed_cny"] == 300
    assert 100 <= bill["ai"]["billed_cny"] <= 120
    assert abs(bill["total_cny"] - (300 + bill["ai"]["billed_cny"])) < 0.01
    assert "token" in bill["customer_does_not_see"]
    quarter = customer_bill(active_stores=1, billing_cycle="quarterly")
    assert quarter["period"] == "quarter"
    assert quarter["subscription"]["billed_cny"] == 825
    assert abs(quarter["ai"]["billed_cny"] - bill["ai"]["billed_cny"] * 3) < 0.05


def test_ai_markup_and_budget() -> None:
    charge = charge_ai(83)
    assert charge.billed_cny == 107.9
    planned = plan_token_cost_cny(4_500_000)
    assert 80 <= planned["actual_cost_cny"] <= 86
    assert 104 <= planned["billed_cny"] <= 112
    assert budget_state(100, 1).state == "normal"
    assert budget_state(120, 1).state == "throttle"
    assert budget_state(150, 1).state == "cap_noncritical"
    assert budget_state(150, 1).continue_high_value is True
    pooled = budget_state(8000, 100)
    assert pooled.budget_actual_cny == 15000
    assert pooled.state == "normal"
    assert acquisition_over_cap(5.0) is False
    assert acquisition_over_cap(5.01) is True


def test_model_router_escalates_by_value() -> None:
    assert route_model("profit_formula") == "code"
    assert route_model("ordinary_reply") == "luna"
    assert route_model("operating_diagnosis") == "terra"
    assert route_model("complex_attribution") == "sol"
    assert route_model("free_audit_diagnose", lane="acquisition") == "terra"
    assert route_model("complex_attribution", budget_state="throttle") == "terra"
    assert high_value_continues("high_value_anomaly", "cap_noncritical") is True
    assert high_value_continues("summarize", "cap_noncritical") is False


def test_partner_y1_tiers_and_true_up() -> None:
    assert y1_partner_rate(1) == 0.50
    assert y1_partner_rate(20) == 0.55
    assert y1_partner_rate(50) == 0.60
    assert y1_partner_rate(100) == 0.65
    assert y1_partner_rate(300) == 0.70
    old, new, jumped = true_up_y1_rate(99, 100)
    assert old == 0.60
    assert new == 0.65
    assert jumped is True
    assert true_up_amount(subscription_base_cny=3000, from_rate=0.65, to_rate=0.70) == 150
    assert requires_service_qualification(0.60) is False
    assert requires_service_qualification(0.65) is True


def test_commission_excludes_ai_and_owned_stores() -> None:
    split = split_commission(
        collected_cny=3000,
        new_qualified_stores=300,
        ninety_day_qualified_stores=300,
        months_since_first_paid=0,
    )
    assert split.lifecycle_rate == 0.70
    assert split.partner_cny == 2100
    assert split.mealkey_cny == 900
    assert split.payable_now_cny == 1500
    assert split.performance_accrual_cny == 600
    try:
        split_commission(
            collected_cny=3000,
            new_qualified_stores=1,
            months_since_first_paid=0,
            include_ai_cny=108,
        )
        raise AssertionError("AI must never enter commission base")
    except CommissionDenied:
        pass
    try:
        assert_not_self_deal(license_kind="owned", owner_partner_id=None, earning_partner_id="p1")
        raise AssertionError("owned stores must not commission")
    except CommissionDenied:
        pass
    try:
        assert_direct_only(upline_partner_id="upline")
        raise AssertionError("multi-level must be denied")
    except CommissionDenied:
        pass


def test_lifecycle_and_four_year_retention_math() -> None:
    y2 = split_commission(collected_cny=3000, new_qualified_stores=300, months_since_first_paid=13)
    assert y2.lifecycle_rate == 0.30
    assert y2.partner_cny == 900
    y4 = split_commission(collected_cny=3000, new_qualified_stores=300, months_since_first_paid=40)
    assert y4.lifecycle_rate == 0.10
    econ = four_year_economics(3000, 0.70)
    assert econ["partner_total_cny"] == 3900
    assert econ["mealkey_total_cny"] == 8100
    assert econ["mealkey_share"] == 0.675


def test_qualified_store_windows() -> None:
    assert is_new_qualified(paid=True, refunded=False, activated=True, days_active=29) is False
    assert is_new_qualified(paid=True, refunded=False, activated=True, days_active=30) is True
    assert is_bonus_confirmed(paid=True, refunded=False, activated=True, days_active=89) is False
    assert is_bonus_confirmed(paid=True, refunded=False, activated=True, days_active=90) is True
    assert is_90_day_qualified(paid=True, refunded=False, activated=True, days_active=90) is True
    assert is_new_qualified(paid=True, refunded=True, activated=True, days_active=90) is False


def test_ninety_day_store_unlocks_partner_bonus() -> None:
    churned = split_commission(
        collected_cny=3000,
        new_qualified_stores=300,
        ninety_day_qualified_stores=0,
        months_since_first_paid=0,
    )
    assert churned.potential_y1_rate == 0.70
    assert churned.y1_rate == 0.50
    assert churned.payable_now_cny == 1500
    assert churned.performance_accrual_cny == 0
    kept = split_commission(
        collected_cny=3000,
        new_qualified_stores=300,
        ninety_day_qualified_stores=20,
        months_since_first_paid=0,
    )
    assert kept.y1_rate == 0.55
    assert kept.payable_now_cny == 1500
    assert kept.performance_accrual_cny == 150


def test_strategy_freeze_rejects_white_label_and_profit_share() -> None:
    snap = policy_snapshot()
    assert snap["version"] == "commercial-os-v1.2"
    assert snap["competitive_strategy_version"] == "competitive-strategy-v1"
    assert snap["profit_share_v1"] is False
    assert snap["white_label_primary"] is False
    assert snap["strategic_seat"] == "merchant_operating_control_plane"
    assert snap["competitive_one_liner"].startswith("平台是执行场")
    assert snap["company_goal"]["paid_stores"] == 20
    assert snap["company_goal"]["verified_closed_loops"] == 100
    assert snap["company_goal"]["memory_changed_decisions"] == 10
    assert snap["company_goal"]["natural_renewals"] == 1
    assert len(snap["sla"]) == 5
    assert len(snap["freeze_sentences"]) == 6
    assert len(snap["battlefields"]) == 5
    assert "verified_closed_loops_100" in snap["not_a_moat"]
    assert "platform_will_only_suggest" in snap["not_a_moat"]
    assert "change_title" in snap["min_closed_loop_actions"]


def test_company_north_star_counts_paid_and_verified() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    merchant = Merchant(name="付费试点")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="试点店")
    db.add(store)
    db.flush()
    db.add(
        StoreLicense(
            merchant_id=merchant.id,
            store_id=store.id,
            kind="owned",
            status="paid",
        )
    )
    from app.models.closed_loop import ClosedLoopItem

    db.add(
        ClosedLoopItem(
            store_id=store.id,
            fingerprint="loop-1",
            title="改标题",
            status="closed",
            result="positive",
        )
    )
    db.add(
        ClosedLoopItem(
            store_id=store.id,
            fingerprint="loop-2",
            title="还在猜",
            status="result_ready",
            result="unknown",
        )
    )
    db.commit()
    star = company_north_star(db)
    assert star["paid_stores"] == 1
    assert star["verified_closed_loops"] == 1
    assert star["paid_stores_remaining"] == 19
    assert star["memory_changed_decisions"] == 0
    assert star["natural_renewals"] == 0
    assert star["ai_cost_per_store"]["status"] == "unmeasured"
    assert star["commercial_traction"] == "in_progress"
    assert star["phase"] == "production_evidence"
    assert len(star["evidence"]) == 4


def test_ledgers_are_separate_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    merchant = Merchant(name="自有品牌")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="自有店")
    db.add(store)
    db.flush()
    partner = Partner(display_name="张合伙人", merchant_id=merchant.id)
    db.add(partner)
    db.flush()
    db.add(
        StoreLicense(
            merchant_id=merchant.id,
            store_id=store.id,
            kind="owned",
            partner_id=None,
            status="paid",
        )
    )
    db.commit()
    try:
        assert_not_self_deal(license_kind="owned", owner_partner_id=partner.id, earning_partner_id=partner.id)
        raise AssertionError("owned license must not commission")
    except CommissionDenied:
        pass
    db.add(
        CommissionLedger(
            partner_id=partner.id,
            store_id=store.id,
            period_month="2027-01",
            kind="base",
            subscription_base_cny=3000,
            rate=0.5,
            amount_cny=1500,
        )
    )
    db.commit()
    row = db.query(CommissionLedger).one()
    assert row.subscription_base_cny == 3000
    assert "ai" not in (row.kind or "")


def test_avatar_board_subscribe_and_wallet() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    merchant = Merchant(name="头像账单店")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="样板店")
    db.add(store)
    db.commit()
    board = merchant_board(db, store)
    assert board["quotes"]["monthly"]["billed_cny"] == 300
    assert board["quotes"]["quarterly"]["billed_cny"] == 825
    assert board["quotes"]["annual"]["billed_cny"] == 3000
    assert board["promise"]["sells"] == "持续经营责任"
    assert len(board["promise"]["sla"]) == 5
    assert board["wallet"]["balance_cny"] == 0
    assert board["wallet"]["alert"]["status"] == "empty"
    assert board["wallet"]["alert"]["show_home_banner"] is False
    paid = subscribe_cycle(db, store, "annual")
    db.commit()
    assert paid["current"]["billing_cycle"] == "annual"
    assert paid["current"]["status"] == "paid"
    topped = topup_wallet(db, store, 500)
    db.commit()
    assert topped["wallet"]["balance_cny"] == 500
    assert topped["wallet"]["alert"]["status"] == "ok"
    wallet = db.query(AIWallet).one()
    assert wallet.balance_cny == 500
    try:
        topup_wallet(db, store, 123)
        raise AssertionError("non-tier topup must fail")
    except ValueError:
        pass


def test_wallet_alert_needs_purchase_link() -> None:
    idle = wallet_alert(balance_cny=0, month_used_cny=0, ever_topped_up=False)
    assert idle["status"] == "empty"
    assert idle["show_home_banner"] is False
    spent = wallet_alert(balance_cny=0, month_used_cny=18, ever_topped_up=True)
    assert spent["show_home_banner"] is True
    assert spent["purchase_path"] == "avatar_wallet"
    assert "充值" in spent["cta"]
    low = wallet_alert(balance_cny=20, month_used_cny=80, ever_topped_up=True)
    assert low["status"] == "low"
    assert low["show_home_banner"] is True
