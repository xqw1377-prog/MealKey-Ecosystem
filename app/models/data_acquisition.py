"""DATA-AS-01 / TE-01 persistence. No cookies, passwords, or raw PII."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class CollectorRunRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "collector_run"

    platform: Mapped[str] = mapped_column(String(64))
    store_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(32))
    acquisition_mode: Mapped[str] = mapped_column(String(32))
    facts_collected: Mapped[int] = mapped_column(Integer, default=0)
    facts_rejected: Mapped[int] = mapped_column(Integer, default=0)
    facts_unknown: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_error_count: Mapped[int] = mapped_column(Integer, default=0)
    reconciliation_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    critical_value_diff: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    auth_status: Mapped[str] = mapped_column(String(24), default="missing")
    manual_intervention: Mapped[bool] = mapped_column(default=False)
    freshness_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unknown_fields_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ReconciliationRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_row"

    store_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[str] = mapped_column(String(16), index=True)
    metric: Mapped[str] = mapped_column(String(32))
    collector_value: Mapped[float] = mapped_column(Float)
    official_value: Mapped[float] = mapped_column(Float)
    absolute_diff: Mapped[float] = mapped_column(Float)
    relative_diff: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(24), default="UNCHECKED")


class IncrementalResultRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "incremental_result"

    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    store_id: Mapped[str] = mapped_column(String(36), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    treatment: Mapped[str] = mapped_column(String(64))
    control: Mapped[str] = mapped_column(String(64), default="no_action")
    observed_lift_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    incremental_orders: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    incremental_revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    incremental_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_grade: Mapped[str] = mapped_column(String(32), default="L0_RESEARCH")
    source: Mapped[str] = mapped_column(String(32), default="sandbox")
    summary: Mapped[str] = mapped_column(String(300), default="")
    created_at_override: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
