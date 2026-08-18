"""Ingest official report + collector evidence. Promote only after reconciliation."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_acquisition import CollectorRunRecord, ReconciliationRecord
from app.models.entities import ShopFunnelDaily, Store
from app.schemas.data_acquisition import CollectorRun, ReconciliationRow
from app.services.authorized_session_connector import AuthorizedSessionConnector
from app.services.data_acquisition_pipeline import (
    build_collector_run,
    can_enter_high_confidence_storestate,
    classify_poc_review,
    promote_envelope,
    reconcile_row,
    unknown_minimal_fields,
)
from app.schemas.data_acquisition import FactEnvelope
from app.services.truth_resolution import may_write_funnel_truth


def _parse_day(raw: str) -> date:
    return date.fromisoformat(str(raw)[:10])


def connector_status(store_id: str, platform: str) -> dict[str, Any]:
    connector = AuthorizedSessionConnector()
    health = connector.health_check(store_id, platform)
    caps = connector.capabilities(store_id, platform)
    return {
        "health": health.model_dump(mode="json"),
        "capabilities": [c.model_dump() for c in caps],
        "ladder": [
            "OFFICIAL_API",
            "SERVICE_PROVIDER_API",
            "AUTHORIZED_SESSION",
            "FILE_IMPORT",
            "SCREENSHOT",
            "MERCHANT_CONFIRMATION",
        ],
        "real_fetch": False,
        "note": "未接真实授权店时 fetch=UNAVAILABLE，禁止 Mock 冒充 Truth",
    }


def ingest_reconciliation(
    db: Session,
    *,
    store_id: str,
    platform: str,
    official_rows: list[dict[str, Any]],
    collector_rows: list[dict[str, Any]] | None = None,
    acquisition_mode: str = "AUTHORIZED_SESSION",
    baseline_only: bool = False,
    auth_status: str = "missing",
    data_source: str | None = None,
) -> dict[str, Any]:
    store = db.execute(select(Store).where(Store.id == store_id)).scalar_one_or_none()
    if store is None:
        raise ValueError("store not found")

    started = datetime.now(timezone.utc)
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    official_by_day = {str(r.get("day")): r for r in official_rows}
    collector_by_day = {str(r.get("day")): r for r in (collector_rows or [])}

    rows: list[ReconciliationRow] = []
    promoted = 0
    unknown = unknown_minimal_fields(
        [k for row in official_rows for k, v in row.items() if v is not None and k != "day"]
    )
    if baseline_only or not collector_rows:
        for day_key, official in official_by_day.items():
            for metric in ("orders", "gmv", "merchant_revenue", "refund"):
                if official.get(metric) is None:
                    continue
                row = reconcile_row(
                    day=day_key,
                    metric=metric,
                    collector_value=None,
                    official_value=float(official[metric]),
                    reason="day0_baseline_only" if baseline_only else "collector_missing",
                )
                rows.append(row)
        health = "UNAVAILABLE" if not collector_rows else "DEGRADED"
        entered = False
    else:
        health = "HEALTHY"
        days = sorted(set(official_by_day) | set(collector_by_day))
        for day_key in days:
            official = official_by_day.get(day_key) or {}
            collector = collector_by_day.get(day_key) or {}
            day_ok = True
            for metric in ("orders", "gmv"):
                rec = reconcile_row(
                    day=day_key,
                    metric=metric,
                    collector_value=None if collector.get(metric) is None else float(collector[metric]),
                    official_value=None if official.get(metric) is None else float(official[metric]),
                    reason=str(collector.get("reason") or official.get("reason") or ""),
                )
                rows.append(rec)
                if rec.status not in {"MATCHED", "EXPLAINABLE_DIFF"}:
                    day_ok = False
            if official.get("merchant_revenue") is None and collector.get("merchant_revenue") is None:
                if "merchant_revenue" not in unknown:
                    unknown.append("merchant_revenue")
            elif official.get("merchant_revenue") is not None and collector.get("merchant_revenue") is not None:
                rec = reconcile_row(
                    day=day_key,
                    metric="merchant_revenue",
                    collector_value=float(collector["merchant_revenue"]),
                    official_value=float(official["merchant_revenue"]),
                    reason=str(collector.get("revenue_reason") or ""),
                )
                rows.append(rec)
                if rec.status not in {"MATCHED", "EXPLAINABLE_DIFF"}:
                    day_ok = False
            envelope = FactEnvelope(
                platform=platform,
                store_id=store_id,
                fact_type="daily_gmv",
                fact_key=f"{day_key}:gmv",
                occurred_at=datetime.combine(_parse_day(day_key), datetime.min.time(), tzinfo=timezone.utc),
                value=collector.get("gmv"),
                unit="CNY",
                acquisition_mode=acquisition_mode,  # type: ignore[arg-type]
                source_connector="authorized_session",
                collected_at=started,
            )
            worst = "MATCHED"
            for rec in rows:
                if rec.day != day_key:
                    continue
                if rec.status == "MISMATCH":
                    worst = "MISMATCH"
                    break
                if rec.status == "EXPLAINABLE_DIFF":
                    worst = "EXPLAINABLE_DIFF"
            promoted_env = promote_envelope(envelope, health="HEALTHY", recon=worst)  # type: ignore[arg-type]
            if day_ok and can_enter_high_confidence_storestate(promoted_env):
                _upsert_funnel(
                    db,
                    store_id=store_id,
                    day=_parse_day(day_key),
                    orders=int(collector.get("orders") or official.get("orders") or 0),
                    gmv=float(collector.get("gmv") or official.get("gmv") or 0),
                    source=(str(data_source or "").strip() or str(acquisition_mode or "").strip().lower() or "legacy_unknown_source"),
                )
                promoted += 1
                entered = True
            else:
                entered = False
        entered = promoted > 0

    run = build_collector_run(
        platform=platform,
        store_id=store_id,
        run_id=run_id,
        started_at=started,
        health_status=health,  # type: ignore[arg-type]
        envelopes=[],
        rejected=0,
        unknown_fields=unknown,
        rows=rows,
        auth_status=auth_status,
    )
    _persist_run(db, run, rows)
    db.commit()
    return {
        "run": run.model_dump(mode="json"),
        "reconciliation": [r.model_dump() for r in rows],
        "promoted_days": promoted,
        "entered_storestate": bool(entered) if collector_rows and not baseline_only else False,
        "unknown_fields": unknown,
        "baseline_only": baseline_only or not collector_rows,
    }


def _upsert_funnel(db: Session, *, store_id: str, day: date, orders: int, gmv: float, source: str) -> None:
    row = db.execute(
        select(ShopFunnelDaily).where(ShopFunnelDaily.store_id == store_id, ShopFunnelDaily.day == day)
    ).scalar_one_or_none()
    if row is not None and not may_write_funnel_truth(row.data_source, source):
        return
    if row is None:
        row = ShopFunnelDaily(store_id=store_id, day=day)
        db.add(row)
    row.orders = orders
    row.gmv = gmv
    row.aov = (gmv / orders) if orders else None
    row.data_source = source


def _persist_run(db: Session, run: CollectorRun, rows: list[ReconciliationRow]) -> None:
    db.add(
        CollectorRunRecord(
            platform=run.platform,
            store_id=run.store_id,
            run_id=run.run_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            health_status=run.health_status,
            acquisition_mode=run.acquisition_mode,
            facts_collected=run.facts_collected,
            facts_rejected=run.facts_rejected,
            facts_unknown=run.facts_unknown,
            duplicate_count=run.duplicate_count,
            schema_error_count=run.schema_error_count,
            reconciliation_rate=run.reconciliation_rate,
            critical_value_diff=run.critical_value_diff,
            auth_status=run.auth_status,
            manual_intervention=run.manual_intervention,
            freshness_seconds=run.freshness_seconds,
            unknown_fields_json=json.dumps(run.unknown_fields, ensure_ascii=False),
            notes=run.notes,
        )
    )
    for row in rows:
        db.add(
            ReconciliationRecord(
                store_id=run.store_id,
                run_id=run.run_id,
                day=row.day,
                metric=row.metric,
                collector_value=row.collector_value,
                official_value=row.official_value,
                absolute_diff=row.absolute_diff,
                relative_diff=row.relative_diff,
                reason=row.reason,
                status=row.status,
            )
        )


def list_runs(db: Session, store_id: str) -> list[dict[str, Any]]:
    records = db.execute(
        select(CollectorRunRecord)
        .where(CollectorRunRecord.store_id == store_id)
        .order_by(CollectorRunRecord.started_at.desc())
    ).scalars().all()
    return [
        {
            "run_id": r.run_id,
            "health_status": r.health_status,
            "acquisition_mode": r.acquisition_mode,
            "reconciliation_rate": r.reconciliation_rate,
            "unknown_fields": json.loads(r.unknown_fields_json or "[]"),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "entered_hint": r.health_status == "HEALTHY",
        }
        for r in records
    ]


def poc_review(db: Session, store_id: str, *, reached_candidate_action: bool) -> dict[str, Any]:
    from app.schemas.data_acquisition import CollectorRun

    records = db.execute(
        select(CollectorRunRecord).where(CollectorRunRecord.store_id == store_id)
    ).scalars().all()
    runs = [
        CollectorRun(
            platform=r.platform,
            store_id=r.store_id,
            run_id=r.run_id,
            started_at=r.started_at,
            completed_at=r.completed_at,
            health_status=r.health_status,  # type: ignore[arg-type]
            acquisition_mode=r.acquisition_mode,  # type: ignore[arg-type]
            facts_collected=r.facts_collected,
            facts_rejected=r.facts_rejected,
            facts_unknown=r.facts_unknown,
            reconciliation_rate=r.reconciliation_rate,
            auth_status=r.auth_status,  # type: ignore[arg-type]
            unknown_fields=json.loads(r.unknown_fields_json or "[]"),
        )
        for r in records
    ]
    return classify_poc_review(runs, reached_candidate_action=reached_candidate_action).model_dump()
