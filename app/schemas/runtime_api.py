"""Runtime V1 API contracts."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.runtime import DailyOperatingPlan, RuntimeState


class RuntimeStoreInfo(BaseModel):
    store_id: str
    store_name: str
    runtime_state: RuntimeState
    operating_phase: str = ""
    phase_label: str = ""


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
    decision_flow: dict[str, Any] = Field(default_factory=dict)
    loop: Optional[dict[str, Any]] = None


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
    # canonical brief：workspace 是首页唯一权威数据源。
    # 前端不再单独 fetch manager_brief（避免两次 POIE 执行互相漂移），
    # home 路径的 state.managerBrief 直接取自这里。
    brief: Optional[dict[str, Any]] = None


class DailyPlanResponse(BaseModel):
    plan: DailyOperatingPlan
    runtime_state: RuntimeState
