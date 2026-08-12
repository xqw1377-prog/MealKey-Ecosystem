"""Persist and apply manager decisions on operating events."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event_decisions import EventDecisionOverride
from app.schemas.events import EventEngineResult, OperatingEvent


def event_fingerprint(event: OperatingEvent) -> str:
    return f"{event.event_type}|{event.affected_metric or ''}|{event.title}"


def load_decision_map(db: Session, store_id: str) -> dict[str, EventDecisionOverride]:
    rows = db.execute(
        select(EventDecisionOverride).where(EventDecisionOverride.store_id == store_id)
    ).scalars().all()
    return {row.fingerprint: row for row in rows}


def apply_decision_overrides(result: EventEngineResult, overrides: dict[str, EventDecisionOverride]) -> EventEngineResult:
    if not overrides:
        return result
    events: list[OperatingEvent] = []
    for event in result.events:
        fp = event_fingerprint(event)
        override = overrides.get(fp)
        if override is None:
            events.append(event)
            continue
        updated = event.model_copy(
            update={
                "manager_decision": override.decision,  # type: ignore[arg-type]
                "status": override.status,  # type: ignore[arg-type]
            }
        )
        events.append(updated)

    handle_today = sum(1 for e in events if e.manager_decision == "handle_today")
    alerts = sum(1 for e in events if e.manager_decision == "alert_owner")
    open_count = sum(1 for e in events if e.status == "open")
    actionable = handle_today + alerts
    summary = (
        f"MealKey 今天发现 {actionable} 个你需要处理的异常。"
        if actionable
        else "今日暂无必须立刻处理的异常。"
    )
    return result.model_copy(
        update={
            "events": events,
            "open_count": open_count,
            "handle_today_count": handle_today,
            "alert_count": alerts,
            "summary": summary,
        }
    )


def upsert_event_decision(
    db: Session,
    *,
    store_id: str,
    fingerprint: str,
    decision: str,
    note: str | None = None,
) -> EventDecisionOverride:
    status_map = {
        "ignore": "ignored",
        "record": "acknowledged",
        "handle_today": "scheduled_today",
        "alert_owner": "open",
        "resolved": "resolved",
    }
    decision_value = str(decision)
    # manager_decision only accepts ignore/record/handle_today/alert_owner
    if decision_value == "resolved":
        decision_value = "ignore"
        status = "resolved"
    else:
        status = status_map.get(decision_value, "acknowledged")

    row = db.execute(
        select(EventDecisionOverride).where(
            EventDecisionOverride.store_id == store_id,
            EventDecisionOverride.fingerprint == fingerprint,
        )
    ).scalar_one_or_none()
    if row is None:
        row = EventDecisionOverride(
            store_id=store_id,
            fingerprint=fingerprint,
            decision=str(decision_value),
            status=status,
            note=note,
        )
        db.add(row)
    else:
        row.decision = str(decision_value)
        row.status = status
        row.note = note
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row
