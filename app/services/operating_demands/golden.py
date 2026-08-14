"""100 Demand Golden Set 骨架：每个需求至少 1 条 smoke，关键需求手写经营 Case。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.operating_demands.catalog import DEMANDS, by_code
from app.services.operating_demands.models import OperatingDemand


@dataclass(frozen=True)
class GoldenCase:
    demand_code: str
    question: str
    facts: dict[str, Any]
    expected_diagnosis: str
    forbidden_diagnosis: tuple[str, ...]
    expected_action: str
    forbidden_action: tuple[str, ...]
    execution: str
    metric: str
    window_hours: int
    guardrail: str = ""


def smoke_cases() -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    for demand in DEMANDS:
        cases.append(
            GoldenCase(
                demand_code=demand.code,
                question=demand.question,
                facts={},
                expected_diagnosis="",
                forbidden_diagnosis=demand.forbidden_diagnosis,
                expected_action="",
                forbidden_action=demand.forbidden_actions,
                execution=demand.execution,
                metric=demand.metric,
                window_hours=demand.window_hours,
                guardrail=demand.guardrail,
            )
        )
    return cases


def featured_cases() -> list[GoldenCase]:
    order_drop = by_code("ORDER_DROP")
    next_best = by_code("NEXT_BEST")
    follow = by_code("FOLLOW_PRICE")
    return [
        GoldenCase(
            demand_code="ORDER_DROP",
            question="今天怎么没单了？",
            facts={"exposure": 3.0, "ctr": -18.0, "cvr": 0.5},
            expected_diagnosis="点击竞争力下降",
            forbidden_diagnosis=("平台限流", "怪天气"),
            expected_action="检查主图/首屏",
            forbidden_action=("立即大幅降价",),
            execution=order_drop.execution,
            metric="orders",
            window_hours=48,
            guardrail="CVR不得下降>5%",
        ),
        GoldenCase(
            demand_code="NEXT_BEST",
            question="今天所有问题里，我现在只该做哪一件事？",
            facts={"ctr": -18.0, "cvr": -1.0, "profit": -2.0},
            expected_diagnosis="点击竞争力变差",
            forbidden_diagnosis=("所有指标都要先看",),
            expected_action="检查主图/首屏",
            forbidden_action=("一次做二十件事",),
            execution=next_best.execution,
            metric=next_best.metric,
            window_hours=next_best.window_hours,
        ),
        GoldenCase(
            demand_code="FOLLOW_PRICE",
            question="对手降价了，我们到底要不要跟？",
            facts={"rival_price_delta": -12.0, "profit_gate_passed": False, "unit_profit": 1.2},
            expected_diagnosis="利润门禁",
            forbidden_diagnosis=("不跟就会没单",),
            expected_action="过利润门禁后再决定是否跟价",
            forbidden_action=("立即跟价",),
            execution=follow.execution,
            metric=follow.metric,
            window_hours=follow.window_hours,
        ),
    ]


def demand_of(case: GoldenCase) -> OperatingDemand:
    return by_code(case.demand_code)
