"""Runtime Bridge runtime adapter.

把 MealKey 的业务对象桥接到 Runtime Bridge POC / Runtime Bridge Runtime，
并把结果投影成 Runtime Queue / Feed，方便后端和前端统一消费。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from urllib import request as urllib_request

from app.schemas.runtime_bridge import RuntimeBridgeRunRequest, RuntimeBridgeRunResult
from app.schemas.runtime_event import (
    ArbitrationQueueEntry,
    RuntimeEventEnvelope,
    RuntimeFeedResponse,
    RuntimeQueueResponse,
)
from app.services.runtime_bridge import run_runtime_bridge_poc


def _priority_from_odo(odo: Any) -> float:
    level = getattr(odo, "goal_relevance_level", "medium")
    confidence = float(getattr(odo, "confidence", 0.7) or 0.7)
    base = {"high": 85.0, "medium": 65.0, "low": 45.0}.get(level, 60.0)
    return round(base + confidence * 10, 1)


def _interrupt_owner(odo: Any) -> bool:
    return getattr(odo, "execution_mode", "") in {"ASK_APPROVAL", "ASK_INFORMATION"}


def run_runtime_bridge_runtime(request: RuntimeBridgeRunRequest) -> RuntimeBridgeRunResult:
    """运行 Runtime Bridge bridge。

    默认走本地 POC bridge；
    当配置了远端 Runtime Bridge Runtime 时，可切到 HTTP adapter。
    """
    mode = os.getenv("MEALKEY_RUNTIME_BRIDGE", "local_poc").strip().lower()
    if mode != "http":
        return run_runtime_bridge_poc(request)

    url = os.getenv("MEALKEY_RUNTIME_BRIDGE_URL", "").strip()
    if not url:
        return run_runtime_bridge_poc(request)

    payload = request.model_dump(mode="json")
    req = urllib_request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    return RuntimeBridgeRunResult.model_validate_json(body)


def runtime_bridge_result_to_runtime_queue(
    *,
    store_id: str,
    runtime_state: str,
    result: RuntimeBridgeRunResult,
    source_event_id: str = "",
) -> RuntimeQueueResponse:
    items: list[ArbitrationQueueEntry] = []
    for candidate in result.candidate_odos:
        priority = _priority_from_odo(candidate.odo)
        items.append(
            ArbitrationQueueEntry(
                candidate_odo_id=candidate.id,
                runtime_state=runtime_state,  # type: ignore[arg-type]
                priority_score=priority,
                decision=candidate.odo.execution_mode,
                interrupt_owner=_interrupt_owner(candidate.odo),
                source_event_id=source_event_id or None,
            )
        )
    return RuntimeQueueResponse(
        store_id=store_id,
        runtime_state=runtime_state,  # type: ignore[arg-type]
        items=items,
    )


def runtime_bridge_result_to_runtime_feed(
    *,
    store_id: str,
    runtime_state: str,
    result: RuntimeBridgeRunResult,
    source_event_id: str = "",
) -> RuntimeFeedResponse:
    events: list[RuntimeEventEnvelope] = []
    now = datetime.now()
    for candidate in result.candidate_odos:
        odo = candidate.odo
        events.append(
            RuntimeEventEnvelope(
                id=f"rt_{candidate.id}",
                store_id=store_id,
                state=runtime_state,  # type: ignore[arg-type]
                node=candidate.node,
                trigger_reason=candidate.trigger_reason,
                domain=candidate.domain,
                subject=odo.object,
                title=odo.diagnosis.primary or odo.why_now or odo.subject or "经营事件",
                detail=odo.business_impact.summary or odo.human_reason or odo.human_request,
                evidence=list(odo.evidence or [])[:4],
                event_payload={
                    "selected_action": odo.recommended_action.model_dump(mode="json"),
                    "pipeline_steps": odo.pipeline_steps_completed,
                    "source_event_id": source_event_id,
                },
                priority_score=_priority_from_odo(odo),
                status=odo.execution_mode.lower(),
                source_odo_id=odo.id,
                occurred_at=now,
            )
        )
    return RuntimeFeedResponse(
        store_id=store_id,
        runtime_state=runtime_state,  # type: ignore[arg-type]
        events=events,
    )
