"""案例与来源登记的持久化。外部案例不得写入 strategy_memory。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class SourceRegistryRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "source_registry"
    __table_args__ = (UniqueConstraint("source_id", name="uq_source_registry_source_id"),)

    source_id: Mapped[str] = mapped_column(String(64), index=True)
    publisher: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    canonical_url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    authority_level: Mapped[str] = mapped_column(String(8), default="C1")
    ingestion_mode: Mapped[str] = mapped_column(String(24), default="SEMI")
    copyright_mode: Mapped[str] = mapped_column(String(32), default="proprietary")
    phase: Mapped[str] = mapped_column(String(16), default="later")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    research_zone: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_for_rules: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_for_case_prior: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_version: Mapped[str] = mapped_column(String(32), default="1")
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_case_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_case_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class OperatingCaseRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "operating_case"
    __table_args__ = (UniqueConstraint("case_id", name="uq_operating_case_case_id"),)

    case_id: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    demand_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    domain: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    evidence_level: Mapped[str] = mapped_column(String(8), default="L1")
    status: Mapped[str] = mapped_column(String(48), default="case_prior_only")
    authority_level: Mapped[str] = mapped_column(String(8), default="C1")
    source_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.2)
    research_zone: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text)


class CaseIngestionRun(IdMixin, Base):
    __tablename__ = "case_ingestion_run"

    source_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_cases: Mapped[int] = mapped_column(Integer, default=0)
    rejected_cases: Mapped[int] = mapped_column(Integer, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
