from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class Goal(IdMixin, TimestampMixin, Base):
    """老板设定的长期经营目标。

    AI 会持续推进、定期回填进度、检测偏差。
    示例："牛肉饭做到附近前三""本月 GMV 做到 20 万""利润率拉回 18%"。
    """

    __tablename__ = "goal"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    raw_text: Mapped[str] = mapped_column(Text)  # 老板原话
    metric: Mapped[str] = mapped_column(String(32))  # gmv/orders/ctr/cvr/rating/rank/take_home_rate/custom
    target_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/achieved/abandoned
    # AI 定期回填
    current_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    forecast_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # target - forecast
    last_synced_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
