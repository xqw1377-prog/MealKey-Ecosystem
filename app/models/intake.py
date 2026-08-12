from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class IntakeSubmission(IdMixin, TimestampMixin, Base):
    __tablename__ = "intake_submission"

    store_id: Mapped[Optional[str]] = mapped_column(ForeignKey("store.id"), nullable=True)
    merchant_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    store_name: Mapped[str] = mapped_column(String(200))
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    area: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    audience: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pain: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    platform_store_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    readiness: Mapped[str] = mapped_column(String(16), default="partial")
    missing_fields_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_types_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class IntakeRawAsset(IdMixin, TimestampMixin, Base):
    __tablename__ = "intake_raw_asset"

    submission_id: Mapped[str] = mapped_column(ForeignKey("intake_submission.id"))
    asset_type: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

