"""Operating Demand — MealKey 经营需求基准库。

200个外卖经营需求(101-300),每个需求映射到:
- 用户意图
- 闭环类型(A/B/C)
- 所需数据
- 预期诊断
- 预期动作
- 当前代码覆盖率
- 成功指标

这是 MealKey 的产品基准,不是技术基准。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class OperatingDemand(IdMixin, TimestampMixin, Base):
    """经营需求 — 每条代表老板会问的一个真实经营问题。"""

    __tablename__ = "operating_demand"

    demand_id: Mapped[int] = mapped_column(Integer, index=True)  # 101-300
    category: Mapped[str] = mapped_column(String(64))  # 财务对账/规则合规/新店启动/...
    question: Mapped[str] = mapped_column(Text)  # 老板真正会问的问题
    loop_type: Mapped[str] = mapped_column(String(1))  # A/B/C

    # 闭环规格
    required_facts: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: 需要哪些数据
    expected_diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 预期诊断方向
    expected_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 预期动作类型
    forbidden_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 禁止动作
    success_metric: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 成功指标
    observation_window_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 覆盖率评估
    coverage_status: Mapped[str] = mapped_column(String(16), default="not_covered")
    # not_covered / partial / covered / verified
    coverage_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(4), default="P2")  # P0/P1/P2/P3

    # 关联代码
    service_module: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    api_endpoint: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
