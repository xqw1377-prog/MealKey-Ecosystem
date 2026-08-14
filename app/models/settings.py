from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class AppSetting(IdMixin, TimestampMixin, Base):
    """系统级键值配置（可被设置页改写，优先于部分环境默认值）。"""

    __tablename__ = "app_setting"
    __table_args__ = (UniqueConstraint("key", name="uq_app_setting_key"),)

    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(32), default="string")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)


class PlatformConnection(IdMixin, TimestampMixin, Base):
    """门店与外卖平台的连接状态（持久化，重启不丢）。"""

    __tablename__ = "platform_connection"
    __table_args__ = (UniqueConstraint("store_id", "platform", name="uq_store_platform"),)

    store_id: Mapped[str] = mapped_column(String(36))
    platform: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    external_store_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    connector_mode: Mapped[str] = mapped_column(String(32), default="mock")  # mock | http | mobile | oauth
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auth_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ConnectCode(IdMixin, TimestampMixin, Base):
    """手机连接码（落库，多 worker / 重启不丢）。"""

    __tablename__ = "connect_code"
    __table_args__ = (UniqueConstraint("code", name="uq_connect_code"),)

    code: Mapped[str] = mapped_column(String(16), index=True)
    store_id: Mapped[str] = mapped_column(String(36), index=True)
    platform: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
