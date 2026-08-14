"""Closed Loop V1 · 一件经营事项从发现走到结果。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class ClosedLoopItem(IdMixin, TimestampMixin, Base):
    """唯一主干：ODO / WorkThread / Now 是同一条记录的不同投影。"""

    __tablename__ = "closed_loop_item"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(180), index=True)
    source_card_id: Mapped[str] = mapped_column(String(128), default="")
    source_event_id: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(200))
    finding: Mapped[str] = mapped_column(Text, default="")
    judgment: Mapped[str] = mapped_column(Text, default="")
    action_type: Mapped[str] = mapped_column(String(64), default="ops_hint")
    object_name: Mapped[str] = mapped_column(String(80), default="")
    pack_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="now", index=True)
    # now | executed | not_executed | observing | result_ready | closed
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    executor: Mapped[str] = mapped_column(String(16), default="OWNER")
    execution_mode: Mapped[str] = mapped_column(String(24), default="")
    assignee_name: Mapped[str] = mapped_column(String(80), default="")
    assignee_role: Mapped[str] = mapped_column(String(24), default="")
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_nagged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    observe_hours: Mapped[int] = mapped_column(Integer, default=48)
    observe_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    success_metric: Mapped[str] = mapped_column(String(64), default="点击率")
    success_target: Mapped[str] = mapped_column(String(80), default="")
    guardrail: Mapped[str] = mapped_column(String(120), default="")
    recommendation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    experiment_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
