"""MealKey <-> Runtime Bridge 最小桥接层。

目标不是把 MealKey 改造成 Runtime Bridge，而是：
1. MealKey 继续维护 StoreState / Event / ODO / POIE 等业务真相
2. Runtime Bridge 只承担 Lead Agent / Skills / Sandbox / Tools 等 Harness

V1 POC 只打通：
BusinessEvent -> 选择 Skills -> 执行 Domain Analysis -> 回收 Candidate ODO
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from app.schemas.runtime_bridge import RuntimeBridgeRunRequest, RuntimeBridgeRunResult, RuntimeBridgeSkillExecution
from app.schemas.domain_playbook import DomainKey, DomainSkillResult, check_domain_dependency
from app.schemas.runtime_event import CandidateODOEnvelope
from app.services.analysis_pipeline import PipelineContext, run_analysis_pipeline
from app.services.skill_registry import get_skill, select_skills_for_event, select_skills_for_question

_ODO_DOMAIN_MAP = {
    "product": "PRODUCT",
    "traffic": "TRAFFIC",
    "profit": "PROFIT",
    "competition": "COMPETITION",
}


def _dedupe_domain_keys(keys: list[str]) -> list[DomainKey]:
    seen: set[str] = set()
    ordered: list[DomainKey] = []
    for key in keys:
        if key not in {"product", "traffic", "profit", "competition"}:
            continue
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)  # type: ignore[arg-type]
    return ordered


def _metric_delta_pct(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if abs(value) <= 1.5:
        return value * 100
    return value


def _merchant_numeric_context(request: RuntimeBridgeRunRequest, *keys: str) -> float | None:
    for item in request.merchant_context:
        if item.key not in keys:
            continue
        payload = item.value_json or {}
        for field in ("rate", "value", "daily_cny", "limit", "margin"):
            raw = payload.get(field)
            if isinstance(raw, (int, float)):
                return float(raw)
    return None


def _build_item_snapshots(request: RuntimeBridgeRunRequest) -> list[Any]:
    obs = request.business_event.observation or {}
    raw_items = obs.get("item_snapshots") or []
    if raw_items:
        return [SimpleNamespace(**item) for item in raw_items if isinstance(item, dict)]

    subject = request.business_event.subject
    if subject.type != "sku":
        return []

    ctr = obs.get("ctr") or request.store_state.funnel.get("ctr")
    cvr = obs.get("cvr") or request.store_state.funnel.get("cvr")
    snapshot = SimpleNamespace(
        item_id=subject.id,
        name=subject.name,
        role=obs.get("role", "Hero Product"),
        observe_ctr=ctr,
        baseline_ctr=obs.get("ctr_baseline"),
        ctr_delta_pct=_metric_delta_pct(obs.get("change") or obs.get("delta_pct")),
        observe_cvr=cvr,
        baseline_cvr=obs.get("cvr_baseline"),
        cvr_delta_pct=_metric_delta_pct(obs.get("cvr_change") or obs.get("cvr_delta_pct")),
        observe_orders=obs.get("orders", 0),
        order_share_pct=obs.get("order_share_pct", 0),
        price=obs.get("price"),
    )
    return [snapshot]


def _build_competition_changes(request: RuntimeBridgeRunRequest) -> list[Any]:
    obs = request.business_event.observation or {}
    raw = obs.get("competition_changes") or []
    return [SimpleNamespace(**item) for item in raw if isinstance(item, dict)]


def _build_skill_kwargs(
    skill_key: DomainKey,
    request: RuntimeBridgeRunRequest,
    prior_results: dict[DomainKey, DomainSkillResult],
) -> dict[str, Any]:
    store_state = request.store_state
    obs = request.business_event.observation or {}
    take_home_rate = store_state.profit.get("take_home_rate")
    contribution_margin = store_state.profit.get("contribution_margin")
    profit_floor = _merchant_numeric_context(
        request,
        "profit_floor",
        "profit_floor_rate",
        "minimum_margin",
        "minimum_margin_rate",
    ) or 0.58

    if skill_key == "product":
        return {
            "item_snapshots": _build_item_snapshots(request),
            "ctr_delta": _metric_delta_pct(obs.get("change") or obs.get("ctr_delta_pct")),
            "cvr_delta": _metric_delta_pct(obs.get("cvr_change") or obs.get("cvr_delta_pct")),
            "store_rating": store_state.platform.get("rating"),
        }
    if skill_key == "competition":
        return {
            "competition_changes": _build_competition_changes(request),
            "competition_score": obs.get("competition_score"),
        }
    if skill_key == "profit":
        return {
            "take_home_rate": take_home_rate,
            "take_home_rate_delta": _metric_delta_pct(obs.get("take_home_rate_delta")),
            "contribution_margin": contribution_margin,
            "profit_floor": profit_floor,
            "gmv_delta": _metric_delta_pct(obs.get("gmv_delta")),
            "ads_spend_delta": _metric_delta_pct(obs.get("ads_spend_delta")),
            "subsidy_delta": _metric_delta_pct(obs.get("subsidy_delta")),
        }
    return {
        "product_result": prior_results.get("product"),
        "ads_spend": store_state.profit.get("ads_spend"),
        "estimated_roi": obs.get("estimated_roi") or obs.get("roi"),
        "cvr": obs.get("cvr") or store_state.funnel.get("cvr"),
        "cvr_baseline": obs.get("cvr_baseline"),
        "take_home_rate": take_home_rate,
        "profit_floor": profit_floor,
        "goal_relevant": bool(request.goal_text),
    }


def _selection_reason(
    skill_key: DomainKey,
    request: RuntimeBridgeRunRequest,
) -> str:
    if skill_key in request.preferred_skills:
        return "老板/系统显式指定"
    if request.business_event.event_type in (get_skill(skill_key).triggers if get_skill(skill_key) else []):
        return f"由事件 {request.business_event.event_type} 直接触发"
    return "作为依赖域补充验证"


def _skill_blockers(
    skill_key: DomainKey,
    result: DomainSkillResult,
    all_results: dict[DomainKey, DomainSkillResult],
) -> list[str]:
    blockers: list[str] = []
    for action in result.candidate_actions:
        allowed, reasons = check_domain_dependency(skill_key, action.action_type, all_results)
        if not allowed:
            blockers.extend(reasons)
    return list(dict.fromkeys(blockers))


def _to_candidate_odo(
    *,
    request: RuntimeBridgeRunRequest,
    skill_key: DomainKey,
    result: DomainSkillResult,
    blockers: list[str],
) -> CandidateODOEnvelope | None:
    if not result.findings and not result.candidate_actions:
        return None

    obs = request.business_event.observation or {}
    subject = request.business_event.subject
    first_action = result.candidate_actions[0] if result.candidate_actions else None
    first_finding = result.findings[0] if result.findings else None
    evidence = list(dict.fromkeys((result.evidence or []) + blockers))

    if result.context_gaps:
        autonomy = "need_assist"
        human_reason = "缺少继续推进当前决策所需的现实信息"
    elif first_action and not blockers:
        autonomy = "need_confirm"
        human_reason = ""
    else:
        autonomy = "inform_only"
        human_reason = ""

    ctx = PipelineContext(
        store_id=request.store_state.store_id,
        trigger=request.trigger_reason.lower(),
        source_node=request.analysis_node or "",
        observed_metric=str(obs.get("metric") or request.business_event.event_type.lower()),
        observed_delta=_metric_delta_pct(obs.get("change") or obs.get("delta_pct")),
        compare_baseline=str(obs.get("benchmark") or ""),
        root_cause=result.diagnosis.primary,
        evidence=evidence[:5],
        subject_type=subject.type,
        subject_id=subject.id,
        subject_name=subject.name,
        estimated_loss=obs.get("estimated_loss_orders"),
        goal_text=request.goal_text,
        goal_relevance_level="high" if request.goal_text else "medium",
        required_context_keys=result.context_gaps,
        candidate_actions=[action.model_dump() for action in result.candidate_actions],
        selected_action=first_action.title if first_action and not blockers else result.recommended_next_step,
        selected_action_type=first_action.action_type if first_action and not blockers else "",
        risk_level=first_action.risk_level if first_action else "medium",
        reversibility="easy" if first_action and first_action.risk_level == "low" else "medium",
        profitability="依赖验证已通过" if not blockers else "等待依赖域完成验证",
        autonomy=autonomy,
        success_metric=first_finding.code if first_finding else result.recommended_next_step,
        observation_window_hours=first_action.observation_window_hours if first_action else 48,
        confidence=result.diagnosis.confidence or (first_finding.confidence if first_finding else 0.7),
        system_mode=request.system_mode,
        human_reason=human_reason,
    )
    odo = run_analysis_pipeline(ctx)
    odo.id = f"{request.business_event.event_id}:{skill_key}"
    odo.domain = _ODO_DOMAIN_MAP[skill_key]  # type: ignore[assignment]
    candidate = CandidateODOEnvelope(
        id=odo.id,
        state=request.runtime_state or "daily_deep_review",
        node=request.analysis_node or "night_settlement",
        trigger_reason=request.trigger_reason,
        domain=_ODO_DOMAIN_MAP[skill_key],  # type: ignore[arg-type]
        odo=odo,
        generated_at=datetime.now(),
    )
    return candidate


def run_runtime_bridge_poc(request: RuntimeBridgeRunRequest) -> RuntimeBridgeRunResult:
    """执行最小 Runtime Bridge POC。

    输入是 MealKey 已经筛过的 BusinessEvent；输出是 Candidate ODO，
    供 MealKey 后续继续做 POIE / Permission / Projection。
    """

    selection: list[str] = list(request.preferred_skills)
    selection.extend(select_skills_for_event(request.business_event.event_type))
    if request.question:
        selection.extend(select_skills_for_question(request.question))
    event_domain = request.business_event.domain.lower()
    if event_domain in {"product", "traffic", "profit", "competition"}:
        selection.insert(0, event_domain)
    selected_skills = _dedupe_domain_keys(selection)

    results: dict[DomainKey, DomainSkillResult] = {}
    executions: list[RuntimeBridgeSkillExecution] = []
    candidates: list[CandidateODOEnvelope] = []
    trace = [
        f"lead_agent 接收事件 {request.business_event.event_type}",
        f"选择 skills: {', '.join(selected_skills)}",
    ]

    for skill_key in selected_skills:
        manifest = get_skill(skill_key)
        if manifest is None:
            continue
        kwargs = _build_skill_kwargs(skill_key, request, results)
        result = manifest.analyze_fn(**kwargs)
        results[skill_key] = result

    for skill_key in selected_skills:
        result = results.get(skill_key)
        manifest = get_skill(skill_key)
        if result is None or manifest is None:
            continue
        blockers = _skill_blockers(skill_key, result, results)
        executions.append(
            RuntimeBridgeSkillExecution(
                skill_key=skill_key,
                skill_name=manifest.name,
                selected_because=_selection_reason(skill_key, request),
                dependencies=result.dependencies,
                findings_count=len(result.findings),
                candidate_actions_count=len(result.candidate_actions),
                recommended_next_step=result.recommended_next_step,
                blocking_reasons=blockers,
            )
        )
        candidate = _to_candidate_odo(
            request=request,
            skill_key=skill_key,
            result=result,
            blockers=blockers,
        )
        if candidate is not None:
            candidates.append(candidate)
            trace.append(f"{skill_key} 产出 Candidate ODO {candidate.id}")

    return RuntimeBridgeRunResult(
        selected_skills=selected_skills,
        skill_executions=executions,
        candidate_odos=candidates,
        trace=trace,
    )
