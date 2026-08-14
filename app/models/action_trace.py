"""Action Trace — 追溯"为什么 AI 做了这个动作"（Runtime Bridge Tracing 理念）。

完整链路：Signal → Event → ODO → Evidence → Permission → Tool Call → Result
每一步都记录，让老板的"为什么你多花了 60 块"可以完整回答。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class ActionTrace(IdMixin, TimestampMixin, Base):
    """动作执行追踪——一个动作的完整因果链。"""

    __tablename__ = "action_trace"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    odo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    work_thread_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    recommendation_id: Mapped[Optional[str]] = mapped_column(ForeignKey("recommendation.id"), nullable=True)
    experiment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 因果链
    trigger_source: Mapped[str] = mapped_column(String(32))  # signal / event / time / goal / opportunity
    trigger_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 什么信号触发的

    # 判断
    diagnosis_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 权限
    execution_mode: Mapped[str] = mapped_column(String(24))  # AUTO / ASK_APPROVAL / ...
    permission_basis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 为什么有权限
    guardrails_check_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # guardrail 结果

    # 执行
    action_type: Mapped[str] = mapped_column(String(64))
    action_params_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executor: Mapped[str] = mapped_column(String(16), default="AI")  # AI / OWNER / SYSTEM

    # 结果
    result_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / success / failed / rolled_back
    result_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost_cny: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 花了多少钱

    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
