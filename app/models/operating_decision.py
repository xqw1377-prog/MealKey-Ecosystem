"""OperatingDecision — MealKey 对每件事的完整经营判断（Runtime V1 核心 Contract）。

材料 §六：ODO 是核心 Contract，必须落库可审计。
"AI 当时基于什么店铺状态做这个决定的？" 是可解释性和后续学习的基础。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class OperatingDecision(IdMixin, TimestampMixin, Base):
    """经营决策对象——一次完整的经营判断。

    生命周期：created → arbitrated → executing → observed → resolved
    """

    __tablename__ = "operating_decision"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    goal_id: Mapped[Optional[str]] = mapped_column(ForeignKey("goal.id"), nullable=True)
    work_thread_id: Mapped[Optional[str]] = mapped_column(ForeignKey("operating_thread.id"), nullable=True)
    runtime_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    analysis_node: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_event_id: Mapped[Optional[str]] = mapped_column(ForeignKey("runtime_event.id"), nullable=True)

    # 为什么现在
    trigger_reason: Mapped[str] = mapped_column(String(32))  # anomaly/time/goal/opportunity/result/history/understanding
    domain: Mapped[str] = mapped_column(String(32))  # product/traffic/profit/competition/crm/review/service/menu
    subject_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # sku/store/campaign
    subject_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # AI 当时基于的状态快照 ID（可解释性）
    state_snapshot_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 发现 + 判断
    observation_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comparison_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)

    # 价值
    estimated_impact_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    goal_relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 方案
    candidate_actions_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    selected_action_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 风险
    profitability_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="medium")  # low/medium/high
    reversibility: Mapped[str] = mapped_column(String(16), default="medium")  # easy/medium/hard

    # 执行
    execution_mode: Mapped[str] = mapped_column(String(24), default="ASK_APPROVAL")
    # AUTO / AUTO_AND_REPORT / ASK_APPROVAL / ASK_INFORMATION / OBSERVE / DROP

    # 需要老板
    human_request_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 实验
    success_metric_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    observation_window_hours: Mapped[int] = mapped_column(default=48)

    # 后续
    next_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 状态
    status: Mapped[str] = mapped_column(String(16), default="created")
    # created / arbitrated / executing / observed / resolved / dropped
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
