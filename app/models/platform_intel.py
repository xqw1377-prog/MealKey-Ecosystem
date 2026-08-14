"""平台官网公开政策 / 促销情报。

只存公开页证据，不爬商家登录后台，不编造活动。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class PlatformIntelItem(IdMixin, TimestampMixin, Base):
    """一条官网公开政策或促销。按 URL 去重。"""

    __tablename__ = "platform_intel_item"
    __table_args__ = (UniqueConstraint("url", name="uq_platform_intel_url"),)

    platform: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # policy / promo / news
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(800))
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_name: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(String(800))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    status: Mapped[str] = mapped_column(String(24), default="active")  # active / stale


class PlatformIntelRun(IdMixin, Base):
    """一次全网公开页采集审计。失败如实记录，不假装有活动。"""

    __tablename__ = "platform_intel_run"

    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
