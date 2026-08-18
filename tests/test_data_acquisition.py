from datetime import datetime, timedelta, timezone

from app.schemas.data_acquisition import ACQUISITION_LADDER, FactEnvelope
from app.services.authorized_session_connector import AuthorizedSessionConnector, PlatformConnector
from app.services.data_acquisition_pipeline import (
    build_collector_run,
    can_enter_high_confidence_storestate,
    classify_poc_review,
    filter_payload,
    promote_envelope,
    reconcile_row,
    unknown_minimal_fields,
)
from app.schemas.data_acquisition import FetchRequest


def _envelope(**kwargs) -> FactEnvelope:
    now = datetime.now(timezone.utc)
    base = dict(
        platform="meituan",
        store_id="s1",
        fact_type="daily_gmv",
        fact_key="gross_amount",
        occurred_at=now,
        value=100.0,
        unit="CNY",
        acquisition_mode="AUTHORIZED_SESSION",
        source_connector="authorized_session",
        collected_at=now,
    )
    base.update(kwargs)
    return FactEnvelope(**base)


def test_frozen_ladder_keeps_session_after_apis() -> None:
    assert ACQUISITION_LADDER[:3] == (
        "OFFICIAL_API",
        "SERVICE_PROVIDER_API",
        "AUTHORIZED_SESSION",
    )


def test_unwired_connector_stays_unavailable() -> None:
    connector = AuthorizedSessionConnector()
    assert isinstance(connector, PlatformConnector)
    result = connector.fetch(FetchRequest(store_id="s1", platform="meituan"))
    assert result.health.status == "UNAVAILABLE"
    assert result.envelopes == []


def test_pii_and_unknown_keys_are_rejected() -> None:
    kept, rejected = filter_payload(
        {
            "gross_amount": 88,
            "customer_name": "张三",
            "phone": "13800000000",
            "mystery_field": 1,
        }
    )
    assert kept == {"gross_amount": 88}
    assert rejected == 3


def test_unreconciled_or_unhealthy_never_promotes() -> None:
    raw = _envelope()
    unchecked = promote_envelope(raw, health="HEALTHY", recon="UNCHECKED")
    assert unchecked.confidence == 0.0
    assert not can_enter_high_confidence_storestate(unchecked)

    blocked = promote_envelope(raw, health="SCHEMA_CHANGED", recon="MATCHED")
    assert blocked.reconciliation_status == "BLOCKED"
    assert blocked.confidence == 0.0

    matched = promote_envelope(raw, health="HEALTHY", recon="MATCHED")
    assert matched.confidence == 0.70
    assert can_enter_high_confidence_storestate(matched)
    official = promote_envelope(
        _envelope(acquisition_mode="OFFICIAL_API"),
        health="HEALTHY",
        recon="MATCHED",
    )
    assert official.confidence == 0.95
    assert official.confidence > matched.confidence


def test_close_amount_without_reason_is_mismatch() -> None:
    row = reconcile_row(
        day="2026-08-17",
        metric="gmv",
        collector_value=100.0,
        official_value=108.0,
    )
    assert row.status == "MISMATCH"


def test_missing_merchant_revenue_stays_unknown() -> None:
    assert "merchant_revenue" in unknown_minimal_fields(["order_count", "gross_gmv", "refund_amount"])


def test_poc_verdicts() -> None:
    start = datetime.now(timezone.utc)
    healthy_runs = []
    for i in range(7):
        healthy_runs.append(
            build_collector_run(
                platform="meituan",
                store_id="s1",
                run_id=f"r{i}",
                started_at=start + timedelta(days=i),
                health_status="HEALTHY",
                envelopes=[_envelope()],
                rejected=0,
                unknown_fields=["merchant_revenue"],
                rows=[
                    reconcile_row(
                        day="2026-08-17",
                        metric="orders",
                        collector_value=10,
                        official_value=10,
                    )
                ],
                auth_status="authorized",
            )
        )
    limited = classify_poc_review(healthy_runs, reached_candidate_action=True)
    assert limited.verdict == "PASS_WITH_LIMITS"
    assert any(item.startswith("UNKNOWN:merchant_revenue") for item in limited.limits)

    stop = classify_poc_review(healthy_runs, reached_candidate_action=True, pii_violation=True)
    assert stop.verdict == "STOP"

    rework = classify_poc_review(healthy_runs[:3], reached_candidate_action=False)
    assert rework.verdict == "REWORK"
