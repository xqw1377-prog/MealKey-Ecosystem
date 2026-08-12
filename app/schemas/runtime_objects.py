"""Runtime V1 core object contracts.

围绕长期稳定的业务对象建模，而不是围绕 Agent 建表。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.content_engine import OperatingDecisionObject, OperatingDomain, OperatingObjectRef, OperatingReason


class StoreStateSnapshot(BaseModel):
    store_id: str
    snapshot_at: datetime
    business: dict[str, Any] = Field(default_factory=dict)
    funnel: dict[str, Any] = Field(default_factory=dict)
    profit: dict[str, Any] = Field(default_factory=dict)
    platform: dict[str, Any] = Field(default_factory=dict)
    market: dict[str, Any] = Field(default_factory=dict)
    customer: dict[str, Any] = Field(default_factory=dict)
    active_goal_ids: list[str] = Field(default_factory=list)
    active_work_thread_ids: list[str] = Field(default_factory=list)


class MerchantContextItem(BaseModel):
    id: str = ""
    merchant_id: str = ""
    store_id: str = ""
    key: str
    value_json: dict[str, Any] = Field(default_factory=dict)
    source: str = "user"
    confidence: float = 0.7
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    required_for: list[str] = Field(default_factory=list)
    blocking: str = "none"
    ask_score: Optional[float] = None


class SignalObject(BaseModel):
    id: str
    type: str
    store_id: str
    subject_id: str = ""
    metric: str = ""
    value: Optional[float] = None
    baseline: Optional[float] = None
    occurred_at: datetime


class BusinessEventObject(BaseModel):
    event_id: str
    event_type: str
    domain: OperatingDomain
    store_id: str
    subject: OperatingObjectRef = Field(default_factory=OperatingObjectRef)
    severity: str = "medium"
    observation: dict[str, Any] = Field(default_factory=dict)
    detected_at: Optional[datetime] = None
    status: str = "OPEN"


class WorkThreadObject(BaseModel):
    id: str
    type: str = ""
    title: str
    goal: dict[str, Any] = Field(default_factory=dict)
    initial_state: dict[str, Any] = Field(default_factory=dict)
    current_state: dict[str, Any] = Field(default_factory=dict)
    phase: str = ""
    status: str = "ACTIVE"
    next_checkpoint_at: Optional[datetime] = None
    human_attention: bool = False


class ActionObject(BaseModel):
    id: str
    work_thread_id: str = ""
    odo_id: str = ""
    type: str
    executor: str = "AI"
    platform: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    permission_basis: dict[str, Any] = Field(default_factory=dict)
    status: str = "READY"
    executed_at: Optional[datetime] = None


class ExperimentObject(BaseModel):
    experiment_id: str
    work_thread_id: str = ""
    action_id: str = ""
    type: str = ""
    subject: str = ""
    baseline: dict[str, Any] = Field(default_factory=dict)
    success_metric: dict[str, Any] = Field(default_factory=dict)
    guardrails: dict[str, Any] = Field(default_factory=dict)
    window: dict[str, Any] = Field(default_factory=dict)
    status: str = "RUNNING"


class ResultObject(BaseModel):
    experiment_id: str
    outcome: str = "UNKNOWN"
    primary_result: dict[str, Any] = Field(default_factory=dict)
    secondary_results: dict[str, Any] = Field(default_factory=dict)
    guardrails_passed: bool = True
    confidence: float = 0.7
    decision: str = ""


class StrategyMemoryObject(BaseModel):
    pattern: dict[str, Any] = Field(default_factory=dict)
    strategy: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    scope: str = "STORE"
    confidence: float = 0.7


class RuntimeChainObject(BaseModel):
    store_state: Optional[StoreStateSnapshot] = None
    merchant_context: list[MerchantContextItem] = Field(default_factory=list)
    signals: list[SignalObject] = Field(default_factory=list)
    events: list[BusinessEventObject] = Field(default_factory=list)
    odos: list[OperatingDecisionObject] = Field(default_factory=list)
    work_threads: list[WorkThreadObject] = Field(default_factory=list)
    actions: list[ActionObject] = Field(default_factory=list)
    experiments: list[ExperimentObject] = Field(default_factory=list)
    results: list[ResultObject] = Field(default_factory=list)
    memories: list[StrategyMemoryObject] = Field(default_factory=list)
