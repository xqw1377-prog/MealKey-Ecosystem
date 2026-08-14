"""外部案例禁止直接写入 Strategy Memory。"""
from __future__ import annotations

from app.schemas.operating_case import OperatingCase


class CaseGraduationError(ValueError):
    pass


def assert_case_cannot_enter_strategy_memory(case: OperatingCase) -> None:
    level = case.distillation.evidence_level
    source = case.source.source_reliability
    if source != "mealkey_experiment" or level != "L3":
        raise CaseGraduationError(
            "外部资料只能进入 Case Library，不能直接进入 Strategy Memory。"
            "改变下一次决策权重的必须是 MealKey 自己的 Action→Result。"
        )
    if case.distillation.status == "case_prior_only":
        raise CaseGraduationError("CASE_PRIOR_ONLY 不得晋升 Strategy Memory")


def can_graduate(case: OperatingCase, *, mealkey_experiment_id: str | None) -> bool:
    if not mealkey_experiment_id:
        return False
    try:
        assert_case_cannot_enter_strategy_memory(case)
    except CaseGraduationError:
        return False
    return True
