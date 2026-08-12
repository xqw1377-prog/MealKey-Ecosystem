from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class OperatingThread(IdMixin, TimestampMixin, Base):
    """经营线程：可跨日/跨周持续推进的故事线。

    不同于一次性任务，线程承载"午餐增长计划""牛肉饭做到前三"这种
    需要持续多步推进、跨日跟踪的经营主线。
    老板回来后不用重新问"上次做到哪了"，AI 自己知道。
    """

    __tablename__ = "operating_thread"

    store_id: Mapped[str] = mapped_column(ForeignKey("store.id"))
    goal_id: Mapped[Optional[str]] = mapped_column(ForeignKey("goal.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))  # "午餐增长计划"
    goal_text: Mapped[str] = mapped_column(Text)  # "午餐订单 +20%"
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/completed/paused
    done_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: ["主图优化 ✅ CTR+12%"]
    doing_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: ["29元套餐实验 剩余31h"]
    next_step: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # "如果 CVR≥18% → 放大 CPC"
    current_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # "午餐订单 +8.7%"
    ai_judgment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # "进度正常"
    needs_owner: Mapped[bool] = mapped_column(Boolean, default=False)
