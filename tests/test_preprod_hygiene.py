"""PRE-PROD HYGIENE GATE — Production Invariants V1."""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, ShopFunnelDaily, Store
from app.models.ohre import Experiment, Recommendation
from app.services.action_capability import (
    BLOCKED_NOT_IMPLEMENTED,
    ActionCapabilityError,
    assert_action_executable,
    execution_capability,
)
from app.services.action_ranker import apply_memory_to_growth_pool, memory_from_result
from app.services.credential_store import get_oauth_secret, public_platform_link
from app.services.data_acquisition_loop import declining_series, run_connected_discovery
from app.services.experiment_attribution import FAILED_VERIFICATION, _loads_dict, evaluate_experiment
from app.services.platform_connectors import PlatformDailyMetric, PlatformSnapshot
from app.services.platform_oauth import persist_oauth_connection
from app.services.platform_sync import apply_platform_snapshot
from app.services.store_state import build_store_state
from app.services.truth_resolution import may_write_funnel_truth


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session) -> Store:
    merchant = Merchant(name="卫生门禁商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="卫生门禁店", city="北京", platform="meituan")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def test_oauth_tokens_never_enter_meta_or_public_link() -> None:
    db = _session()
    store = _store(db)
    row = persist_oauth_connection(
        db,
        store_id=store.id,
        platform="meituan",
        token_payload={
            "access_token": "real-looking-token",
            "refresh_token": "real-looking-refresh",
            "scope": "order_manage menu_manage",
            "expires_in": 3600,
        },
    )
    db.commit()
    meta = json.loads(row.meta_json or "{}")
    dumped = json.dumps(meta)
    assert "real-looking-token" not in dumped
    assert "access_token" not in meta.get("oauth", {})
    assert get_oauth_secret(db, store.id, "meituan")["access_token"] == "real-looking-token"
    public = public_platform_link(row, db=db)
    assert "access_token" not in json.dumps(public)
    assert public["connected"] is True
    assert "order_manage" in public["scopes"]


def test_legacy_plaintext_token_is_migrated_and_flagged() -> None:
    db = _session()
    store = _store(db)
    from app.models.settings import PlatformConnection

    row = PlatformConnection(
        store_id=store.id,
        platform="eleme",
        status="connected",
        connector_mode="oauth",
        meta_json=json.dumps({"oauth": {"access_token": "legacy-at", "refresh_token": "legacy-rt", "scope": "order"}}),
    )
    db.add(row)
    db.commit()
    public = public_platform_link(row, db=db)
    db.commit()
    assert public["rotate_recommended"] is True
    assert "legacy-at" not in (row.meta_json or "")
    assert get_oauth_secret(db, store.id, "eleme")["access_token"] == "legacy-at"


def test_real_discover_without_facts_is_no_signal() -> None:
    db = _session()
    store = _store(db)
    body = run_connected_discovery(db, store_id=store.id, mode="REAL")
    assert body["status"] == "NO_SIGNAL"
    assert body["events"] == []
    assert body["reached_candidate_action"] is False


def test_fixture_discover_never_becomes_production_truth() -> None:
    db = _session()
    store = _store(db)
    body = run_connected_discovery(db, store_id=store.id, mode="FIXTURE")
    assert body["production_truth"] is False
    assert body["source"] == "synthetic"
    state = build_store_state(db, store.id, days=7)
    assert state is not None
    assert (state.kpis["orders"].confidence or 0) == 0
    assert state.kpis["orders"].delta_pct is None


def test_mock_funnel_cannot_overwrite_authorized_session() -> None:
    db = _session()
    store = _store(db)
    day = date.today() - timedelta(days=1)
    db.add(
        ShopFunnelDaily(
            store_id=store.id,
            day=day,
            orders=40,
            gmv=1600,
            data_source="authorized_session",
        )
    )
    db.commit()
    assert may_write_funnel_truth("authorized_session", "synthetic") is False
    apply_platform_snapshot(
        db,
        store,
        PlatformSnapshot(
            platform="meituan",
            external_store_id="mock-1",
            store_name=store.name,
            daily_metrics=[PlatformDailyMetric(day=day, orders=1, gmv=1.0)],
            synthetic=True,
        ),
    )
    db.commit()
    row = db.get(ShopFunnelDaily, (store.id, day))
    assert row is not None
    assert row.orders == 40
    assert row.data_source == "authorized_session"


def test_not_implemented_is_central_hard_gate() -> None:
    assert execution_capability("issue_repurchase_coupon") == "NOT_IMPLEMENTED"
    assert execution_capability("reactivate_dormant_customer") == "NOT_IMPLEMENTED"
    assert execution_capability("referral_share") == "NOT_IMPLEMENTED"
    try:
        assert_action_executable("issue_repurchase_coupon")
        raise AssertionError("must block")
    except ActionCapabilityError as exc:
        assert exc.code == BLOCKED_NOT_IMPLEMENTED
    assert_action_executable("change_title")


def test_observed_growth_memory_cannot_boost_production_ranking() -> None:
    class Row:
        def __init__(self, action_type: str, score: float):
            self.action_type = action_type
            self.score = score

        def model_copy(self, update):
            return Row(self.action_type, update["score"])

    pool = [
        Row("issue_repurchase_coupon", 51.0),
        Row("adjust_price_value", 58.0),
        Row("change_main_image", 62.0),
    ]
    memory = memory_from_result(
        action_type="adjust_price_value",
        result="positive",
        lift_pct=18.0,
        metric="orders",
    )
    after = apply_memory_to_growth_pool(pool, memory)
    scores = {row.action_type: row.score for row in after}
    assert scores["adjust_price_value"] == 58.0
    assert scores["issue_repurchase_coupon"] == 51.0


def test_loads_dict_and_failed_verification_are_explicit(monkeypatch) -> None:
    assert _loads_dict(None) == {}
    assert _loads_dict("{") == {}
    assert _loads_dict('{"a": 1}') == {"a": 1}

    db = _session()
    store = _store(db)
    rec = Recommendation(
        store_id=store.id,
        scope="store",
        object_ref=f"store:{store.id}",
        action_type="change_title",
        expected_metric="orders",
        status="executed",
        content_json="{}",
    )
    db.add(rec)
    db.flush()
    exp = Experiment(store_id=store.id, recommendation_id=rec.id, result="pending")
    db.add(exp)
    db.commit()

    def boom(_raw):
        raise RuntimeError("writeback exploded")

    monkeypatch.setattr("app.services.experiment_attribution._loads_dict", boom)
    outcome = evaluate_experiment(db, exp, days=7)
    assert outcome.reason == FAILED_VERIFICATION
    assert outcome.result == "unknown"
    assert exp.result == "unknown"
    assert FAILED_VERIFICATION in (exp.notes or "")


def test_empty_data_source_is_never_production_truth() -> None:
    from app.services.truth_resolution import (
        LEGACY_UNKNOWN_SOURCE,
        confidence_for_sources,
        is_production_truth_source,
        normalize_source,
    )

    assert normalize_source(None) == LEGACY_UNKNOWN_SOURCE
    assert normalize_source("") == LEGACY_UNKNOWN_SOURCE
    assert normalize_source("  ") == LEGACY_UNKNOWN_SOURCE
    assert is_production_truth_source(None) is False
    assert is_production_truth_source("") is False
    assert confidence_for_sources([None, "", "legacy_unknown_source"]) == 0.0

    db = _session()
    store = _store(db)
    day = date.today() - timedelta(days=1)
    db.add(
        ShopFunnelDaily(
            store_id=store.id,
            day=day,
            orders=99,
            gmv=9900,
            data_source="",
        )
    )
    db.commit()
    state = build_store_state(db, store.id, days=7)
    assert state is not None
    assert (state.kpis["orders"].confidence or 0) == 0
    assert (state.kpis["orders"].observed_value or 0) != 99


def test_recommendation_execute_is_pipeline_choke_point() -> None:
    from fastapi.testclient import TestClient

    from app.db.session import SessionLocal
    from app.main import app
    from app.services.action_pipeline import (
        NEED_APPROVAL,
        PIPELINE_COMMIT_BY,
        ActionPipelineError,
        run_recommendation_pipeline,
    )

    client = TestClient(app)
    seed = client.post("/dev/seed")
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]

    with SessionLocal() as db:
        blocked = Recommendation(
            store_id=store_id,
            scope="store",
            object_ref=f"store:{store_id}",
            action_type="issue_repurchase_coupon",
            expected_metric="orders",
            status="proposed",
            content_json="{}",
        )
        db.add(blocked)
        db.commit()
        blocked_id = blocked.id

    denied = client.post(f"/workspace/recommendations/{blocked_id}/execute")
    assert denied.status_code == 409
    detail = denied.json()["detail"]
    assert detail["code"] == BLOCKED_NOT_IMPLEMENTED
    with SessionLocal() as db:
        still = db.get(Recommendation, blocked_id)
        assert still is not None
        assert still.status != "executed"
    no_effect = client.post(f"/workspace/recommendations/{blocked_id}/no_effect")
    assert no_effect.status_code == 409

    db = _session()
    store = _store(db)
    ready = Recommendation(
        store_id=store.id,
        scope="store",
        object_ref=f"store:{store.id}",
        action_type="change_title",
        expected_metric="ctr",
        status="adopted",
        content_json=json.dumps({"executed_in_system": True}),
    )
    db.add(ready)
    db.flush()
    try:
        run_recommendation_pipeline(db, ready, actor="test", approved=False)
        raise AssertionError("approval gate must hold")
    except ActionPipelineError as exc:
        assert exc.code == NEED_APPROVAL
        assert ready.status != "executed"
    committed = run_recommendation_pipeline(db, ready, actor="test", approved=True)
    assert committed["executed"] is True
    assert committed["stages"][-1] == "COMMIT"
    assert ready.status == "executed"
    stamp = json.loads(ready.content_json or "{}").get("execution_commit") or {}
    assert stamp.get("by") == PIPELINE_COMMIT_BY


def test_production_never_falls_back_to_mock(monkeypatch) -> None:
    from app.core.config import settings
    from app.services.connector_mode import (
        AUTH_REQUIRED,
        CONFIGURATION_ERROR,
        PLATFORM_UNAVAILABLE,
        ConnectorModeError,
        assert_mode_allowed,
    )
    from app.services.platform_connectors import fetch_platform_snapshot

    monkeypatch.setattr(settings, "app_env", "production")
    try:
        assert_mode_allowed("mock", explicit=True)
        raise AssertionError("prod must forbid mock")
    except ConnectorModeError as exc:
        assert exc.code == CONFIGURATION_ERROR

    try:
        fetch_platform_snapshot("meituan", store_id="s1", mode="human_paste")
        raise AssertionError("human_paste must not fall through to mock")
    except ConnectorModeError as exc:
        assert exc.code == PLATFORM_UNAVAILABLE

    def boom(*_args, **_kwargs):
        raise ValueError("401 unauthorized token expired")

    monkeypatch.setattr("app.services.platform_connectors.fetch_http_snapshot", boom)
    try:
        fetch_platform_snapshot("meituan", store_id="s1", mode="http")
        raise AssertionError("real connector failure must fail closed")
    except ConnectorModeError as exc:
        assert exc.code == AUTH_REQUIRED


def test_only_pipeline_can_create_executed_semantics() -> None:
    from pathlib import Path

    from app.services.action_pipeline import ActionPipelineError, commit_recommendation_executed

    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for path in app_root.rglob("*.py"):
        if path.name == "action_pipeline.py":
            continue
        text = path.read_text(encoding="utf-8")
        if 'rec.status = "executed"' in text or "rec.status = 'executed'" in text:
            offenders.append(str(path.relative_to(app_root.parent)))
    assert offenders == []

    rec = Recommendation(
        store_id="store-choke",
        scope="store",
        object_ref="store:store-choke",
        action_type="change_title",
        expected_metric="orders",
        status="adopted",
        content_json="{}",
    )
    try:
        rec.status = "executed"
        raise AssertionError("direct assignment must be forbidden")
    except RuntimeError as exc:
        assert "choke point" in str(exc)
    try:
        commit_recommendation_executed(rec, actor="test", verified=False)
        raise AssertionError("unverified commit must be refused")
    except ActionPipelineError as exc:
        assert exc.code == "VERIFY_REQUIRED"
        assert rec.status != "executed"
    commit_recommendation_executed(rec, actor="test", verified=True)
    assert rec.status == "executed"


def test_unprovenanced_funnel_is_query_invisible_not_just_low_confidence() -> None:
    from app.services.diagnosis_analysis import _aggregate_shop
    from app.services.ops_diagnosis import _recent_funnel

    db = _session()
    store = _store(db)
    day = date.today() - timedelta(days=1)
    db.add(
        ShopFunnelDaily(
            store_id=store.id,
            day=day,
            orders=77,
            gmv=7700,
            data_source=None,
        )
    )
    db.commit()
    assert _recent_funnel(db, store.id) == []
    assert _aggregate_shop(db, store.id, day, day) is None
    state = build_store_state(db, store.id, days=7)
    assert state is not None
    assert (state.kpis["orders"].observed_value or 0) != 77
