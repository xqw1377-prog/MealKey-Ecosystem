from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class StrategyMemoryRecord(IdMixin, TimestampMixin, Base):
    """Persist Experiment Result lessons for future Growth decisions."""

    __tablename__ = "strategy_memory"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    experiment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("experiment.id"), nullable=True)
    recommendation_id: Mapped[Optional[str]] = mapped_column(ForeignKey("recommendation.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), default="unknown")
    lift_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    context_tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lesson: Mapped[str] = mapped_column(String(400))
    reuse_when: Mapped[str] = mapped_column(String(300))
    avoid_when: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.6)
