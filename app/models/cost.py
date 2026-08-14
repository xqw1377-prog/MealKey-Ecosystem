from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class CostRecord(IdMixin, TimestampMixin, Base):
    """单品成本记录 — 每次上传成本表生成一条,支持审计与回溯。

    每条记录有 value / source / confidence / observed_at,
    这正是 Business Truth 要求的 "每个事实可溯源" 结构。
    """

    __tablename__ = "cost_record"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"), index=True)
    item_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("menu_item.id"), nullable=True, index=True
    )
    # 商品名称快照(即使 item_id 未匹配到也保留,供人工映射)
    item_name: Mapped[str] = mapped_column(String(200))

    food_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    packaging_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # source: owner_cost_sheet / platform_export / manual_input / ai_estimate
    source: Mapped[str] = mapped_column(String(64), default="owner_cost_sheet")
    # confidence: high(老板上传原表) / medium(平台导出) / low(AI估算)
    confidence: Mapped[str] = mapped_column(String(16), default="high")
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    # 成本所属日期(成本会变动,需要时间维度)
    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 导入批次(同一次上传的记录共享同一 batch_id)
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
