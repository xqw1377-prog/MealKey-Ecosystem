"""Shared helpers for matrix specialist agents (promo/ads/crm/service/review/store_matrix)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ReviewFact, ReviewNLP, Store
from app.models.ohre import Experiment, Recommendation
from app.schemas.agents import (
    AgentActionCreateResponse,
    AgentKey,
    AgentPriorityAction,
    AgentWorkflowItem,
)
from app.services.action_feedback import find_recent_action_feedback


@dataclass
class MatrixAgentInput:
    store: Store
    menu_items: list[dict[str, Any]]
    item_snapshots: list[Any]
    competition_changes: list[Any]
    kpis: dict[str, Any]
    document_alignment: dict[str, Any]
    primary_problem_type: Optional[str]
    hypothesis_id: Optional[str]
    generated_at: datetime
    days: int = 7
    sibling_stores: list[Store] = field(default_factory=list)
    # 透传实验记录，让 attach_queue 能判定 execution_phase（P1-3）
    experiments: list[Any] = field(default_factory=list)
    # 真实 CRM 用户数据是否可用（P1-2：CRM 降级用）
    has_real_crm_data: bool = False
    # 无真实投流数据时 Ads Agent fail-closed，禁止把加投当实战
    ads_observed: bool = False


MATRIX_ACTION_TYPES: dict[str, set[str]] = {
    "promo": {
        "join_lunch_campaign",
        "launch_value_bundle_promo",
        "match_competitor_promo",
    },
    "ads": {
        "boost_hero_item_ads",
        "shift_ads_to_high_cvr_item",
        "pause_broad_ads",
    },
    "crm": {
        "recall_churn_risk_users",
        "nurture_new_customers",
        "reward_vip_repeat",
    },
    "service": {
        "batch_reply_negative_reviews",
        "publish_service_reply_scripts",
        "escalate_portion_complaints",
    },
    "review": {
        "fix_top_review_theme",
        "pin_positive_review_themes",
        "reply_rating_critical_reviews",
        "escalate_unfair_review",
    },
    "store_matrix": {
        "open_lunch_online_store",
        "open_night_online_store",
        "open_value_online_store",
    },
}

ALL_MATRIX_ACTION_TYPES = {action for actions in MATRIX_ACTION_TYPES.values() for action in actions}


def clamp_score(score: float, low: int = 20, high: int = 98) -> int:
    return int(max(low, min(high, round(score))))


def kpi_delta(kpis: dict[str, Any], key: str) -> Optional[float]:
    row = kpis.get(key)
    if row is None:
        return None
    return getattr(row, "delta_pct", None) if not isinstance(row, dict) else row.get("delta_pct")


def kpi_value(kpis: dict[str, Any], key: str) -> Optional[float]:
    row = kpis.get(key)
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get("observed_value") if row.get("observed_value") is not None else row.get("value")
    return getattr(row, "observed_value", None) if getattr(row, "observed_value", None) is not None else getattr(row, "value", None)


def alignment_readiness(document_alignment: dict[str, Any]) -> str:
    status = document_alignment.get("status") or "partial"
    if status == "aligned":
        return "ready"
    if status == "partial":
        return "partial"
    return "limited"


def load_reviews(db: Session, store_id: str, limit: int = 60) -> list[tuple[ReviewFact, Optional[ReviewNLP]]]:
    rows = db.execute(
        select(ReviewFact, ReviewNLP)
        .outerjoin(ReviewNLP, ReviewNLP.review_id == ReviewFact.id)
        .where(ReviewFact.store_id == store_id)
        .order_by(ReviewFact.reviewed_at.desc())
        .limit(limit)
    ).all()
    return [(review, nlp) for review, nlp in rows]


def review_theme_counts(rows: list[tuple[ReviewFact, Optional[ReviewNLP]]]) -> dict[str, int]:
    counts = {"portion": 0, "package": 0, "speed": 0, "taste": 0, "appearance": 0}
    for review, nlp in rows:
        text = (review.content or "").lower()
        if nlp is not None:
            if nlp.portion is not None and nlp.portion < 0.42:
                counts["portion"] += 1
            if nlp.package is not None and nlp.package < 0.42:
                counts["package"] += 1
            if nlp.speed is not None and nlp.speed < 0.42:
                counts["speed"] += 1
            if nlp.taste is not None and nlp.taste < 0.42:
                counts["taste"] += 1
        if any(token in text for token in ("份量", "量少", "太少", "不够吃")):
            counts["portion"] += 1
        if any(token in text for token in ("包装", "撒漏", "漏了", "洒了")):
            counts["package"] += 1
        if any(token in text for token in ("慢", "迟到", "配送慢", "等太久")):
            counts["speed"] += 1
        if any(token in text for token in ("难吃", "味道", "咸", "淡")):
            counts["taste"] += 1
        if any(token in text for token in ("图", "照片", "和实物", "不像", "色差")):
            counts["appearance"] += 1
    return counts


def top_item(snapshots: list[Any]) -> Any | None:
    if not snapshots:
        return None
    return sorted(
        snapshots,
        key=lambda row: (getattr(row, "observe_orders", 0) or 0, getattr(row, "observe_cvr", 0) or 0),
        reverse=True,
    )[0]


def has_set_meal(menu_items: list[dict[str, Any]]) -> bool:
    return any(
        any(token in (row.get("name") or "") for token in ("套餐", "组合", "双人", "单人餐", "工作餐"))
        for row in menu_items
    )


def natural_conversion_stable(kpis: dict[str, Any]) -> bool:
    ctr = kpi_delta(kpis, "ctr")
    cvr = kpi_delta(kpis, "cvr")
    ctr_ok = ctr is None or ctr >= -5
    cvr_ok = cvr is None or cvr >= -5
    return ctr_ok and cvr_ok


def make_action(
    *,
    action_type: str,
    title: str,
    detail: str,
    expected_metric: str,
    lift_low: float,
    lift_high: float,
    object_ref: str,
    object_name: str,
    evidence: list[str],
    risk_level: str = "medium",
    severity: str = "medium",
    window_hours: int = 48,
    content: Optional[dict[str, Any]] = None,
) -> AgentPriorityAction:
    return AgentPriorityAction(
        action_type=action_type,
        title=title,
        detail=detail,
        expected_metric=expected_metric,
        expected_lift_pct_low=lift_low,
        expected_lift_pct_high=lift_high,
        window_hours=window_hours,
        risk_level=risk_level,
        severity=severity,
        object_ref=object_ref,
        object_name=object_name,
        generated_content=content or {},
        evidence=evidence,
    )


def prioritize_actions_with_feedback(
    actions: list[AgentPriorityAction],
    recommendations: list[Recommendation],
    experiments: list[Experiment],
    *,
    agent_key: AgentKey,
) -> list[AgentPriorityAction]:
    if not actions:
        return actions

    ranked: list[tuple[float, int, AgentPriorityAction]] = []
    total = len(actions)
    source_tag = f"{agent_key}_agent"
    for index, action in enumerate(actions):
        feedback = find_recent_action_feedback(
            recommendations,
            experiments,
            action_type=action.action_type,
            object_ref=action.object_ref,
            source_tag=source_tag,
        )
        generated_content = dict(action.generated_content)
        evidence = list(action.evidence)
        if feedback is not None:
            generated_content.update(
                {
                    "feedback_result": feedback.result,
                    "feedback_note": feedback.note,
                    "feedback_lift_pct": feedback.lift_pct,
                }
            )
            evidence = list(dict.fromkeys([feedback.note, *evidence]))[:5]
        ranked.append(
            (
                (total - index) + (feedback.score_delta if feedback is not None else 0.0),
                index,
                action.model_copy(update={"generated_content": generated_content, "evidence": evidence}),
            )
        )

    return [row[2] for row in sorted(ranked, key=lambda row: (-row[0], row[1]))]


def attach_queue(
    *,
    agent_key: AgentKey,
    priority_actions: list[AgentPriorityAction],
    recommendations: list[Recommendation],
    set_queue,
    experiments: list[Any] | None = None,
    generated_at: Any | None = None,
) -> None:
    """Mutates result via set_queue(queue, current).

    execution_phase 与 growth agent 的状态机对齐（审计 P1-3）：
    - proposed → execute_now
    - adopted → execute_now
    - executed + 实验 pending/None → observe
    - executed + positive/neutral/negative → review
    - archived → archived
    之前矩阵 agent 只用两态（execute_now/observe），导致已出结果的实验仍显示 observe。
    """
    allowed = MATRIX_ACTION_TYPES.get(agent_key, set())
    source_tag = f"{agent_key}_agent"
    experiment_map: dict[str, Any] = {}
    if experiments:
        for exp in experiments:
            if getattr(exp, "recommendation_id", None):
                experiment_map[exp.recommendation_id] = exp

    queue: list[AgentWorkflowItem] = []
    for rec in recommendations:
        content: dict[str, Any] = {}
        try:
            content = json.loads(rec.content_json or "{}")
        except json.JSONDecodeError:
            content = {}
        if rec.action_type not in allowed and content.get("source") != source_tag:
            continue

        experiment = experiment_map.get(rec.id)
        execution_phase = _matrix_execution_phase(rec, experiment)
        queue.append(
            AgentWorkflowItem(
                recommendation_id=rec.id,
                title=content.get("title") or rec.action_type,
                action_type=rec.action_type,
                object_ref=rec.object_ref,
                object_name=content.get("object_name") or rec.object_ref,
                status=rec.status,
                execution_phase=execution_phase,
                expected_metric=rec.expected_metric or "orders",
                window_hours=rec.window_hours or 48,
                confidence=float(rec.confidence or 0.6),
                evidence=content.get("evidence") or [],
                experiment_id=getattr(experiment, "id", None) if experiment else None,
                experiment_result=getattr(experiment, "result", None) if experiment else None,
            )
        )
    # current 选 execute_now > review > observe > deferred > archived
    phase_rank = {"execute_now": 0, "review": 1, "observe": 2, "deferred": 3, "archived": 4}
    current = (
        sorted(queue, key=lambda r: phase_rank.get(r.execution_phase, 2))[0] if queue else None
    )
    set_queue(queue, current)


def _matrix_execution_phase(rec: Recommendation, experiment: Any | None) -> str:
    """与 agents._workflow_phase 同语义，给矩阵 agent 复用。"""
    if rec.status == "proposed":
        return "execute_now"
    if rec.status == "adopted":
        return "execute_now"
    if rec.status == "archived":
        return "archived"
    # executed
    if experiment is None:
        return "observe"
    result = getattr(experiment, "result", None)
    if result in {None, "pending"}:
        return "observe"
    return "review"


def annotate_action_gates(
    actions: list[AgentPriorityAction],
    *,
    agent_key: AgentKey,
    unlock_ready: bool = True,
    blockers: list[str] | None = None,
    profit_state: Any = None,
    system_mode: str = "operating",
    strategy_memory: Any = None,
) -> list[AgentPriorityAction]:
    """Attach create_enabled / profit_gate flags for frontend + create guards."""
    from app.services.profit_gate import evaluate_profit_gate

    blockers = blockers or []
    annotated: list[AgentPriorityAction] = []
    for action in actions:
        create_enabled = True
        create_block_reason = None
        profit_allowed = None
        profit_reason = None

        if agent_key in {"promo", "ads", "store_matrix"} and not unlock_ready:
            create_enabled = False
            create_block_reason = blockers[0] if blockers else "尚未解锁，先补齐前置条件。"

        if agent_key in {"promo", "ads"} and profit_state is not None:
            memory_veto = None
            if strategy_memory is not None:
                for item in getattr(strategy_memory, "items", []) or []:
                    if getattr(item, "action_type", "") == action.action_type and getattr(item, "result", "") == "negative":
                        memory_veto = getattr(item, "avoid_when", None) or getattr(item, "lesson", None)
                        break
            gate = evaluate_profit_gate(
                profit_state,
                action_type=action.action_type,
                expected_order_lift_pct=float(action.expected_lift_pct_high or 0),
                system_mode=system_mode,
                memory_veto=memory_veto,
            )
            profit_allowed = gate.allowed
            profit_reason = gate.reason
            if not gate.allowed:
                create_enabled = False
                create_block_reason = gate.reason

        annotated.append(
            action.model_copy(
                update={
                    "profit_gate_allowed": profit_allowed,
                    "profit_gate_reason": profit_reason,
                    "create_enabled": create_enabled,
                    "create_block_reason": create_block_reason,
                }
            )
        )
    return annotated


def create_matrix_action(
    db: Session,
    *,
    store_id: str,
    agent_key: AgentKey,
    action_index: int,
    actions: list[AgentPriorityAction],
    hypothesis_id: Optional[str] = None,
    extra_content: Optional[dict[str, Any]] = None,
) -> AgentActionCreateResponse:
    if action_index < 0 or action_index >= len(actions):
        raise IndexError(f"{agent_key} action not found")
    action = actions[action_index]
    if action.create_enabled is False:
        raise ValueError(action.create_block_reason or "当前动作未通过解锁/利润门禁，暂不可创建。")
    metric_label = {
        "orders": "订单",
        "gmv": "成交额",
        "ctr": "点击率",
        "cvr": "转化率",
        "rating": "评分",
        "repurchase_rate": "复购率",
    }.get(action.expected_metric, action.expected_metric)
    review_note = f"先围绕{metric_label}验证这条动作，观察窗结束后再决定继续放大还是回退。"
    observe_focus = [
        f"观察 {action.object_name} 的{metric_label}变化。",
        "观察窗内不要叠加第二个同类动作。",
    ]
    next_decision = observe_focus[0]

    existing_candidates = db.execute(
        select(Recommendation).where(
            Recommendation.store_id == store_id,
            Recommendation.action_type == action.action_type,
            Recommendation.object_ref == action.object_ref,
            Recommendation.status.in_(("proposed", "adopted", "executed")),
        )
    ).scalars().all()
    existing = None
    existing_experiment = None
    for candidate in existing_candidates:
        candidate_experiment = db.execute(
            select(Experiment)
            .where(Experiment.recommendation_id == candidate.id)
            .order_by(Experiment.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        in_observation = (
            candidate.status == "executed"
            and (
                candidate_experiment is None
                or candidate_experiment.result in {None, "pending"}
            )
        )
        if candidate.status in {"proposed", "adopted"} or in_observation:
            existing = candidate
            existing_experiment = candidate_experiment
            break
    if existing is not None:
        existing_payload = json.loads(existing.content_json or "{}")
        existing_payload.update(
            {
                "review_note": review_note,
                "observe_focus": observe_focus,
                "next_decision": next_decision,
                "generated_content": action.generated_content,
                "evidence": action.evidence,
                **(extra_content or {}),
            }
        )
        existing.content_json = json.dumps(existing_payload, ensure_ascii=False)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return AgentActionCreateResponse(
            store_id=store_id,
            agent_key=agent_key,
            action_index=action_index,
            recommendation_id=existing.id,
            experiment_id=existing_experiment.id if existing_experiment else None,
            status=existing.status,
            message=f"该{agent_key}动作已在队列中，无需重复创建。",
            review_note=review_note,
            observe_focus=observe_focus,
            next_decision=next_decision,
            action=action,
        )

    payload = {
        "source": f"{agent_key}_agent",
        "title": action.title,
        "detail": action.detail,
        "risk_level": action.risk_level,
        "object_name": action.object_name,
        "review_note": review_note,
        "observe_focus": observe_focus,
        "next_decision": next_decision,
        "generated_content": action.generated_content,
        "evidence": action.evidence,
        "feedback_history": [
            {
                "status": "proposed",
                "at": datetime.now().isoformat(),
                "message": f"{agent_key} Agent 已生成可执行动作",
            }
        ],
        **(extra_content or {}),
    }
    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=hypothesis_id,
        scope="store" if action.object_ref.startswith("store:") else "item",
        object_ref=action.object_ref,
        action_type=action.action_type,
        expected_metric=action.expected_metric,
        expected_lift_pct_low=action.expected_lift_pct_low,
        expected_lift_pct_high=action.expected_lift_pct_high,
        window_hours=action.window_hours,
        confidence=0.72 if action.severity == "high" else 0.64,
        rollback_rule="若观察窗内核心指标无改善，停止该动作并回看诊断根因。",
        status="proposed",
        content_json=json.dumps(payload, ensure_ascii=False),
        evidence_json=json.dumps(action.evidence, ensure_ascii=False),
    )
    db.add(recommendation)
    db.commit()
    db.refresh(recommendation)
    return AgentActionCreateResponse(
        store_id=store_id,
        agent_key=agent_key,
        action_index=action_index,
        recommendation_id=recommendation.id,
        experiment_id=None,
        status=recommendation.status,
        message=f"已生成动作「{action.title}」，等待老板确认执行。",
        review_note=review_note,
        observe_focus=observe_focus,
        next_decision=next_decision,
        action=action,
    )
