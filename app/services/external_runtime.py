"""External Runtime Contract — 外部 Agent Runtime 的统一接口。

支持:
- LocalRuntime: MealKey 自带的 chief_agent (默认)
- DeepSeekHarnessRuntime: dsh Shadow POC (只读,不写)
- DeerFlowRuntime: DeerFlow (如果还能跑)
- 未来其他 runtime

核心原则:
- dsh 可以推理,但没有经营主权
- 所有 runtime 返回 Candidate ODO,由 MealKey POIE/Profit Gate 决定是否执行
- Shadow Mode: dsh 的输出只用于对比,不影响生产决策
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from app.services.agent_event_log import AgentEventLog


@dataclass
class RuntimeRequest:
    """统一请求:给 runtime 的经营上下文 + 目标。"""
    store_id: str
    work_thread_id: str = ""
    objective: str = ""  # "诊断为什么订单下降"
    question: str = ""   # 原始问题
    context_projection: dict[str, Any] = field(default_factory=dict)  # StoreState 快照
    allowed_skills: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    token_budget: int = 8000
    runtime_policy: str = "read_only"  # read_only / shadow / full


@dataclass
class RuntimeCandidateResult:
    """统一响应:runtime 返回的候选决策。"""
    status: str = "pending"  # pending / completed / failed / timeout
    candidate_odos: list[dict[str, Any]] = field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    unknown_facts: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    trace_ref: str = ""  # AgentEvent session_id
    token_usage: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    errors: list[str] = field(default_factory=list)
    runtime: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_odos": self.candidate_odos,
            "proposed_actions": self.proposed_actions,
            "selected_skills": self.selected_skills,
            "unknown_facts": self.unknown_facts,
            "assumptions": self.assumptions,
            "evidence_refs": self.evidence_refs,
            "trace_ref": self.trace_ref,
            "token_usage": self.token_usage,
            "cost": self.cost,
            "latency_ms": self.latency_ms,
            "errors": self.errors,
            "runtime": self.runtime,
        }


class ExternalRuntime(ABC):
    """外部 Runtime 基类。"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def execute_candidate(self, db, request: RuntimeRequest) -> RuntimeCandidateResult:
        """执行推理,返回候选决策。"""
        ...


class LocalRuntime(ExternalRuntime):
    """本地 runtime — MealKey 自带的 chief_agent。"""

    @property
    def name(self) -> str:
        return "local"

    def execute_candidate(self, db, request: RuntimeRequest) -> RuntimeCandidateResult:
        """用现有 chief_agent 执行。"""
        event_log = AgentEventLog(db, store_id=request.store_id, runtime="local")
        event_log.turn_start(question=request.question, context_summary=request.objective)

        try:
            from app.services.store_state import build_store_state
            state = build_store_state(db, request.store_id, days=7)

            result = RuntimeCandidateResult(
                status="completed",
                runtime="local",
                trace_ref=event_log.session_id,
            )

            if state:
                # 从 StoreState 提取候选 ODO
                if state.primary_problem:
                    result.candidate_odos.append({
                        "type": state.primary_problem.type,
                        "confidence": state.primary_problem.confidence,
                        "source": "local_diagnosis",
                    })
                result.unknown_facts = state.profit.missing_blocks if state.profit else []

            event_log.turn_end(
                conclusion=f"intent={intent}, generated {len(result.candidate_odos)} candidates",
                actions=[o["type"] for o in result.candidate_odos],
            )

        except Exception as exc:
            event_log.error(message=str(exc))
            result = RuntimeCandidateResult(
                status="failed",
                errors=[str(exc)],
                runtime="local",
                trace_ref=event_log.session_id,
            )

        return result


class DeepSeekHarnessRuntime(ExternalRuntime):
    """DeepSeek Harness Shadow Runtime — 只读 POC。

    通过 Python SDK 驱动 dsh subprocess (如果可用)。
    如果 dsh 不可用,优雅降级。
    """

    @property
    def name(self) -> str:
        return "dsh"

    def execute_candidate(self, db, request: RuntimeRequest) -> RuntimeCandidateResult:
        """驱动 dsh 执行推理(Shadow Mode)。

        当前阶段: dsh 不可用 → 返回 not_implemented。
        未来: 通过 dsh Python SDK 驱动。
        """
        event_log = AgentEventLog(db, store_id=request.store_id, runtime="dsh")

        try:
            # 尝试 import dsh SDK
            try:
                from deepseek_harness import DeepSeekHarness  # type: ignore[import-not-found]
                dsh_available = True
            except ImportError:
                dsh_available = False

            if not dsh_available:
                event_log._emit("dsh_unavailable", payload={"reason": "deepseek_harness SDK not installed"})
                return RuntimeCandidateResult(
                    status="not_implemented",
                    runtime="dsh",
                    errors=["deepseek_harness SDK not installed — install with: pip install deepseek-harness-sdk"],
                    trace_ref=event_log.session_id,
                )

            # TODO: 当 SDK 可用时,构造 prompt 并驱动 dsh
            # h = DeepSeekHarness(...)
            # result = h.run(prompt=...)
            event_log._emit("dsh_todo", payload={"reason": "SDK integration pending"})
            return RuntimeCandidateResult(
                status="pending_integration",
                runtime="dsh",
                trace_ref=event_log.session_id,
            )

        except Exception as exc:
            event_log.error(message=str(exc))
            return RuntimeCandidateResult(
                status="failed",
                errors=[str(exc)],
                runtime="dsh",
                trace_ref=event_log.session_id,
            )


# ── Runtime Registry ──

_RUNTIMES: dict[str, ExternalRuntime] = {
    "local": LocalRuntime(),
    "dsh": DeepSeekHarnessRuntime(),
}


def get_runtime(name: str) -> ExternalRuntime:
    return _RUNTIMES.get(name, _RUNTIMES["local"])


def list_runtimes() -> list[str]:
    return list(_RUNTIMES.keys())


def execute_shadow_comparison(
    db,
    request: RuntimeRequest,
    runtimes: list[str] | None = None,
) -> dict[str, RuntimeCandidateResult]:
    """Shadow Mode: 同时用多个 runtime 执行,对比结果。

    生产决策仍然由 LocalRuntime 的输出驱动;
    其他 runtime 的输出只用于对比分析。
    """
    runtimes = runtimes or ["local", "dsh"]
    results: dict[str, RuntimeCandidateResult] = {}

    for rt_name in runtimes:
        rt = get_runtime(rt_name)
        try:
            results[rt_name] = rt.execute_candidate(db, request)
        except Exception as exc:
            results[rt_name] = RuntimeCandidateResult(
                status="failed",
                errors=[str(exc)],
                runtime=rt_name,
            )

    return results
