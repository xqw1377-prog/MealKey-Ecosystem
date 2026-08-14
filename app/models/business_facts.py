"""业务事实表 — 投流、活动、评价导入的持久化层。

每个事实都有 source/confidence/observed_at,支持审计与溯源。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class AdSpendDaily(IdMixin, TimestampMixin, Base):
    """每日推广费用记录 — CPC/投流数据。

    来源:平台导出 / 手动录入 / API
    """

    __tablename__ = "ad_spend_daily"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # meituan/eleme/douyin

    # 核心指标
    cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 推广花费(元)
    impressions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 广告曝光
    clicks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 广告点击
    orders_from_ads: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 广告带来订单
    gmv_from_ads: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 广告带来 GMV

    # 派生
    cpc: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # cost / clicks
    ctr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # clicks / impressions
    roas: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # gmv_from_ads / cost

    # Provenance
    source: Mapped[str] = mapped_column(String(64), default="platform_export")
    confidence: Mapped[str] = mapped_column(String(16), default="high")
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)


class CampaignRecord(IdMixin, TimestampMixin, Base):
    """平台活动记录 — 活动规则 + 执行状态。

    来源:手动录入 / 平台导出
    """

    __tablename__ = "campaign_record"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    name: Mapped[str] = mapped_column(String(200))  # 活动名称
    campaign_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # discount/bundle/coupon/fullcut

    # 活动规则
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    discount_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 优惠金额
    discount_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # amount/percent
    platform_subsidy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 平台承担
    merchant_subsidy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 商家承担
    min_order_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 满减门槛

    # 状态
    status: Mapped[str] = mapped_column(String(24), default="active")  # active/ended/opted_out/unknown

    # Provenance
    source: Mapped[str] = mapped_column(String(64), default="manual_input")
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    source_url: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    intel_item_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)


class ReviewImport(IdMixin, TimestampMixin, Base):
    """评价导入记录 — 从平台导出的评价数据。

    ReviewFact 是只读诊断用;ReviewImport 是导入层,带 provenance。
    导入后会同步写入 ReviewFact 供诊断使用。
    """

    __tablename__ = "review_import"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    reviewer_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 1-5
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 商家回复
    reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 同步到 ReviewFact 的 ID (去重用)
    review_fact_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("review_fact.id"), nullable=True
    )

    # Provenance
    source: Mapped[str] = mapped_column(String(64), default="platform_export")
    confidence: Mapped[str] = mapped_column(String(16), default="high")
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)


class OpsMetricDaily(IdMixin, TimestampMixin, Base):
    """平台运营指标日表 — IM 回复率 / 出餐率 / 准时率 / 商责取消率。

    无数据时保持 unknown，不编造。来源：CSV 导入或连接器。
    """

    __tablename__ = "ops_metric_daily"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    im_reply_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    meal_prep_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    on_time_delivery_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    merchant_cancel_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(64), default="platform_export")
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
