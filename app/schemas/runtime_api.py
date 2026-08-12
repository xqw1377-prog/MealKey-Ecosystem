"""Runtime V1 API contracts."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.runtime import DailyOperatingPlan, RuntimeState


class RuntimeStoreInfo(BaseModel):
    store_id: str
    store_name: str
    runtime_state: RuntimeState


class RuntimeLeftPanel(BaseModel):
    need_you: list[dict[str, Any]] = Field(default_factory=list)
    active: list[dict[str, Any]] = Field(default_factory=list)
    waiting: list[dict[str, Any]] = Field(default_factory=list)
    completed: list[dict[str, Any]] = Field(default_factory=list)
    opportunities: list[dict[str, Any]] = Field(default_factory=list)
    active_goal: Optional[dict[str, Any]] = None
    threads: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeCenterPanel(BaseModel):
    active_thread_id: Optional[str] = None
    guide: dict[str, Any] = Field(default_factory=dict)
    principle: str = ""


class RuntimeRightPanel(BaseModel):
    proactive_feed: list[dict[str, Any]] = Field(default_factory=list)
    filtered_count: int = 0


class RuntimeMetaPanel(BaseModel):
    candidates_total: int = 0
    filtered_noop_count: int = 0
    mealkey_score: Optional[dict[str, Any]] = None
    operation_score: Optional[dict[str, Any]] = None
    runtime_bridge: Optional[dict[str, Any]] = None


class WorkspaceRuntimeResponse(BaseModel):
    store: RuntimeStoreInfo
    left: RuntimeLeftPanel
    center: RuntimeCenterPanel
    right: RuntimeRightPanel
    meta: RuntimeMetaPanel


class DailyPlanResponse(BaseModel):
    plan: DailyOperatingPlan
    runtime_state: RuntimeState
