from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class StoreStateSnapshotRecord(IdMixin, TimestampMixin, Base):
    """某一时刻 AI 对门店统一认知的快照。"""

    __tablename__ = "store_state_snapshot"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    state_json: Mapped[str] = mapped_column(Text, default="{}")


class MerchantContextItemRecord(IdMixin, TimestampMixin, Base):
    """细粒度 merchant context item，而不是整段聊天记录。"""

    __tablename__ = "merchant_context_item"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    merchant_id: Mapped[Optional[str]] = mapped_column(ForeignKey("merchant.id"), nullable=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(24), default="user")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    required_for_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocking: Mapped[str] = mapped_column(String(24), default="none")
    ask_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class SignalRecord(IdMixin, TimestampMixin, Base):
    """高频原始 signal。大部分不会直接进入经营系统。"""

    __tablename__ = "signal"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    state_snapshot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("store_state_snapshot.id"), nullable=True)
    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metric: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class BusinessEventRecord(IdMixin, TimestampMixin, Base):
    """有经营意义的 event，和 trigger reason 明确分开。"""

    __tablename__ = "business_event"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    state_snapshot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("store_state_snapshot.id"), nullable=True)
    source_signal_id: Mapped[Optional[str]] = mapped_column(ForeignKey("signal.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    domain: Mapped[str] = mapped_column(String(32))
    subject_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    observation_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class DailyOperatingPlanRecord(IdMixin, TimestampMixin, Base):
    """Deep Review 后生成的当日经营计划。"""

    __tablename__ = "daily_operating_plan"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    plan_date: Mapped[date] = mapped_column(Date)
    runtime_state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    current_meal_period: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    core_goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    focus_meal_period: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    active_experiment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    protected_metrics_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_exec_budget_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active_threads_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    check_points_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")


class RuntimeEventRecord(IdMixin, TimestampMixin, Base):
    """Runtime V1 统一事件包。"""

    __tablename__ = "runtime_event"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    state: Mapped[str] = mapped_column(String(32))
    node: Mapped[str] = mapped_column(String(32))
    trigger_reason: Mapped[str] = mapped_column(String(32))
    domain: Mapped[str] = mapped_column(String(32))
    event_level: Mapped[str] = mapped_column(String(16), default="event")
    subject_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    execution_mode: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    source_odo_id: Mapped[Optional[str]] = mapped_column(ForeignKey("operating_decision.id"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class OperatingActionRecord(IdMixin, TimestampMixin, Base):
    """系统真正执行的动作审计。"""

    __tablename__ = "operating_action"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    work_thread_id: Mapped[Optional[str]] = mapped_column(ForeignKey("operating_thread.id"), nullable=True)
    odo_id: Mapped[Optional[str]] = mapped_column(ForeignKey("operating_decision.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64))
    executor: Mapped[str] = mapped_column(String(16), default="AI")
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    parameters_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    permission_basis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="READY")
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentResultRecord(IdMixin, TimestampMixin, Base):
    """Experiment 的独立结果对象。"""

    __tablename__ = "experiment_result"

    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiment.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    primary_result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    secondary_results_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    guardrails_passed: Mapped[str] = mapped_column(String(8), default="true")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
