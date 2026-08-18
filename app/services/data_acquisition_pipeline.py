"""DATA-AS-01 pipeline: Evidence → reconcile → (maybe) Business Fact.

Connector 仍只产出 FactEnvelope。本模块决定能否晋升，不伪造缺失字段。
未接真实平台时不得把 Mock 写成高置信 Truth。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.schemas.data_acquisition import (
    ACQUISITION_LADDER,
    ORDER_FACT_ALLOWLIST,
    POC_MINIMAL_FACT_KEYS,
    AcquisitionMode,
    CollectorRun,
    ConnectorHealthStatus,
    FactEnvelope,
    PocReview,
    PocVerdict,
    ReconciliationRow,
    ReconciliationStatus,
)

# 授权会话即使对账通过，也不升到官方 API 同级。
_MODE_CONFIDENCE: dict[AcquisitionMode, float] = {
    "OFFICIAL_API": 0.95,
    "SERVICE_PROVIDER_API": 0.90,
    "AUTHORIZED_SESSION": 0.70,
    "FILE_IMPORT": 0.75,
    "SCREENSHOT": 0.40,
    "MERCHANT_CONFIRMATION": 0.85,
}

_UNHEALTHY: frozenset[ConnectorHealthStatus] = frozenset(
    {"AUTH_REQUIRED", "SCHEMA_CHANGED", "UNAVAILABLE"}
)

PII_DENIED_KEYS: frozenset[str] = frozenset(
    {"name", "customer_name", "phone", "mobile", "address", "full_address"}
)


def filter_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    """Allowlist only. Denied / unknown keys are dropped, never guessed."""
    rejected = 0
    kept: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if key in PII_DENIED_KEYS or key not in ORDER_FACT_ALLOWLIST:
            rejected += 1
            continue
        kept[key] = value
    return kept, rejected


def reconcile_row(
    *,
    day: str,
    metric: str,
    collector_value: float | None,
    official_value: float | None,
    reason: str = "",
    match_tolerance: float = 0.01,
) -> ReconciliationRow:
    if collector_value is None or official_value is None:
        return ReconciliationRow(
            day=day,
            metric=metric,  # type: ignore[arg-type]
            collector_value=float(collector_value or 0),
            official_value=float(official_value or 0),
            absolute_diff=0.0,
            relative_diff=0.0,
            reason=reason or "missing_side",
            status="UNCHECKED",
        )
    abs_diff = abs(collector_value - official_value)
    denom = abs(official_value) if official_value != 0 else 1.0
    rel = abs_diff / denom
    if rel <= match_tolerance:
        status: ReconciliationStatus = "MATCHED"
    elif reason:
        status = "EXPLAINABLE_DIFF"
    else:
        status = "MISMATCH"
    return ReconciliationRow(
        day=day,
        metric=metric,  # type: ignore[arg-type]
        collector_value=collector_value,
        official_value=official_value,
        absolute_diff=abs_diff,
        relative_diff=rel,
        reason=reason,
        status=status,
    )


def promote_envelope(
    envelope: FactEnvelope,
    *,
    health: ConnectorHealthStatus,
    recon: ReconciliationStatus,
) -> FactEnvelope:
    """晋升规则：不健康 / 未对账 / 错账 → 不进高置信。"""
    updated = envelope.model_copy()
    updated.reconciliation_status = recon
    if health in _UNHEALTHY or recon in {"UNCHECKED", "MISMATCH", "BLOCKED"}:
        updated.confidence = 0.0
        if health in _UNHEALTHY:
            updated.reconciliation_status = "BLOCKED"
        return updated
    if recon == "EXPLAINABLE_DIFF":
        updated.confidence = min(_MODE_CONFIDENCE[envelope.acquisition_mode], 0.55)
        return updated
    updated.confidence = _MODE_CONFIDENCE[envelope.acquisition_mode]
    return updated


def can_enter_high_confidence_storestate(envelope: FactEnvelope) -> bool:
    return (
        envelope.reconciliation_status == "MATCHED"
        and envelope.confidence >= 0.7
        and envelope.value is not None
    )


def unknown_minimal_fields(available_keys: Iterable[str]) -> list[str]:
    have = set(available_keys)
    return [key for key in POC_MINIMAL_FACT_KEYS if key not in have]


def build_collector_run(
    *,
    platform: str,
    store_id: str,
    run_id: str,
    started_at: datetime,
    health_status: ConnectorHealthStatus,
    envelopes: list[FactEnvelope],
    rejected: int,
    unknown_fields: list[str],
    rows: list[ReconciliationRow],
    auth_status: str = "missing",
    manual_intervention: bool = False,
    duplicate_count: int = 0,
    schema_error_count: int = 0,
) -> CollectorRun:
    completed = datetime.now(timezone.utc)
    matched = sum(1 for row in rows if row.status in {"MATCHED", "EXPLAINABLE_DIFF"})
    rate = (matched / len(rows)) if rows else None
    critical = None
    money_rows = [r for r in rows if r.metric in {"gmv", "merchant_revenue", "refund"}]
    if money_rows:
        critical = max(r.relative_diff for r in money_rows)
    freshness = int((completed - started_at).total_seconds())
    return CollectorRun(
        platform=platform,
        store_id=store_id,
        run_id=run_id,
        started_at=started_at,
        completed_at=completed,
        health_status=health_status,
        facts_collected=len(envelopes),
        facts_rejected=rejected,
        facts_unknown=len(unknown_fields),
        duplicate_count=duplicate_count,
        schema_error_count=schema_error_count,
        reconciliation_rate=rate,
        critical_value_diff=critical,
        auth_status=auth_status,  # type: ignore[arg-type]
        manual_intervention=manual_intervention,
        freshness_seconds=freshness,
        unknown_fields=list(unknown_fields),
    )


def classify_poc_review(
    runs: list[CollectorRun],
    *,
    reached_candidate_action: bool,
    security_violation: bool = False,
    pii_violation: bool = False,
) -> PocReview:
    if security_violation or pii_violation:
        reasons = []
        if security_violation:
            reasons.append("credential_or_unauthorized")
        if pii_violation:
            reasons.append("unnecessary_pii")
        return PocReview(
            verdict="STOP",
            day_count=len(runs),
            reliability_ok=False,
            stop_reasons=reasons,
            reached_candidate_action=reached_candidate_action,
        )
    if len(runs) < 7:
        return PocReview(
            verdict="REWORK",
            day_count=len(runs),
            reliability_ok=False,
            limits=["incomplete_7_days"],
            reached_candidate_action=reached_candidate_action,
        )
    unhealthy = sum(1 for r in runs if r.health_status in _UNHEALTHY)
    rates = [r.reconciliation_rate for r in runs if r.reconciliation_rate is not None]
    avg_rate = sum(rates) / len(rates) if rates else 0.0
    unknown = sorted({field for r in runs for field in r.unknown_fields})
    reliability_ok = unhealthy == 0 and avg_rate >= 0.99
    limits: list[str] = []
    if unknown:
        limits.extend(f"UNKNOWN:{name}" for name in unknown)
    if not reached_candidate_action:
        limits.append("no_candidate_action")

    verdict: PocVerdict
    if not reliability_ok:
        verdict = "REWORK"
    elif limits:
        verdict = "PASS_WITH_LIMITS"
    else:
        verdict = "PASS"
    return PocReview(
        verdict=verdict,
        day_count=len(runs),
        reliability_ok=reliability_ok,
        limits=limits,
        reached_candidate_action=reached_candidate_action,
    )


def ladder_rank(mode: AcquisitionMode) -> int:
    return ACQUISITION_LADDER.index(mode)
