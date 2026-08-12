from __future__ import annotations

from typing import Optional

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class EventDecisionOverride(IdMixin, TimestampMixin, Base):
    """Persist AI store-manager decisions against regenerated event fingerprints."""

    __tablename__ = "event_decision_overrides"
    __table_args__ = (UniqueConstraint("store_id", "fingerprint", name="uq_event_decision_store_fp"),)

    store_id: Mapped[str] = mapped_column(String(36), index=True)
    fingerprint: Mapped[str] = mapped_column(String(160))
    decision: Mapped[str] = mapped_column(String(32), default="record")
    status: Mapped[str] = mapped_column(String(32), default="acknowledged")
    note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
