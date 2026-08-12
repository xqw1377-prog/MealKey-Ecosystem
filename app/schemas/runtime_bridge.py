"""Runtime Bridge bridge contracts.

MealKey 保留业务真相与仲裁；Runtime Bridge 只承担 Agent Harness。
这一层定义最小桥接请求/响应，用于 Golden Path POC。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.content_engine import AnalysisNodeKey, OperatingReason
from app.schemas.domain_playbook import DomainKey
from app.schemas.runtime import RuntimeState
from app.schemas.runtime_event import CandidateODOEnvelope
from app.schemas.runtime_objects import BusinessEventObject, MerchantContextItem, StoreStateSnapshot


class RuntimeBridgeRunRequest(BaseModel):
    """MealKey -> Runtime Bridge Harness 的最小桥接输入。"""

    store_state: StoreStateSnapshot
    business_event: BusinessEventObject
    merchant_context: list[MerchantContextItem] = Field(default_factory=list)
    goal_text: str = ""
    question: str = ""
    trigger_reason: OperatingReason = "ANOMALY"
    runtime_state: Optional[RuntimeState] = None
    analysis_node: Optional[AnalysisNodeKey] = None
    preferred_skills: list[DomainKey] = Field(default_factory=list)
    system_mode: Literal["operating", "safe"] = "operating"


class RuntimeBridgeSkillExecution(BaseModel):
    """一次 Skill 执行的可追溯摘要。"""

    skill_key: DomainKey
    skill_name: str
    selected_because: str = ""
    dependencies: list[DomainKey] = Field(default_factory=list)
    findings_count: int = 0
    candidate_actions_count: int = 0
    recommended_next_step: str = ""
    blocking_reasons: list[str] = Field(default_factory=list)


class RuntimeBridgeRunResult(BaseModel):
    """Runtime Bridge POC 输出：Skill 轨迹 + Candidate ODO。"""

    lead_agent: str = "mealkey_lead_agent"
    run_mode: str = "golden_path_poc"
    selected_skills: list[DomainKey] = Field(default_factory=list)
    skill_executions: list[RuntimeBridgeSkillExecution] = Field(default_factory=list)
    candidate_odos: list[CandidateODOEnvelope] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
