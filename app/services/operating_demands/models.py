"""经营需求契约：一个问题从 Trigger 走到 Result，不是一个功能入口。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OperatingDemand:
    id: int
    code: str
    question: str
    loop: str  # A 全自动 / B 审批 / C 人机
    coverage: str  # green 骨架完整 / yellow 判断有最后一公里未通 / red 实体缺口
    family: str
    keywords: tuple[str, ...]
    playbook: tuple[str, ...]
    actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    forbidden_diagnosis: tuple[str, ...]
    execution: str  # AUTO / ASK_APPROVAL / HUMAN_TASK
    metric: str
    window_hours: int
    truth: tuple[str, ...]
    blockers: tuple[str, ...] = ()
    guardrail: str = ""


@dataclass
class DemandVerdict:
    demand: OperatingDemand
    diagnosis: str
    action: str
    execution: str
    missing_truth: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    why_not: list[str] = field(default_factory=list)
    blocked: bool = False

    def as_dict(self) -> dict:
        d = self.demand
        return {
            "id": d.id,
            "code": d.code,
            "question": d.question,
            "loop": d.loop,
            "coverage": d.coverage,
            "family": d.family,
            "diagnosis": self.diagnosis,
            "action": self.action,
            "execution": self.execution,
            "forbidden_actions": list(d.forbidden_actions),
            "forbidden_diagnosis": list(d.forbidden_diagnosis),
            "metric": d.metric,
            "window_hours": d.window_hours,
            "guardrail": d.guardrail,
            "missing_truth": self.missing_truth,
            "evidence": self.evidence,
            "why_not": self.why_not,
            "blocked": self.blocked,
            "blockers": list(d.blockers),
        }
