"""CaseScore 确定性排序。只改变候选先验，不把案例正文推给老板。"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.schemas.operating_case import CaseScoreResult, OperatingCase
from app.services.oci.ingest import corpus_dir

_FAMILY_HINTS = {
    "ads": ("ADS_ROI", "ADS_EFFICIENCY", "BUDGET_UP_DOWN", "BUDGET_BURN"),
    "campaign": ("JOIN_CAMPAIGN", "CAMPAIGN_DECISION", "CAMPAIGN", "STACK_LOSS"),
    "product": ("ORDER_DROP", "HERO_CTR_DROP", "CHANGE_IMAGE", "TRAFFIC", "PRODUCT", "MENU", "MENU_STRUCTURE", "LIMIT_TRAFFIC_SKU"),
    "ops": ("OPERATION_ABNORMAL",),
    "fulfillment": ("SLOW_COOK", "SPILL", "CAPACITY_PEAK", "FULFILLMENT"),
    "review": ("REPEAT_ROOT_CAUSE", "RATING_AND_SERVICE"),
    "profit": ("STORE_LOSS", "PROFIT_DROP", "UNIT_PROFIT", "SKU_PROFIT", "PROFIT"),
    "repurchase": ("REPURCHASE", "CUSTOMER"),
    "chain": ("COPY_STRATEGY", "CHAIN_OPERATIONS"),
}


def _hints_for_demand(demand_code: str, family: str = "") -> set[str]:
    tokens = {demand_code, family, (family or "").upper()}
    family_key = (family or "").lower()
    for key, group in _FAMILY_HINTS.items():
        if demand_code in group or family in group or family_key == key:
            tokens.update(group)
    return {item for item in tokens if item}


@lru_cache(maxsize=1)
def load_file_cases() -> tuple[OperatingCase, ...]:
    folder = corpus_dir()
    cases: list[OperatingCase] = []
    if not folder.exists():
        return tuple()
    for path in sorted(folder.glob("case_*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            cases.append(OperatingCase.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return tuple(cases)


def reload_file_cases() -> tuple[OperatingCase, ...]:
    load_file_cases.cache_clear()
    return load_file_cases()


def _allowed_as_prior(case: OperatingCase) -> bool:
    if case.distillation.evidence_level not in {"L1", "L2", "L3"}:
        return False
    if not (case.source.source_excerpt or "").strip():
        return False
    name = f"{case.source.source_name} {case.source.source_url or ''}".lower()
    if "yelp" in name:
        return False
    return True


def _score(case: OperatingCase, *, demand_code: str, family: str, question: str) -> CaseScoreResult:
    hints = _hints_for_demand(demand_code, family)
    code = (case.demand_code or "").upper()
    domain = (case.incident.domain or "").upper()
    problem = (case.incident.problem_type or "").upper()
    metric_hit = 1.0 if (code in hints or domain in hints or any(h in problem for h in hints)) else 0.25
    if question:
        blob = f"{case.analysis.hypothesis} {case.distillation.strategy_principle} {case.incident.trigger}"
        overlap = sum(1 for token in ("曝光", "CTR", "主图", "活动", "广告", "评价", "履约", "利润") if token in question and token in blob)
        metric_hit = min(1.0, metric_hit + 0.1 * overlap)
    evidence = {"L1": 0.45, "L2": 0.7, "L3": 1.0}.get(case.distillation.evidence_level, 0.3)
    if case.source.source_reliability == "vendor_material":
        evidence *= 0.7
    if case.distillation.source_conflict_flag:
        evidence *= 0.5
    confidence = float(case.trust.confidence or 0.2)
    transfer = 0.6 if case.transferability.applicable_when else 0.4
    freshness = 0.7
    context = 0.5
    score = context * evidence * metric_hit * freshness * transfer * max(confidence, 0.08)
    return CaseScoreResult(
        case_id=case.case_id,
        score=round(score, 4),
        context_similarity=context,
        evidence_quality=round(evidence, 3),
        metric_relevance=round(metric_hit, 3),
        freshness=freshness,
        transferability=transfer,
        outcome_confidence=confidence,
        case=case,
    )


def retrieve_case_priors(
    *,
    demand_code: str,
    family: str = "",
    question: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    scored = [
        _score(case, demand_code=demand_code, family=family, question=question)
        for case in load_file_cases()
        if _allowed_as_prior(case)
    ]
    scored.sort(key=lambda item: item.score, reverse=True)
    out: list[dict[str, Any]] = []
    for item in scored[: max(1, min(limit, 5))]:
        case = item.case
        if case is None:
            continue
        out.append(
            {
                "case_id": case.case_id,
                "score": item.score,
                "principle": case.distillation.strategy_principle,
                "action_pattern": case.distillation.candidate_action_pattern,
                "forbidden_claim": case.result.forbidden_claim or case.distillation.status,
                "source_conflict": case.distillation.source_conflict_flag,
                "confidence": case.trust.confidence,
                "status": "CASE_PRIOR_ONLY",
                "evidence_level": case.distillation.evidence_level,
            }
        )
    return out


def prior_facts_for_demand(demand_code: str, family: str = "", question: str = "") -> dict[str, Any]:
    priors = retrieve_case_priors(demand_code=demand_code, family=family, question=question)
    return {
        "case_priors": priors,
        "case_prior_conflict": any(item.get("source_conflict") for item in priors),
        "case_prior_forbids_price_cut": any("降价" in (item.get("forbidden_claim") or "") for item in priors),
    }
