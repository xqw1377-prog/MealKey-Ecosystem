"""Golden Case — 经典外卖经营案例库。

每个案例是从真实经营场景蒸馏出来的"经营智慧单元":
  什么情况 → 为什么 → 该做什么 → 不该做什么 → 怎么验证 → 经验教训

用途:
1. 新问题进来时,检索最相似的案例辅助判断
2. 给 LLM 提供 few-shot 示例,提升诊断质量
3. 随着真实门店积累,案例库不断扩充
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdMixin, TimestampMixin


class GoldenCase(IdMixin, TimestampMixin, Base):
    """经典经营案例。"""

    __tablename__ = "golden_case"

    # 案例标识
    case_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # GC-001
    category: Mapped[str] = mapped_column(String(64), index=True)  # order_drop/profit_loss/bad_review/...
    title: Mapped[str] = mapped_column(String(200))
    scenario: Mapped[str] = mapped_column(Text)  # 场景描述(老板会怎么问)

    # 经营事实(JSON)
    facts_json: Mapped[str] = mapped_column(Text)  # {"ctr_delta": -18, "orders_delta": -12, ...}
    # 缺失数据
    missing_facts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 诊断
    expected_diagnosis: Mapped[str] = mapped_column(Text)  # 正确诊断方向
    forbidden_diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 常见误判

    # 动作
    expected_action: Mapped[str] = mapped_column(Text)  # 该做什么
    forbidden_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 不该做什么
    execution_mode: Mapped[str] = mapped_column(String(24), default="ASK_APPROVAL")

    # 验证
    success_metric: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    observation_window_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guardrail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 结果与教训
    actual_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lesson: Mapped[str] = mapped_column(Text)  # 一句话经验

    # 匹配标签(用于检索)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # "ctr,order_drop,主图,午高峰"

    # 真实度
    source: Mapped[str] = mapped_column(String(32), default="distilled")  # distilled/real/synthetic
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
