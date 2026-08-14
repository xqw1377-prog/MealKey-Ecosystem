"""Operating Demand Library：100 条经营契约，不是 100 个按钮。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.operating_demands.catalog import DEMANDS, coverage_counts
from app.services.operating_demands.models import OperatingDemand
from app.services.operating_demands.playbooks import run_playbook
from app.services.operating_demands.router import match_demand

router = APIRouter()


def _public(item: OperatingDemand) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "question": item.question,
        "loop": item.loop,
        "coverage": item.coverage,
        "family": item.family,
        "execution": item.execution,
        "metric": item.metric,
        "window_hours": item.window_hours,
        "playbook": list(item.playbook),
        "blockers": list(item.blockers),
        "guardrail": item.guardrail,
    }


@router.get("/operating-demands")
def list_operating_demands():
    counts = coverage_counts()
    return {
        "version": "operating-demand-library-v1",
        "principle": "100个经营问题 → 1个AI店长，不要100个入口",
        "counts": {
            "total": len(DEMANDS),
            "loop_A": counts["A"],
            "loop_B": counts["B"],
            "loop_C": counts["C"],
            "green": counts["green"],
            "yellow": counts["yellow"],
            "red": counts["red"],
        },
        "items": [_public(item) for item in DEMANDS],
    }


@router.get("/operating-demands/{demand_id}")
def get_operating_demand(demand_id: int):
    item = next((row for row in DEMANDS if row.id == demand_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="demand not found")
    verdict = run_playbook(item, {})
    return {"demand": _public(item), "idle_verdict": verdict.as_dict()}


@router.post("/operating-demands/match")
def match_operating_demand(payload: dict):
    question = str(payload.get("question") or "")
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    demand = match_demand(question)
    if demand is None:
        return {"matched": False, "question": question}
    verdict = run_playbook(demand, facts)
    return {"matched": True, "question": question, **verdict.as_dict()}
