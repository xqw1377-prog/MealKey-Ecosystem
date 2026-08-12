from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class MerchantUnderstandingRecord(IdMixin, TimestampMixin, Base):
    """商家理解快照：偏好 / 约束 / 权限 / 推断 / 缺口。

    不是 Settings 表单落库；由 MUE 随对话与平台读取持续更新。
    """

    __tablename__ = "merchant_understanding"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), unique=True, index=True)
    onboarding_stage: Mapped[str] = mapped_column(String(24), default="connect")
    store_profile_json: Mapped[str] = mapped_column(Text, default="{}")
    inferred_json: Mapped[str] = mapped_column(Text, default="[]")
    preferences_json: Mapped[str] = mapped_column(Text, default="{}")
    constraints_json: Mapped[str] = mapped_column(Text, default="{}")
    permissions_json: Mapped[str] = mapped_column(Text, default="{}")
    open_gaps_json: Mapped[str] = mapped_column(Text, default="[]")
    last_interview_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
