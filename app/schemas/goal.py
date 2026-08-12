"""Goal schema — 老板设定的长期经营目标。"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class GoalCreateRequest(BaseModel):
    """老板创建目标（支持自然语言 + 结构化字段）。"""
    raw_text: str  # "牛肉饭做到附近前三"
    metric: str = "custom"  # gmv/orders/ctr/cvr/rating/rank/take_home_rate/custom
    target_value: Optional[float] = None
    deadline: Optional[date] = None


class GoalView(BaseModel):
    """目标视图（首页展示 + 偏差检测用）。"""
    id: str
    store_id: str
    raw_text: str
    metric: str
    target_value: Optional[float] = None
    deadline: Optional[date] = None
    status: str = "active"
    current_value: Optional[float] = None
    forecast_value: Optional[float] = None
    gap: Optional[float] = None
    gap_pct: Optional[float] = None  # gap / target
    on_track: Optional[bool] = None  # forecast >= target * 0.95
    last_synced_at: Optional[date] = None
    created_at: Optional[datetime] = None


class GoalSnapshot(BaseModel):
    """门店所有活跃目标的快照。"""
    store_id: str
    active_goals: List[GoalView] = []
    achieved_goals: List[GoalView] = []
    deviation_alerts: List[GoalView] = []  # 偏差大的目标（on_track=False）
