"""Opportunity schema — 外部找钱机会信号（区别于内部问题补救）。"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class OpportunityTrigger(BaseModel):
    """一个外部找钱机会。

    和 event_engine 的异常事件不同：这不是"出问题了要救火"，
    而是"现在不做也不会出事，但做了能多赚钱"。
    """
    key: str  # 唯一标识
    type: Literal[
        "subsidy_window",      # 平台补贴窗口开放
        "competitor_gap",      # 竞品停投/价格带空档
        "weather_demand",      # 天气/季节导致需求变化
        "daypart_untapped",    # 时段未覆盖（如夜宵流量空档）
        "price_band_gap",      # 价格带空档
    ]
    title: str  # "平台午餐补贴开放，建议参与"
    detail: str  # 具体理由
    expected_gain: Optional[str] = None  # "预计 +8-15% 午餐订单"
    window: Optional[str] = None  # "今天 11:00-13:00"
    source: str = "opportunity_scanner"
    recommended_action: Optional[str] = None  # 建议的动作类型
