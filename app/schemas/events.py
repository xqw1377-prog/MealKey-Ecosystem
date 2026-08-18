from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

EventType = Literal[
    "STORE_ABNORMAL_CLOSED",
    "HERO_SKU_SOLD_OUT",
    "ACTIVITY_EXPIRING",
    "RATING_DROP",
    "IM_REPLY_DROP",
    "CTR_DROP",
    "ORDER_DROP",
    "CVR_DROP",
    "TAKE_RATE_DROP",
    "ADS_ROI_DROP",
    "COMPETITOR_NEW_PROMOTION",
    "COMPETITOR_PRICE_CHANGE",
    "COMPETITOR_NEW_PRODUCT",
    "OPPORTUNITY_DETECTED",
]

EventSeverity = Literal["info", "low", "medium", "high", "critical"]
EventStatus = Literal["open", "acknowledged", "scheduled_today", "resolved", "ignored"]
ManagerDecision = Literal["ignore", "record", "handle_today", "alert_owner"]
EventDecisionInput = Literal["ignore", "record", "handle_today", "alert_owner", "resolved"]

# 5 种 AI 行为决策（步骤 4 升级）
# AI 真正高级不是天天找老板，而是知道什么时候别烦你。
AIAction = Literal[
    "auto_handle",      # AI 自己做（回复评价/调整标题等低风险可逆动作）
    "need_confirm",     # 让老板确认后做（换主图/投流/套餐等中风险动作）
    "need_assist",      # 让老板提供信息/线下协助（拍照/补库存/传资质）
    "inform_only",      # 只告诉老板结果（实验结论/竞品变化，不需要老板做任何事）
    "silent_observe",   # 什么都不做，只观察（信号弱/观察窗内）
]


class OperatingEvent(BaseModel):
    """经营异常事件：监控菜单收敛成事件流，由 AI 店长决策。"""

    id: str
    store_id: str
    event_type: EventType
    title: str
    detail: str
    severity: EventSeverity = "medium"
    detected_at: datetime
    affected_metric: Optional[str] = None
    estimated_impact: Optional[str] = None
    estimated_impact_amount: Optional[float] = None
    confidence: float = 0.7
    recommended_agent: Optional[str] = None
    status: EventStatus = "open"
    manager_decision: Optional[ManagerDecision] = None
    ai_action: Optional[str] = None  # 5 种 AI 行为（auto_handle/need_confirm/need_assist/inform_only/silent_observe）
    fingerprint: Optional[str] = None
    evidence: list[str] = Field(default_factory=list)
    source: str = "event_engine"


class EventEngineResult(BaseModel):
    store_id: str
    generated_at: datetime
    events: list[OperatingEvent] = Field(default_factory=list)
    open_count: int = 0
    handle_today_count: int = 0
    alert_count: int = 0
    summary: str = ""


class EventDecisionRequest(BaseModel):
    fingerprint: str
    decision: EventDecisionInput
    note: Optional[str] = None


class EventDecisionResponse(BaseModel):
    store_id: str
    fingerprint: str
    decision: EventDecisionInput
    status: str
    message: str
    events: EventEngineResult
