"""AI 经营仲裁：交互单位 = 事件 → 判断 → 行动 → 介入 → 结果。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ArbiterState = Literal[
    "auto_do",
    "confirm",
    "need_input",
    "report_result",
    "noop",
]

InterruptReason = Literal[
    "time",
    "anomaly",
    "history",
    "opportunity",
    "goal",
    "result",
    "understanding",  # MUE：AI 无法自知、必须问老板
]

QueueBucket = Literal["need_you", "working", "result", "opportunity", "goal"]

DecisionActionKind = Literal[
    "adopt",
    "execute",
    "ignore",
    "evaluate",
    "event_decision",
    "scroll",
    "focus_intent",
    "upload_cost",
]


class DecisionAction(BaseModel):
    label: str
    kind: DecisionActionKind = "scroll"
    class_name: str = "primary"
    recommendation_id: Optional[str] = None
    experiment_id: Optional[str] = None
    event_fingerprint: Optional[str] = None
    event_decision: Optional[str] = None
    scroll_target: Optional[str] = None


class DecisionCard(BaseModel):
    """决策卡：回答五问 + ODO 补全字段（材料 §八）。"""

    id: str
    title: str
    arbiter_state: ArbiterState
    interrupt_reason: InterruptReason = "anomaly"
    queue_bucket: QueueBucket
    priority_score: float = 0.0
    why_now: str = ""
    ai_judgment: str = ""
    ai_already_did: str = ""
    need_from_owner: str = ""
    success_metric: str = ""
    summary: str = ""
    meta: str = ""
    actions: list[DecisionAction] = Field(default_factory=list)
    # B3 补全：Operating Decision Object 缺失字段
    evidence: list[str] = Field(default_factory=list)  # 证据链
    business_impact: str = ""  # 量化经营影响
    estimated_loss: Optional[float] = None  # 预计损失单量
    goal_relevance: str = ""  # 和老板目标的关系
    observation_window_hours: int = 48  # 观察窗
    next_check: Optional[str] = None  # 下次检查时间
    confidence: float = 0.7  # 置信度
    safe_mode_blocked: bool = False  # 是否被 Safe Mode 拦截


class ActiveGoalBrief(BaseModel):
    title: str
    current_status: str = ""
    progress_summary: str = ""
    next_step: str = ""
    blocked_by: str = ""
    ai_judgment: str = ""


class OperatingThreadBrief(BaseModel):
    """经营线程：不是任务列表项，而是可跨周推进的故事线。"""

    id: str
    title: str
    goal: str = ""
    done: list[str] = Field(default_factory=list)
    doing: list[str] = Field(default_factory=list)
    next_step: str = ""
    current_result: str = ""
    ai_judgment: str = ""
    needs_owner: bool = False


class OpsQueueBrief(BaseModel):
    need_you: list[DecisionCard] = Field(default_factory=list)
    working: list[DecisionCard] = Field(default_factory=list)
    results: list[DecisionCard] = Field(default_factory=list)
    opportunities: list[DecisionCard] = Field(default_factory=list)
    active_goal: Optional[ActiveGoalBrief] = None
    threads: list[OperatingThreadBrief] = Field(default_factory=list)
    principle: str = "系统负责发现所有事情，AI负责筛掉绝大多数事情，老板只处理必须由老板处理的事情。"
    filtered_noop_count: int = 0


ProactiveReason = Literal[
    "TIME",
    "ANOMALY",
    "CONTINUATION",
    "OPPORTUNITY",
    "GOAL_DEVIATION",
    "RESULT",
    "UNDERSTANDING",
]

ProactiveDomain = Literal[
    "PLATFORM",
    "PRODUCT",
    "COMPETITION",
    "TRAFFIC",
    "PROFIT",
    "CUSTOMER",
    "REVIEW",
    "STORE_GROWTH",
]

ProactiveOwner = Literal["ai", "boss", "shared"]
ProactiveStatus = Literal[
    "auto_done",
    "need_you",
    "observing",
    "analyzing",
    "done",
    "no_action",
]


class ProactiveEvent(BaseModel):
    """右栏 AI 主动经营流：六路径是 reason，不是六个固定模块。"""

    id: str
    reason: ProactiveReason
    domain: ProactiveDomain = "PRODUCT"
    occurred_at: Optional[datetime] = None
    summary: str
    object_name: str = ""
    why_now: str = ""
    finding: str = ""
    decision: str = ""
    action: str = ""
    owner: ProactiveOwner = "ai"
    status: ProactiveStatus = "observing"
    human_required: bool = False
    business_impact: str = ""
    next_check: str = ""
    related_workthread: Optional[str] = None
    label: str = ""  # 展示用：时间节点 / 异常发现 …
    domain_label: str = ""  # 展示用：商品 / 流量投放 …
