"""Notification — 正式通知表（替代 AppSetting hack）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notification"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    notification_type: Mapped[str] = mapped_column(String(32))  # need_you / goal_deviation / experiment_result / safe_mode / opportunity / auto_done
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")  # urgent / high / normal / low
    action_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    related_decision_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 通知治理：节流/合并
    clock_phase: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # morning_readiness / lunch_nba / ...
    digest_group: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 合并组 key
    push_status: Mapped[str] = mapped_column(String(16), default="delivered")  # delivered | queued | read
    push_suppressed_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
