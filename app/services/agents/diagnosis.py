from __future__ import annotations
from sqlalchemy.orm import Session
from app.schemas.agents import DiagnosisAgentResult, DiagnosisObservationView
from app.services.diagnosis_analysis import (
    build_diagnosis_comparisons,
    build_diagnosis_root_causes,
    build_diagnosis_signals,
    build_market_comparison,
    diagnosis_score,
)
from app.services.agent_narrator import narrate_diagnosis

from .types import _AgentContext
from .helpers import (
    _agent_meta,
    _dedupe_strings,
    _json_loads_list,
    _metric_label,
    _problem_summary,
    _recommendation_title,
)
from .workflow import (
    _current_action,
    _dedupe_workflow_items,
    _experiment_map,
    _workflow_item,
    _workflow_phase_rank,
    _workflow_phase_summary,
)
from .menu import _alignment_readiness, _document_blockers

def _build_diagnosis_agent(db: Session, ctx: _AgentContext) -> DiagnosisAgentResult:
    primary_problem = ctx.store_state.primary_problem.type if ctx.store_state.primary_problem else "unknown"
    hypothesis = ctx.hypothesis
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    experiment_map = _experiment_map(ctx)
    full_action_queue = _dedupe_workflow_items(sorted(
        [_workflow_item(rec, experiment_map, item_names) for rec in ctx.recommendations],
        key=_workflow_phase_rank,
    ))
    current_action = _current_action(full_action_queue)
    action_queue = full_action_queue[:4]
    metric_key = "orders"
    if primary_problem == "store_ctr_down":
        metric_key = "ctr"
    elif primary_problem == "store_cvr_down":
        metric_key = "cvr"

    metric_row = ctx.store_state.kpis.get(metric_key)
    delta = metric_row.delta_pct if metric_row else None
    delta_text = f"{delta:.1f}%" if delta is not None else "暂无明显变化"
    daily_summary = f"{_metric_label(metric_key)} {delta_text}，{hypothesis.root_cause if hypothesis else _problem_summary(primary_problem)}"
    reasons = _json_loads_list(hypothesis.evidence_refs) if hypothesis else []
    if not reasons:
        reasons = [obs.what_happened for obs in ctx.observations[:2]] or [_problem_summary(primary_problem)]
    next_actions = (
        _dedupe_strings([item.title for item in action_queue[:3]])
        if action_queue
        else _dedupe_strings([_recommendation_title(rec.action_type) for rec in ctx.recommendations[:3]])
    )
    blockers = _document_blockers(ctx)
    workflow_summary = None
    if current_action is not None:
        workflow_summary = f"{_workflow_phase_summary(current_action)} {current_action.phase_reason}"
    if blockers:
        workflow_summary = blockers[0]
    readiness = _alignment_readiness(ctx)
    evidence = [
        f"主问题：{primary_problem}",
        f"{_metric_label(metric_key)} 变化：{delta_text}",
        *(reasons[:2]),
        ctx.document_alignment.get("summary", ""),
    ]
    comparisons = build_diagnosis_comparisons(db, ctx.store.id)
    metric_signals, data_gaps = build_diagnosis_signals(db, ctx.store_state)
    root_causes = build_diagnosis_root_causes(ctx.store_state, metric_signals)
    market_comparison = build_market_comparison(ctx.store_state)
    score = diagnosis_score(metric_signals, data_gaps)
    primary_root = root_causes[0] if root_causes else None
    executive_summary = (
        f"经营诊断 {score} 分。首要问题是{primary_root.title}；"
        f"{primary_root.explanation}"
        if primary_root
        else f"经营诊断 {score} 分，当前未发现单一强异常。"
    )
    priority_map = {
        "traffic_decline": "先排查流量入口、排序和时段曝光，不要直接改价格。",
        "first_impression": "先优化主推商品主图或标题，只执行一个 CTR 动作。",
        "conversion_weakness": "先修套餐、价格价值感与评价承接，观察 72 小时 CVR。",
        "aov_decline": "围绕主推款补搭配品或套餐，先验证客单与连带单。",
        "rating_decline": "先收敛差评主题并修正一个服务问题，再观察评分和 CVR。",
        "competition_pressure": "继续采集竞品快照，用真实变化辅助判断，不跟随盲目降价。",
        "no_strong_anomaly": "保持当前动作节奏，补齐退款、复购和商圈趋势数据。",
    }
    action_priorities = [priority_map[row.code] for row in root_causes if row.code in priority_map]
    if market_comparison.availability != "ready":
        data_gaps.append(market_comparison.note)

    diagnosis_narrative = narrate_diagnosis(
        store_name=ctx.store.name,
        diagnosis_score=score,
        primary_problem=primary_problem,
        daily_summary=daily_summary,
        root_causes=[r.model_dump(mode="json") for r in root_causes],
        metric_signals=[m.model_dump(mode="json") for m in metric_signals],
        next_actions=next_actions[:3],
        fallback_summary=executive_summary,
    )
    diagnosis_meta = _agent_meta("diagnosis", ctx.generated_at, hypothesis.confidence if hypothesis else 0.68)
    if diagnosis_narrative:
        diagnosis_meta.ai_narrative = diagnosis_narrative
        diagnosis_meta.ai_mode = "llm"
    return DiagnosisAgentResult(
        meta=diagnosis_meta,
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        diagnosis_score=score,
        executive_summary=executive_summary,
        daily_summary=daily_summary,
        primary_problem=primary_problem,
        root_cause=primary_root.title if primary_root else hypothesis.root_cause if hypothesis else None,
        comparisons=comparisons,
        metric_signals=metric_signals,
        root_causes=root_causes,
        market_comparison=market_comparison,
        data_gaps=list(dict.fromkeys(data_gaps))[:5],
        observations=[
            DiagnosisObservationView(
                metric=obs.metric,
                what_happened=obs.what_happened,
                delta_pct=obs.delta_pct,
                confidence=obs.confidence,
            )
            for obs in ctx.observations[:4]
        ],
        reasons=reasons[:3],
        evidence=[row for row in list(dict.fromkeys(evidence))[:5] if row],
        next_actions=next_actions[:3],
        action_priorities=list(dict.fromkeys(action_priorities))[:3],
        workflow_summary=workflow_summary,
        action_queue=action_queue,
        current_action=current_action,
    )
