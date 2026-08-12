"""Tracing Service — 追溯"为什么 AI 做了这个动作"。

材料 §10：老板问"为什么你今天给我多花了 60 块"，必须能完整追：
Signal → Event → ODO → Evidence → Permission → Tool Call → Result
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_trace import ActionTrace


def create_trace(
    db: Session,
    *,
    store_id: str,
    trigger_source: str,  # signal / event / time / goal / opportunity
    trigger_detail: str = "",
    action_type: str = "",
    execution_mode: str = "ASK_APPROVAL",
    odo_id: str | None = None,
    recommendation_id: str | None = None,
    diagnosis_summary: str = "",
    evidence: list[str] | None = None,
    confidence: float | None = None,
    permission_basis: dict[str, Any] | None = None,
    guardrails_check: dict[str, Any] | None = None,
    action_params: dict[str, Any] | None = None,
    executor: str = "AI",
    cost_cny: float | None = None,
) -> ActionTrace:
    """创建一条动作追踪记录。"""
    trace = ActionTrace(
        store_id=store_id,
        odo_id=odo_id,
        recommendation_id=recommendation_id,
        trigger_source=trigger_source,
        trigger_detail=trigger_detail[:500] if trigger_detail else None,
        action_type=action_type,
        execution_mode=execution_mode,
        diagnosis_summary=diagnosis_summary[:500] if diagnosis_summary else None,
        evidence_json=json.dumps(evidence[:5], ensure_ascii=False) if evidence else None,
        confidence=confidence,
        permission_basis_json=json.dumps(permission_basis, ensure_ascii=False) if permission_basis else None,
        guardrails_check_json=json.dumps(guardrails_check, ensure_ascii=False) if guardrails_check else None,
        action_params_json=json.dumps(action_params, ensure_ascii=False) if action_params else None,
        executor=executor,
        cost_cny=cost_cny,
        executed_at=datetime.now(timezone.utc) if execution_mode in ("AUTO", "AUTO_AND_REPORT") else None,
    )
    db.add(trace)
    db.commit()
    db.refresh(trace)
    return trace


def resolve_trace(
    db: Session,
    trace_id: str,
    *,
    status: str,  # success / failed / rolled_back
    detail: str = "",
    cost_cny: float | None = None,
) -> ActionTrace | None:
    """标记动作追踪的结果。"""
    trace = db.get(ActionTrace, trace_id)
    if trace is None:
        return None
    trace.result_status = status
    trace.result_detail = detail[:500] if detail else None
    if cost_cny is not None:
        trace.cost_cny = cost_cny
    trace.resolved_at = datetime.now(timezone.utc)
    db.add(trace)
    db.commit()
    db.refresh(trace)
    return trace


def get_trace_chain(db: Session, store_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """获取门店最近的动作追踪链——回答"AI 做了什么，为什么"。"""
    traces = db.execute(
        select(ActionTrace)
        .where(ActionTrace.store_id == store_id)
        .order_by(ActionTrace.created_at.desc())
        .limit(limit)
    ).scalars().all()

    result: list[dict[str, Any]] = []
    for t in traces:
        entry: dict[str, Any] = {
            "id": t.id,
            "trigger": t.trigger_source,
            "trigger_detail": t.trigger_detail or "",
            "action_type": t.action_type,
            "execution_mode": t.execution_mode,
            "executor": t.executor,
            "status": t.result_status,
            "cost": t.cost_cny,
            "diagnosis": t.diagnosis_summary or "",
            "evidence": json.loads(t.evidence_json) if t.evidence_json else [],
            "permission": json.loads(t.permission_basis_json) if t.permission_basis_json else {},
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "executed_at": t.executed_at.isoformat() if t.executed_at else "",
        }
        result.append(entry)
    return result


def explain_action(db: Session, trace_id: str) -> str:
    """用自然语言解释"为什么 AI 做了这个动作"。

    老板问"为什么你今天多花了 60 块"时，直接返回这段话。
    """
    trace = db.get(ActionTrace, trace_id)
    if trace is None:
        return "未找到该动作的追踪记录。"

    parts: list[str] = []
    # 1. 触发
    if trace.trigger_detail:
        parts.append(f"触发原因：{trace.trigger_detail}")
    # 2. 诊断
    if trace.diagnosis_summary:
        parts.append(f"诊断：{trace.diagnosis_summary}")
    # 3. 证据
    if trace.evidence_json:
        try:
            evidence = json.loads(trace.evidence_json)
            if evidence:
                parts.append("证据：" + "；".join(evidence[:3]))
        except json.JSONDecodeError:
            pass
    # 4. 权限
    if trace.permission_basis_json:
        try:
            perm = json.loads(trace.permission_basis_json)
            if perm.get("rule"):
                parts.append(f"执行依据：{perm['rule']}" + (f"（限额 ¥{perm.get('limit')}）" if perm.get("limit") else ""))
        except json.JSONDecodeError:
            pass
    # 5. 结果
    if trace.cost_cny:
        parts.append(f"花费：¥{trace.cost_cny}")
    if trace.result_status == "success":
        parts.append("结果：执行成功")
    elif trace.result_status == "failed":
        parts.append("结果：执行失败")

    return "；\n".join(parts) if parts else "该动作暂无详细追踪信息。"
