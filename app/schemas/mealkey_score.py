"""MealKey Score — 统一外卖健康分（跨 agent 5 维加权）。

文档承诺权重：商品表现 30% / 菜单结构 20% / 竞争能力 20% / 经营趋势 20% / 评价表现 10%
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ScoreDimension(BaseModel):
    """健康分的单个维度。"""
    key: str  # product/menu/competition/trend/review
    label: str
    score: int
    weight: float
    weighted_score: float  # score * weight
    source_agent: str  # 该分来自哪个 agent
    explanation: Optional[str] = None  # 可点击解释


class MealKeyScore(BaseModel):
    """首页核心数字：跨 agent 聚合的统一健康分。"""
    total: int  # 加权总分
    dimensions: list[ScoreDimension] = Field(default_factory=list)
    judgment: Optional[str] = None  # 一句话定性（如"基本盘偏弱，主要拖累在商品表现"）


class OperationDimension(BaseModel):
    """运营基本功的单个维度。"""
    key: str  # meal_prep/im_reply/on_time_delivery/cancel/hero_sku/open
    label: str
    score: Optional[int] = None  # None = 数据未接入
    status: str = "unknown"  # ok | watch | risk | unknown
    note: Optional[str] = None


class OperationScore(BaseModel):
    """运营基本功分：独立于 MealKey Score（业务结果）。

    回答"营业额很好但运营健康度很差"的情况——
    出餐率/回复率/准时率/取消率/核心SKU在售率/营业状态。
    数据未接入时各维度为 None，总分降级。
    """
    total: Optional[int] = None
    dimensions: list[OperationDimension] = Field(default_factory=list)
    data_coverage: str = "none"  # full | partial | none
    judgment: Optional[str] = None
