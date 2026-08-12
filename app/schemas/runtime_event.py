"""Runtime V1 event contracts.

把 Runtime State / Trigger / Event / Candidate ODO / Arbitration Queue
收束成可直接落库、走接口、做调试台的统一结构。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.content_engine import OperatingDecisionObject, OperatingDomain, OperatingObjectRef, OperatingReason
from app.schemas.runtime import AnalysisNodeKey, RuntimeState


class RuntimeSignalEnvelope(BaseModel):
    id: str
    store_id: str
    state: RuntimeState
    node: AnalysisNodeKey
    source: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime


class RuntimeEventEnvelope(BaseModel):
    id: str
    store_id: str
    state: RuntimeState
    node: AnalysisNodeKey
    trigger_reason: OperatingReason
    domain: OperatingDomain
    subject: OperatingObjectRef = Field(default_factory=OperatingObjectRef)
    title: str
    detail: str = ""
    evidence: list[str] = Field(default_factory=list)
    event_payload: dict[str, Any] = Field(default_factory=dict)
    priority_score: float = 0.0
    status: str = "open"
    source_odo_id: str = ""
    occurred_at: datetime
    resolved_at: Optional[datetime] = None


class CandidateODOEnvelope(BaseModel):
    id: str
    state: RuntimeState
    node: AnalysisNodeKey
    trigger_reason: OperatingReason
    domain: OperatingDomain
    odo: OperatingDecisionObject
    generated_at: datetime


class ArbitrationQueueEntry(BaseModel):
    candidate_odo_id: str
    runtime_state: RuntimeState
    priority_score: float = 0.0
    decision: str = "OBSERVE"
    interrupt_owner: bool = False
    guide_projection_id: Optional[str] = None
    source_event_id: Optional[str] = None


class RuntimeQueueResponse(BaseModel):
    store_id: str
    runtime_state: RuntimeState
    items: list[ArbitrationQueueEntry] = Field(default_factory=list)


class RuntimeFeedResponse(BaseModel):
    store_id: str
    runtime_state: RuntimeState
    events: list[RuntimeEventEnvelope] = Field(default_factory=list)
