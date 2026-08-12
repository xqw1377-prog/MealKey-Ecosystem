"""POIE 核心对象：MealKey Decision System 的数据契约。

Signal → Event → Insight → (Goal) → WorkThread → Action → Experiment → Memory
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.arbiter import ArbiterState, InterruptReason, OpsQueueBrief

TriggerType = Literal[
    "time",
    "anomaly",
    "history",
    "opportunity",
    "goal",
    "result",
    "intent",
    "understanding",
]

PermissionLevel = Literal[0, 1, 2, 3]
# 0 自动 / 1 可撤销自动 / 2 需确认 / 3 明确授权


class Signal(BaseModel):
    """原始信号：平台/商圈/用户/天气等未解释输入。"""

    id: str
    store_id: str
    source: str
    kind: str
    payload: dict = Field(default_factory=dict)
    observed_at: datetime


class Event(BaseModel):
    """经营事件：Signal 收敛后的可处理事实。"""

    id: str
    store_id: str
    event_type: str
    title: str
    detail: str = ""
    severity: str = "medium"
    confidence: float = 0.7
    trigger: TriggerType = "anomaly"
    fingerprint: Optional[str] = None


class Insight(BaseModel):
    """AI 对 Event 的诊断结论（先于打扰老板）。"""

    id: str
    event_id: Optional[str] = None
    judgment: str
    root_cause: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    already_did: str = ""


class Goal(BaseModel):
    """老板想达成的结果。"""

    id: str
    store_id: str
    raw_text: str
    metric: str = "custom"
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    forecast_value: Optional[float] = None
    gap: Optional[float] = None
    on_track: Optional[bool] = None


class WorkThread(BaseModel):
    """长期经营事项：不是 task 列表项。"""

    id: str
    store_id: str
    title: str
    goal_id: Optional[str] = None
    stage: str = ""
    done: list[str] = Field(default_factory=list)
    doing: list[str] = Field(default_factory=list)
    next_step: str = ""
    next_checkpoint: Optional[datetime] = None
    blocked_by: str = ""
    needs_owner: bool = False


class Action(BaseModel):
    """候选/已决策的经营动作。"""

    id: str
    title: str
    action_type: str = ""
    trigger: TriggerType = "anomaly"
    insight_id: Optional[str] = None
    work_thread_id: Optional[str] = None
    recommendation_id: Optional[str] = None
    risk_level: PermissionLevel = 2
    reversibility: Literal["easy", "medium", "hard"] = "medium"
    financial_limit: Optional[float] = None
    permission_required: bool = True


class ExperimentRef(BaseModel):
    """动作验证窗口。"""

    id: str
    action_id: Optional[str] = None
    metric: str = ""
    window_hours: int = 48
    status: str = "pending"
    can_evaluate: bool = False
    result: Optional[str] = None
    lift_pct: Optional[float] = None


class MemoryItem(BaseModel):
    """策略记忆：Result → 可复用经验。"""

    id: str
    lesson: str
    result: str = "unknown"
    reuse_when: str = ""
    avoid_when: str = ""
    lift_pct: Optional[float] = None


class ArbitrationScore(BaseModel):
    """统一评分：任何 Candidate 必须过仲裁。"""

    business_impact: float = 0.5
    urgency: float = 0.5
    confidence: float = 0.7
    goal_relevance: float = 0.5
    need_for_human: float = 0.5
    interruption_cost: float = 0.55
    priority: float = 0.0

    def compute(self) -> float:
        cost = max(0.15, self.interruption_cost)
        raw = (
            self.business_impact
            * self.urgency
            * max(0.2, self.confidence)
            * max(0.15, self.goal_relevance)
            * max(0.05, self.need_for_human)
        ) / cost
        self.priority = round(min(100.0, max(0.0, raw * 100)), 2)
        return self.priority


class CandidateAction(BaseModel):
    """Trigger 产物：进入仲裁前的候选。"""

    id: str
    title: str
    trigger: TriggerType
    insight: str = ""
    why_now: str = ""
    already_did: str = ""
    success_metric: str = ""
    action: Optional[Action] = None
    score: ArbitrationScore = Field(default_factory=ArbitrationScore)
    suggested_state: ArbiterState = "noop"
    interrupt_reason: InterruptReason = "anomaly"


class PoieRunResult(BaseModel):
    """一次 POIE 运行的输出：投影到首页队列。"""

    store_id: str
    generated_at: datetime
    principle: str = (
        "系统负责发现所有事情，AI负责筛掉绝大多数事情，老板只处理必须由老板处理的事情。"
    )
    candidates_total: int = 0
    filtered_noop_count: int = 0
    ops_queue: OpsQueueBrief
    active_goals: list[Goal] = Field(default_factory=list)
    work_threads: list[WorkThread] = Field(default_factory=list)
