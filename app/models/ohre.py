from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class Observation(IdMixin, TimestampMixin, Base):
    __tablename__ = "observation"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    scope: Mapped[str] = mapped_column(String(16), default="store")  # store|item|market
    item_id: Mapped[Optional[str]] = mapped_column(ForeignKey("menu_item.id"), nullable=True)

    metric: Mapped[str] = mapped_column(String(64))  # gmv/orders/ctr/cvr/...
    window_days: Mapped[int] = mapped_column(Integer, default=7)
    baseline_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    baseline_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    observe_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    observe_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    baseline_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    what_happened: Mapped[str] = mapped_column(String(300))
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string


class Hypothesis(IdMixin, TimestampMixin, Base):
    __tablename__ = "hypothesis"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    observation_id: Mapped[Optional[str]] = mapped_column(ForeignKey("observation.id"), nullable=True)
    item_id: Mapped[Optional[str]] = mapped_column(ForeignKey("menu_item.id"), nullable=True)

    funnel_stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # impressions|ctr|cvr|repurchase
    root_cause: Mapped[str] = mapped_column(String(300))
    competing_explanations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string
    evidence_refs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string
    confidence: Mapped[float] = mapped_column(Float, default=0.7)


class Recommendation(IdMixin, TimestampMixin, Base):
    __tablename__ = "recommendation"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    hypothesis_id: Mapped[Optional[str]] = mapped_column(ForeignKey("hypothesis.id"), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), default="item")  # item|store|market
    object_ref: Mapped[str] = mapped_column(String(128))  # e.g. item:{id}
    action_type: Mapped[str] = mapped_column(String(64))  # change_image/change_title/add_set_meal/...

    expected_metric: Mapped[str] = mapped_column(String(64), default="ctr")
    expected_lift_pct_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_lift_pct_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    window_hours: Mapped[int] = mapped_column(Integer, default=24)
    rollback_rule: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string for generated content

    status: Mapped[str] = mapped_column(String(24), default="proposed")  # proposed|adopted|executed|archived
    adopted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Experiment(IdMixin, TimestampMixin, Base):
    __tablename__ = "experiment"

    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendation.id"))
    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    item_id: Mapped[Optional[str]] = mapped_column(ForeignKey("menu_item.id"), nullable=True)

    baseline_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lift_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    baseline_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    baseline_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    observe_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    observe_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    control_desc: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    attribution_quality: Mapped[str] = mapped_column(String(16), default="medium")  # high|medium|low
    result: Mapped[str] = mapped_column(String(16), default="pending")  # pending|positive|neutral|negative|unknown
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Runtime V1 §九 补全：Guardrails（主指标 + 护栏）
    guardrails_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: {"cvr_drop_max": -0.03, "margin_min": 0.17}
    success_metric_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: {"metric": "ctr", "minimum_lift": 0.08}
    # Domain Playbook §五：单变量实验约束
    primary_variable: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # image/title/price/bundle/budget
    # Runtime V1 §八 补全：Action 审计
    executor: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # AI / OWNER / SYSTEM
    permission_basis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: {"rule": "ads_auto_budget_limit", "limit": 300}

