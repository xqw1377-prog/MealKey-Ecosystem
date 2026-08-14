from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, String, Text, UniqueConstraint
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


class MemoryChangedDecision(IdMixin, TimestampMixin, Base):
    """因为过去某个真实 Result，这一次做出了不同判断。

    10 条是学习飞轮的 Production Evidence，不是装饰性记忆表。
    """

    __tablename__ = "memory_changed_decision"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_memory_changed_fingerprint"),)

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(220), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    naive_mode: Mapped[str] = mapped_column(String(32))
    learned_mode: Mapped[str] = mapped_column(String(32))
    cause: Mapped[str] = mapped_column(String(24))  # positive_boost | negative_drop
    source: Mapped[str] = mapped_column(String(32), default="execution_policy")
    memory_result: Mapped[str] = mapped_column(String(16), default="positive")
