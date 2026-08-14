"""Commercial OS V1 持久化对象。

三本账必须分开：
- Customer Ledger（订阅）
- Partner Commission Ledger（只分基础经营费）
- AI Compute Ledger（真实成本 × 1.30）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class PricingContract(IdMixin, TimestampMixin, Base):
    __tablename__ = "pricing_contract"

    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), index=True)
    billing_cycle: Mapped[str] = mapped_column(String(16), default="monthly")  # monthly | annual
    active_store_count: Mapped[int] = mapped_column(Integer, default=1)
    unit_monthly_cny: Mapped[float] = mapped_column(Float)
    unit_annual_cny: Mapped[float] = mapped_column(Float)
    equiv_monthly_cny: Mapped[float] = mapped_column(Float)
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")


class StoreLicense(IdMixin, TimestampMixin, Base):
    __tablename__ = "store_license"
    __table_args__ = (UniqueConstraint("store_id", name="uq_store_license_store"),)

    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="owned")  # owned | referred
    partner_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="trial")  # trial | paid | churned | refunded
    first_paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    qualified_30d_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    bonus_confirmed_90d_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Subscription(IdMixin, TimestampMixin, Base):
    """Customer Ledger：基础经营订阅。不含 AI 算力。"""

    __tablename__ = "subscription"

    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchant.id"), index=True)
    contract_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    billing_cycle: Mapped[str] = mapped_column(String(16), default="monthly")
    store_count: Mapped[int] = mapped_column(Integer, default=1)
    base_amount_cny: Mapped[float] = mapped_column(Float, default=0)
    collected_amount_cny: Mapped[float] = mapped_column(Float, default=0)
    refunded_amount_cny: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | collected | refunded | void


class AIWallet(IdMixin, TimestampMixin, Base):
    """客户只看人民币余额，不看 Token。"""

    __tablename__ = "ai_wallet"
    __table_args__ = (UniqueConstraint("merchant_id", name="uq_ai_wallet_merchant"),)

    merchant_id: Mapped[str] = mapped_column(String(36), index=True)
    balance_cny: Mapped[float] = mapped_column(Float, default=0)


class AIWalletTopup(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_wallet_topup"

    merchant_id: Mapped[str] = mapped_column(String(36), index=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("ai_wallet.id"), index=True)
    amount_cny: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="collected")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ManualPaymentRequest(IdMixin, TimestampMixin, Base):
    """人工核销工单：种子客户转账后先提交凭证，运营审核后再开通。"""

    __tablename__ = "manual_payment_request"

    merchant_id: Mapped[str] = mapped_column(String(36), index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="subscription")  # subscription | wallet
    billing_cycle: Mapped[str] = mapped_column(String(16), default="monthly")
    amount_cny: Mapped[float] = mapped_column(Float, default=0)
    payer_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    transfer_note: Mapped[str] = mapped_column(String(120))
    evidence_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_ref: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class AIUsageLedger(IdMixin, TimestampMixin, Base):
    """AI Compute Ledger 明细。"""

    __tablename__ = "ai_usage_ledger"

    merchant_id: Mapped[str] = mapped_column(String(36), index=True)
    store_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    period_month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    purpose: Mapped[str] = mapped_column(String(64), default="operating")
    category: Mapped[str] = mapped_column(String(32), default="其他")
    model_tier: Mapped[str] = mapped_column(String(16), default="luna")  # code | luna | terra | sol
    lane: Mapped[str] = mapped_column(String(16), default="operating")  # operating | acquisition
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    actual_cost_cny: Mapped[float] = mapped_column(Float, default=0)
    billed_cny: Mapped[float] = mapped_column(Float, default=0)
    extra_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AIComputeInvoice(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_compute_invoice"
    __table_args__ = (UniqueConstraint("merchant_id", "period_month", name="uq_ai_invoice_merchant_month"),)

    merchant_id: Mapped[str] = mapped_column(String(36), index=True)
    period_month: Mapped[str] = mapped_column(String(7))
    actual_cost_cny: Mapped[float] = mapped_column(Float, default=0)
    billed_cny: Mapped[float] = mapped_column(Float, default=0)
    store_count: Mapped[int] = mapped_column(Integer, default=1)
    budget_actual_cny: Mapped[float] = mapped_column(Float, default=0)
    throttle_state: Mapped[str] = mapped_column(String(24), default="normal")
    status: Mapped[str] = mapped_column(String(16), default="open")


class Partner(IdMixin, TimestampMixin, Base):
    __tablename__ = "partner"

    display_name: Mapped[str] = mapped_column(String(120))
    merchant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    qualification: Mapped[str] = mapped_column(String(16), default="standard")  # standard | service
    can_onboard: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PartnerReferral(IdMixin, TimestampMixin, Base):
    __tablename__ = "partner_referral"
    __table_args__ = (UniqueConstraint("store_id", name="uq_partner_referral_store"),)

    partner_id: Mapped[str] = mapped_column(ForeignKey("partner.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(String(36), index=True)
    store_id: Mapped[str] = mapped_column(String(36), index=True)
    source: Mapped[str] = mapped_column(String(24), default="direct")  # direct | expansion
    status: Mapped[str] = mapped_column(String(16), default="open")


class PartnerPerformanceYear(IdMixin, TimestampMixin, Base):
    __tablename__ = "partner_performance_year"
    __table_args__ = (UniqueConstraint("partner_id", "year", name="uq_partner_year"),)

    partner_id: Mapped[str] = mapped_column(ForeignKey("partner.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    new_qualified_stores: Mapped[int] = mapped_column(Integer, default=0)
    bonus_confirmed_stores: Mapped[int] = mapped_column(Integer, default=0)
    y1_rate: Mapped[float] = mapped_column(Float, default=0.50)
    bonus_accrual_cny: Mapped[float] = mapped_column(Float, default=0)
    bonus_paid_cny: Mapped[float] = mapped_column(Float, default=0)


class PartnerCohort(IdMixin, TimestampMixin, Base):
    __tablename__ = "partner_cohort"
    __table_args__ = (UniqueConstraint("store_id", name="uq_partner_cohort_store"),)

    partner_id: Mapped[str] = mapped_column(ForeignKey("partner.id"), index=True)
    store_id: Mapped[str] = mapped_column(String(36), index=True)
    first_paid_year: Mapped[int] = mapped_column(Integer)
    first_paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    y1_rate: Mapped[float] = mapped_column(Float, default=0.50)


class CommissionLedger(IdMixin, TimestampMixin, Base):
    """Partner Commission Ledger。base 只能是到账基础经营订阅。"""

    __tablename__ = "commission_ledger"

    partner_id: Mapped[str] = mapped_column(ForeignKey("partner.id"), index=True)
    store_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    merchant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    period_month: Mapped[str] = mapped_column(String(7), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="base")  # base | performance_trueup | y2 | y3 | tail
    subscription_base_cny: Mapped[float] = mapped_column(Float, default=0)
    rate: Mapped[float] = mapped_column(Float, default=0)
    amount_cny: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="accrued")  # accrued | payable | paid | void
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class GrowthArtifact(IdMixin, TimestampMixin, Base):
    """Result → 结果卡。可隐藏店名/GMV/利润绝对值。"""

    __tablename__ = "growth_artifact"

    store_id: Mapped[str] = mapped_column(String(36), index=True)
    loop_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    metric: Mapped[str] = mapped_column(String(64), default="")
    lift_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hide_store_name: Mapped[bool] = mapped_column(Boolean, default=True)
    hide_absolute_money: Mapped[bool] = mapped_column(Boolean, default=True)
    cta: Mapped[str] = mapped_column(String(40), default="测一下我的店")
    share_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ReferralAttribution(IdMixin, TimestampMixin, Base):
    __tablename__ = "referral_attribution"

    artifact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    partner_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    from_store_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    to_store_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    path: Mapped[str] = mapped_column(String(32), default="result_share")  # result_share | partner_direct
    status: Mapped[str] = mapped_column(String(16), default="open")
