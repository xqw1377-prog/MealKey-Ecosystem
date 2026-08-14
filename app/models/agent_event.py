"""AgentEvent — AI 执行过程的可重放轨迹。

借鉴 dsh 的 event-sourced session log 设计:
"model-visible means logged" — 每个模型可见的事实都是持久事件。

Agent 可以死,但事件不能丢。
重放事件序列 = 重建完整推理过程。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class AgentEvent(IdMixin, TimestampMixin, Base):
    """AI agent 执行事件 — append-only 日志。"""

    __tablename__ = "agent_event"

    # 会话标识(一次对话/一次任务)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    store_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # 事件类型
    event_type: Mapped[str] = mapped_column(String(32))
    # turn_start / llm_call / tool_call / tool_result / llm_response / turn_end / error / interrupt

    step_index: Mapped[int] = mapped_column(Integer, default=0)

    # 事件内容 (JSON)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 追踪
    tool_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_input: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_output: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_cny: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 来源
    runtime: Mapped[str] = mapped_column(String(32), default="local")
    # local / dsh / deerflow / external

    # 错误
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
