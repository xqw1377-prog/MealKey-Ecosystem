"""Runtime V1 API — 统一 workspace 三栏投影 + intent 入口。

材料 §十五：GET /v1/stores/{store_id}/workspace 返回三栏全部从统一 Runtime 投影。
材料 §十八：POST /v1/stores/{store_id}/intent 不是普通聊天，是 Intent→Goal→Plan→ODO→POIE 链路。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.runtime_bridge import RuntimeBridgeRunRequest
from app.schemas.runtime_event import RuntimeFeedResponse, RuntimeQueueResponse
from app.schemas.runtime_objects import BusinessEventObject, MerchantContextItem, StoreStateSnapshot
from app.schemas.runtime_api import WorkspaceRuntimeResponse

logger = logging.getLogger(__name__)
router = APIRouter()


class IntentRequest(BaseModel):
    """用户意图输入（底部 AI Command Bar）。"""
    text: str
    attachments: list[str] = []  # 文件名列表（已上传的）
    work_thread_id: Optional[str] = None


class RuntimeBridgePreviewRequest(BaseModel):
    """Runtime Bridge bridge 预览输入。

    用于把一个 BusinessEvent 直接送入 runtime adapter，验证 Golden Path。
    """

    store_state: StoreStateSnapshot
    business_event: BusinessEventObject
    merchant_context: list[MerchantContextItem] = []
    goal_text: str = ""
    question: str = ""
    trigger_reason: str = "ANOMALY"
    runtime_state: Optional[str] = None
    analysis_node: Optional[str] = None
    preferred_skills: list[str] = []
    system_mode: str = "operating"


def _preview_bridge_response(store_id: str, request: RuntimeBridgeRunRequest, source_event_id: str) -> dict[str, Any]:
    from app.services.runtime_bridge_adapter import (
        runtime_bridge_result_to_runtime_feed,
        runtime_bridge_result_to_runtime_queue,
        run_runtime_bridge_runtime,
    )

    result = run_runtime_bridge_runtime(request)
    runtime_state = request.runtime_state or "daily_deep_review"
    queue: RuntimeQueueResponse = runtime_bridge_result_to_runtime_queue(
        store_id=store_id,
        runtime_state=runtime_state,
        result=result,
        source_event_id=source_event_id,
    )
    feed: RuntimeFeedResponse = runtime_bridge_result_to_runtime_feed(
        store_id=store_id,
        runtime_state=runtime_state,
        result=result,
        source_event_id=source_event_id,
    )
    return {
        "runtime_bridge": result.model_dump(mode="json"),
        "queue": queue.model_dump(mode="json"),
        "feed": feed.model_dump(mode="json"),
    }


def _build_daily_plan_payload(store_id: str, db: Session) -> dict[str, Any]:
    from app.services.runtime_engine import build_daily_operating_plan, determine_runtime_state

    plan = build_daily_operating_plan(db, store_id)
    state = determine_runtime_state()
    return {
        "plan": plan.model_dump(mode="json"),
        "runtime_state": state,
    }


def _build_workspace_payload(store_id: str, db: Session) -> dict[str, Any]:
    from app.services.agents import build_store_agents
    from app.services.event_engine import build_operating_events
    from app.services.event_decisions import apply_decision_overrides, load_decision_map
    from app.services.manager_brief import build_manager_home_brief
    from app.services.strategy_memory import load_strategy_memory
    from app.services.poie import run_poie
    from app.services.runtime_engine import determine_runtime_state
    from app.services.runtime_request_mapper import build_runtime_bridge_run_request, pick_primary_event
    from app.services.runtime_bridge_adapter import (
        runtime_bridge_result_to_runtime_feed,
        runtime_bridge_result_to_runtime_queue,
        run_runtime_bridge_runtime,
    )

    agents = build_store_agents(db=db, store_id=store_id, days=7)
    if agents is None:
        raise HTTPException(status_code=404, detail="store not found")

    events = apply_decision_overrides(
        build_operating_events(agents.store_state),
        load_decision_map(db, store_id),
    )
    memory = load_strategy_memory(db, store_id)

    brief = build_manager_home_brief(
        agents.store_state,
        events=events,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
        strategy_memory=memory,
        db=db,
        store_id=store_id,
    )

    poie = run_poie(
        brief,
        store_id=store_id,
        events=events,
        agents=agents,
        strategy_memory=memory,
        db=db,
    )

    queue = poie.ops_queue
    runtime_state = determine_runtime_state()

    from app.services.decision_flow import build_decision_flow

    decision_flow = build_decision_flow(
        queue=queue,
        events=events,
        db=db,
        store_id=store_id,
    )
    try:
        from app.services.operating_clock import apply_light_tick

        decision_flow["tick"] = apply_light_tick(db, store_id, flow=decision_flow, queue=queue)
        tick = decision_flow.get("tick") or {}
        decision_flow["tick"] = {
            "auto_done": len(tick.get("auto_executed") or []),
            "notified": bool(tick.get("notified")),
        }
    except Exception:  # noqa: BLE001 — 轻量时钟失败不挡首页
        decision_flow["tick"] = {"status": "skipped"}

    runtime_bridge_result = None
    runtime_bridge_queue = None
    runtime_bridge_feed = None
    source_event_id = ""
    primary_event = pick_primary_event(events.events)
    if primary_event is not None:
        runtime_bridge_request = build_runtime_bridge_run_request(
            state=agents.store_state,
            event=primary_event,
            goal_text=queue.active_goal.title if queue.active_goal else "",
        )
        runtime_bridge_result = run_runtime_bridge_runtime(runtime_bridge_request)
        source_event_id = primary_event.id
        runtime_bridge_queue = runtime_bridge_result_to_runtime_queue(
            store_id=store_id,
            runtime_state=runtime_state,
            result=runtime_bridge_result,
            source_event_id=source_event_id,
        )
        runtime_bridge_feed = runtime_bridge_result_to_runtime_feed(
            store_id=store_id,
            runtime_state=runtime_state,
            result=runtime_bridge_result,
            source_event_id=source_event_id,
        )

    # 三栏投影
    payload = {
        "store": {
            "store_id": store_id,
            "store_name": agents.store_name,
            "runtime_state": runtime_state,
            "operating_phase": decision_flow.get("phase") or "",
            "phase_label": decision_flow.get("phase_label") or "",
        },
        "left": _build_left_panel(
            queue,
            runtime_bridge_result,
            now_id=str((decision_flow.get("now") or {}).get("id") or ""),
            now_title=str((decision_flow.get("now") or {}).get("title") or ""),
            events=events,
        ),
        "center": {
            "active_thread_id": queue.threads[0].id if queue.threads else None,
            "guide": _build_guide(
                queue,
                runtime_bridge_result,
                runtime_bridge_queue,
                decision_flow=decision_flow,
            ),
            "principle": queue.principle,
            "decision_flow": decision_flow,
            "loop": None,
        },
        "right": {
            "proactive_feed": _build_feed(queue, events, runtime_bridge_feed),
            "filtered_count": queue.filtered_noop_count,
        },
        "meta": {
            "candidates_total": poie.candidates_total,
            "filtered_noop_count": poie.filtered_noop_count,
            "mealkey_score": brief.mealkey_score.model_dump(mode="json") if brief.mealkey_score else None,
            "operation_score": brief.operation_score.model_dump(mode="json") if brief.operation_score else None,
            "runtime_bridge": {
                "enabled": runtime_bridge_result is not None,
                "selected_skills": runtime_bridge_result.selected_skills if runtime_bridge_result else [],
                "lead_agent": runtime_bridge_result.lead_agent if runtime_bridge_result else "",
                "source_event_id": source_event_id,
                "candidate_count": len(runtime_bridge_result.candidate_odos) if runtime_bridge_result else 0,
            },
        },
    }
    if not (queue.need_you and _is_understanding_card(queue.need_you[0])):
        try:
            from app.services.closed_loop import apply_loop_to_workspace, ensure_now_loop

            loop = ensure_now_loop(db, store_id, decision_flow=decision_flow, events=events)
            payload = apply_loop_to_workspace(payload, loop)
        except Exception:
            logger.exception("closed-loop projection failed for store %s", store_id)
    return payload


@router.get("/stores/{store_id}/workspace", response_model=WorkspaceRuntimeResponse)
def get_workspace(store_id: str, db: Session = Depends(get_db)):
    """统一 workspace 三栏投影（材料 §十五）。

    前端只需要调这一个 API 就能拿到全部三栏数据。
    左栏：WorkThread 投影（need_you / active / waiting / completed）
    中栏：当前最高优先级 Guide + 对话
    右栏：经营意义过滤后的 Event Projection
    首页 GET 不同步等待大模型。
    """
    from app.services.llm_engine.request_budget import homepage_read_scope

    with homepage_read_scope():
        return _build_workspace_payload(store_id, db)


@router.post("/stores/{store_id}/loop/{loop_id}/executed")
def post_loop_executed(store_id: str, loop_id: str, db: Session = Depends(get_db)):
    """老板确认：这件事已经做了。人机任务必须先有证据。"""
    from app.services.closed_loop import mark_loop_executed, project_loop

    try:
        item = mark_loop_executed(db, store_id, loop_id)
    except ValueError as exc:
        message = str(exc)
        code = 404 if "not found" in message else 409
        raise HTTPException(status_code=code, detail=message) from exc
    return {"ok": True, "loop": project_loop(item)}


@router.post("/stores/{store_id}/loop/{loop_id}/evidence")
def post_loop_evidence(store_id: str, loop_id: str, payload: dict, db: Session = Depends(get_db)):
    """门店或老板提交线下动作证据。没有证据不能进入观察窗。"""
    from app.services.closed_loop import project_loop
    from app.services.store_ops import attach_evidence

    try:
        item = attach_evidence(
            db,
            store_id,
            loop_id,
            kind=str(payload.get("kind") or "note"),
            note=str(payload.get("note") or ""),
            data_url=str(payload.get("data_url") or ""),
            by=str(payload.get("by") or "OWNER"),
        )
    except ValueError as exc:
        message = str(exc)
        code = 404 if "not found" in message else 409
        raise HTTPException(status_code=code, detail=message) from exc
    return {"ok": True, "loop": project_loop(item)}


@router.post("/stores/{store_id}/loop/{loop_id}/execute-platform")
def post_loop_execute_platform(store_id: str, loop_id: str, db: Session = Depends(get_db)):
    """老板确认后：工具写回平台，读回成功才进入观察窗。失败保持 now。"""
    from app.services.closed_loop import execute_loop_platform_writeback, project_loop
    from app.services.platform_write import ReadBackMismatchError, WriteFailedError, WritePermissionError

    try:
        item = execute_loop_platform_writeback(db, store_id, loop_id)
    except WritePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReadBackMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WriteFailedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        code = 404 if "not found" in message else 409
        raise HTTPException(status_code=code, detail=message) from exc
    return {"ok": True, "loop": project_loop(item), "executor": item.executor}


@router.post("/stores/{store_id}/loop/{loop_id}/not-executed")
def post_loop_not_executed(store_id: str, loop_id: str, db: Session = Depends(get_db)):
    """老板确认：这一次还没改。"""
    from app.services.closed_loop import mark_loop_not_executed, project_loop

    try:
        item = mark_loop_not_executed(db, store_id, loop_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "loop": project_loop(item)}


@router.post("/stores/{store_id}/loop/{loop_id}/ack")
def post_loop_acked(store_id: str, loop_id: str, db: Session = Depends(get_db)):
    """老板看过结果。这条闭环结束，下一件 Now 才能进来。"""
    from app.services.closed_loop import mark_loop_acked, project_loop

    try:
        item = mark_loop_acked(db, store_id, loop_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "loop": project_loop(item)}


@router.post("/stores/{store_id}/loop/{loop_id}/share-card")
def post_loop_share_card(store_id: str, loop_id: str, db: Session = Depends(get_db)):
    """把这次 Result 收成结果卡，发给同行去测店。"""
    from app.services.closed_loop import get_loop, project_loop
    from app.services.commercial.growth import ensure_result_card, public_card, share_url_for

    item = get_loop(db, store_id, loop_id)
    if item is None:
        raise HTTPException(status_code=404, detail="loop not found")
    artifact = ensure_result_card(db, item, force=True)
    if artifact is None:
        raise HTTPException(status_code=409, detail="这次结果还不适合分享")
    db.commit()
    db.refresh(item)
    card = public_card(artifact, share_url=share_url_for(artifact.id))
    return {"ok": True, "share_card": card, "loop": project_loop(item)}


def _build_left_panel(
    queue,
    runtime_bridge_result,
    *,
    now_id: str = "",
    now_title: str = "",
    events=None,
) -> dict[str, Any]:
    from app.services.copy_humanize import humanize_operator_text

    def _dump_card(card, kind: str) -> dict[str, Any]:
        data = card.model_dump(mode="json")
        data["kind"] = kind
        data["title"] = humanize_operator_text(data.get("title") or "") or data.get("title") or ""
        data["summary"] = humanize_operator_text(
            data.get("summary") or data.get("why_now") or data.get("business_impact") or ""
        )
        data["why_now"] = humanize_operator_text(data.get("why_now") or "")
        data["ai_judgment"] = humanize_operator_text(data.get("ai_judgment") or "")
        data["business_impact"] = humanize_operator_text(data.get("business_impact") or "")
        return data

    left = {
        "need_you": [_dump_card(c, "need") for c in queue.need_you],
        "active": [_dump_card(c, "thread") for c in queue.working],
        "waiting": [],
        "completed": [_dump_card(c, "done") for c in queue.results],
        "opportunities": [_dump_card(c, "need") for c in queue.opportunities],
        "active_goal": queue.active_goal.model_dump(mode="json") if queue.active_goal else None,
        "threads": [t.model_dump(mode="json") for t in queue.threads],
    }

    seen_ids = {now_id} if now_id else set()
    seen_titles = {humanize_operator_text(now_title)} if now_title else set()
    for bucket in ("need_you", "active", "completed"):
        for item in left[bucket]:
            if item.get("id"):
                seen_ids.add(str(item["id"]))
            title = humanize_operator_text(item.get("title") or "")
            if title:
                seen_titles.add(title)

    def _is_dup(item_id: str, title: str) -> bool:
        hid = str(item_id or "").strip()
        htitle = humanize_operator_text(title)
        if hid and hid in seen_ids:
            return True
        if htitle and htitle in seen_titles:
            return True
        return False

    # runtime bridge 只补充，不再整桶替换——避免第二套 Now
    if runtime_bridge_result:
        for candidate in runtime_bridge_result.candidate_odos:
            odo = candidate.odo
            title = _candidate_title(candidate)
            item = {
                "id": candidate.id,
                "kind": "thread",
                "title": title,
                "summary": humanize_operator_text(
                    odo.why_now or odo.diagnosis.primary or odo.business_impact.summary or ""
                ),
                "status": odo.execution_mode,
                "prompt": _candidate_prompt(candidate),
                "source_odo_id": odo.id,
            }
            if _is_dup(candidate.id, title):
                continue
            if odo.execution_mode in {"ASK_INFORMATION", "ASK_APPROVAL"}:
                continue
            bucket = "waiting" if odo.execution_mode in {"OBSERVE", "DROP"} else "active"
            left[bucket].append(item)
            seen_ids.add(str(candidate.id))
            seen_titles.add(humanize_operator_text(title))

    def _dedupe(items: list[dict[str, Any]], *, drop_now: bool) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        local_ids: set[str] = set()
        local_titles: set[str] = set()
        for item in items:
            iid = str(item.get("id") or "")
            title = humanize_operator_text(item.get("title") or "")
            if drop_now and now_id and iid == now_id:
                continue
            if drop_now and now_title and title == humanize_operator_text(now_title):
                continue
            if iid and iid in local_ids:
                continue
            if title and title in local_titles:
                continue
            if iid:
                local_ids.add(iid)
            if title:
                local_titles.add(title)
            out.append(item)
        return out

    left["need_you"] = _dedupe(left["need_you"], drop_now=True)
    left["active"] = _dedupe(left["active"], drop_now=True)
    left["waiting"] = _dedupe(left["waiting"], drop_now=True)
    left["completed"] = _dedupe(left["completed"], drop_now=False)
    return left


def _is_understanding_card(card) -> bool:
    if card is None:
        return False
    return (
        getattr(card, "interrupt_reason", "") == "understanding"
        or (getattr(card, "meta", "") or "") == "understanding"
        or str(getattr(card, "id", "")).startswith("understanding:")
    )


def _need_you_guide(card) -> dict[str, Any]:
    if card.arbiter_state == "need_input":
        return {
            "id": card.id,
            "type": "QUESTION",
            "title": card.title,
            "prompt": card.why_now or card.ai_judgment,
            "explanation": card.ai_already_did,
            "choices": [{"id": a.kind, "label": a.label, "prompt": a.label} for a in card.actions[:4]],
            "actions": [a.model_dump(mode="json") for a in card.actions[:4]],
            "allow_free_text": True,
            "allow_file": False,
        }
    return {
        "id": card.id,
        "type": "APPROVAL",
        "title": card.title,
        "prompt": card.why_now,
        "explanation": card.ai_judgment,
        "success_metric": card.success_metric,
        "choices": [{"id": a.kind, "label": a.label, "prompt": a.label} for a in card.actions[:3]],
        "actions": [a.model_dump(mode="json") for a in card.actions[:3]],
        "allow_free_text": True,
    }


def _build_guide(
    queue,
    runtime_bridge_result=None,
    runtime_bridge_queue=None,
    decision_flow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建中栏 Guide（当前最高优先级 ODO / Gap / Goal / 决策流）。

    材料 §十六：Guide Type 只有 QUESTION/APPROVAL/FILE_REQUEST/PLAN_REVIEW/RESULT/PROGRESS/INFO。
    访谈 / MOS 缺口优先；高峰保护与静默时段不让增长类 bridge 抢戏。
    """
    from app.services.decision_flow import attach_decision_flow

    flow = decision_flow or {}
    flow_guide = flow.get("guide") or {}
    runtime_bridge_guide = _build_runtime_bridge_guide(runtime_bridge_result, runtime_bridge_queue)
    protect = bool(flow.get("protect_mode"))
    quiet = bool(flow.get("quiet"))
    human_types = {"QUESTION", "APPROVAL", "FILE_REQUEST"}

    def finish(guide: dict[str, Any]) -> dict[str, Any]:
        return attach_decision_flow(guide, flow) if flow else guide

    if queue.need_you and _is_understanding_card(queue.need_you[0]):
        return finish(_need_you_guide(queue.need_you[0]))

    now = flow.get("now") or {}
    now_id = str(now.get("id") or now.get("source_card_id") or "").strip()

    bridge_type = (runtime_bridge_guide or {}).get("type")
    bridge_reason = str((runtime_bridge_guide or {}).get("trigger_reason") or "").upper()
    bridge_is_anomaly = bridge_reason in {"ANOMALY", "GOAL_DEVIATION"}
    if (protect or quiet) and runtime_bridge_guide:
        if bridge_type in human_types and bridge_is_anomaly:
            return finish(runtime_bridge_guide)
        return finish(flow_guide or runtime_bridge_guide)

    # 有真实 Now 时，中栏 id 必须跟决策流一致，不被 runtime bridge 换掉
    if now_id and now.get("source_card_id") and flow_guide:
        return finish(flow_guide)
    if queue.need_you:
        return finish(_need_you_guide(queue.need_you[0]))
    if runtime_bridge_guide and bridge_type in human_types:
        return finish(runtime_bridge_guide)
    if flow_guide:
        return finish(flow_guide)
    if runtime_bridge_guide:
        return finish(runtime_bridge_guide)
    if queue.active_goal:
        return finish(
            {
                "type": "PROGRESS",
                "title": queue.active_goal.title,
                "prompt": queue.active_goal.ai_judgment or "持续推进中",
            }
        )
    return finish(
        {
            "type": "INFO",
            "title": "店我看着呢",
            "prompt": "目前一切正常，有需要你的我会出现。",
        }
    )


def _build_feed(queue, events, runtime_bridge_feed=None) -> list[dict[str, Any]]:
    """构建右栏 Proactive Feed（经营意义过滤后的 Event Projection）。

    材料 §十七：不是 Event Log 原样输出。
    """
    from app.services.copy_humanize import humanize_operator_text

    if runtime_bridge_feed and getattr(runtime_bridge_feed, "events", None):
        projected: list[dict[str, Any]] = []
        for event in runtime_bridge_feed.events[:8]:
            payload = event.event_payload or {}
            action = payload.get("selected_action") or {}
            projected.append(
                {
                    "id": event.id,
                    "reason": event.trigger_reason,
                    "domain": event.domain,
                    "summary": humanize_operator_text(event.title),
                    "finding": humanize_operator_text(event.detail or (event.evidence[0] if event.evidence else "")),
                    "decision": humanize_operator_text(action.get("title") or action.get("detail") or ""),
                    "action": humanize_operator_text(action.get("detail") or ""),
                    "status": event.status.upper(),
                    "occurred_at": event.occurred_at.isoformat() if hasattr(event.occurred_at, "isoformat") else str(event.occurred_at),
                    "business_impact": humanize_operator_text(event.detail or ""),
                    "source_odo_id": event.source_odo_id,
                }
            )
        if projected:
            return projected
    feed: list[dict[str, Any]] = []
    for card in (queue.working + queue.results + queue.opportunities)[:8]:
        feed.append({
            "id": card.id,
            "timestamp": card.meta or "",
            "reason": card.interrupt_reason,
            "domain": card.meta or "general",
            "headline": humanize_operator_text(card.title),
            "summary": humanize_operator_text(card.summary or card.ai_judgment or ""),
            "status": card.arbiter_state,
        })
    return feed


def _candidate_title(candidate) -> str:
    odo = candidate.odo
    raw = (
        odo.recommended_action.title
        or odo.object.name
        or odo.diagnosis.primary
        or odo.why_now
        or "经营任务"
    )
    return _humanize_candidate_title(raw)


def _humanize_candidate_title(text: str) -> str:
    from app.services.copy_humanize import humanize_operator_text

    return humanize_operator_text(text) or "经营任务"


def _candidate_prompt(candidate) -> str:
    odo = candidate.odo
    if odo.execution_mode == "ASK_INFORMATION":
        return odo.human_request or odo.human_reason or odo.why_now or "还需要你补一个信息。"
    if odo.execution_mode == "ASK_APPROVAL":
        return odo.recommended_action.title or odo.why_now or "这个方案需要你确认。"
    return f"关于「{_candidate_title(candidate)}」，现在进展怎样？"


def _build_runtime_bridge_guide(runtime_bridge_result=None, runtime_bridge_queue=None) -> dict[str, Any]:
    if not runtime_bridge_result or not runtime_bridge_result.candidate_odos:
        return {}
    ordered = runtime_bridge_result.candidate_odos
    if runtime_bridge_queue and getattr(runtime_bridge_queue, "items", None):
        priorities = {item.candidate_odo_id: item.priority_score for item in runtime_bridge_queue.items}
        ordered = sorted(
            runtime_bridge_result.candidate_odos,
            key=lambda candidate: priorities.get(candidate.id, 0),
            reverse=True,
        )
    candidate = ordered[0]
    odo = candidate.odo
    allow_file = any(
        token in key.lower()
        for key in odo.required_context_keys
        for token in ("file", "photo", "image", "sheet", "cost")
    )
    if odo.execution_mode == "ASK_INFORMATION":
        return {
            "id": candidate.id,
            "type": "FILE_REQUEST" if allow_file else "QUESTION",
            "title": _candidate_title(candidate),
            "prompt": odo.human_request or odo.human_reason or odo.why_now or "还差一个关键信息",
            "explanation": odo.business_impact.summary or odo.diagnosis.primary or odo.finding.primary,
            "allow_free_text": True,
            "allow_file": allow_file,
            "required_context_keys": odo.required_context_keys,
            "trigger_reason": candidate.trigger_reason,
            "source_odo_id": odo.id,
            "status": "需要你",
            "request_label": "现在需要你",
        }
    if odo.execution_mode == "ASK_APPROVAL":
        return {
            "id": candidate.id,
            "type": "APPROVAL",
            "title": _candidate_title(candidate),
            "prompt": odo.why_now or odo.diagnosis.primary or "我把方案收敛好了",
            "explanation": odo.recommended_action.detail or odo.business_impact.summary or odo.finding.primary,
            "allow_free_text": True,
            "allow_file": False,
            "trigger_reason": candidate.trigger_reason,
            "source_odo_id": odo.id,
            "status": "等你确认",
            "request_label": "现在需要你",
        }
    return {
        "id": candidate.id,
        "type": "PROGRESS" if odo.execution_mode in {"AUTO", "AUTO_AND_REPORT"} else "INFO",
        "title": _candidate_title(candidate),
        "prompt": odo.recommended_action.detail or odo.why_now or odo.diagnosis.primary or "我在继续推进",
        "explanation": odo.business_impact.summary or odo.success_metric.target or "",
        "allow_free_text": False,
        "allow_file": False,
        "trigger_reason": candidate.trigger_reason,
        "source_odo_id": odo.id,
        "status": "经营进展",
    }


@router.post("/stores/{store_id}/intent")
def post_intent(
    store_id: str,
    payload: IntentRequest,
    db: Session = Depends(get_db),
):
    """用户意图入口（材料 §十八）。

    不是普通聊天。走 Intent → Goal Parser → Plan Generator → Candidate ODO → POIE。
    """
    from app.services.ai_assist import answer_assist_question
    from app.services.agents import _load_store
    from app.services.poie import handle_user_intent
    from app.services.chief_agent import answer_as_chief

    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")

    # 第一道：产品引导
    assisted = answer_assist_question(payload.text, db=db, store=store)
    if assisted is not None:
        return {
            "mode": "assist",
            **assisted,
            "workspace": _build_workspace_payload(store_id, db),
            "daily_plan": _build_daily_plan_payload(store_id, db),
        }

    # 第二道：POIE Intent（Goal/Thread/NL 设置）
    intent_hit = handle_user_intent(db, store_id, payload.text)
    if intent_hit is not None:
        return {
            "mode": "intent",
            **intent_hit,
            "workspace": _build_workspace_payload(store_id, db),
            "daily_plan": _build_daily_plan_payload(store_id, db),
        }

    # 第三道：chief_agent（ReAct 调度）
    response = answer_as_chief(db, store_id, payload.text, days=7)
    return {
        "mode": "chief_agent",
        **response.model_dump(mode="json"),
        "workspace": _build_workspace_payload(store_id, db),
        "daily_plan": _build_daily_plan_payload(store_id, db),
    }


@router.post("/stores/{store_id}/runtime-bridge/preview")
def preview_runtime_bridge(
    store_id: str,
    payload: RuntimeBridgePreviewRequest,
    db: Session = Depends(get_db),
):
    """把 BusinessEvent 送入 Runtime Bridge runtime adapter，返回 POC 结果。

    这是给后端联调用的预览接口，不走前台三栏主链。
    """
    if payload.store_state.store_id != store_id or payload.business_event.store_id != store_id:
        raise HTTPException(status_code=400, detail="store_id mismatch")

    request = RuntimeBridgeRunRequest(
        store_state=payload.store_state,
        business_event=payload.business_event,
        merchant_context=payload.merchant_context,
        goal_text=payload.goal_text,
        question=payload.question,
        trigger_reason=payload.trigger_reason,  # type: ignore[arg-type]
        runtime_state=payload.runtime_state,  # type: ignore[arg-type]
        analysis_node=payload.analysis_node,  # type: ignore[arg-type]
        preferred_skills=payload.preferred_skills,  # type: ignore[arg-type]
        system_mode=payload.system_mode,  # type: ignore[arg-type]
    )
    return _preview_bridge_response(store_id, request, payload.business_event.event_id)


@router.get("/stores/{store_id}/runtime-bridge/current-preview")
def preview_current_runtime_bridge(
    store_id: str,
    fingerprint: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """直接用当前门店的 StoreState + Event 运行 Runtime Bridge preview。"""
    from app.services.agents import build_store_agents
    from app.services.event_engine import build_operating_events
    from app.services.event_decisions import apply_decision_overrides, load_decision_map
    from app.services.runtime_request_mapper import build_runtime_bridge_run_request, pick_primary_event

    agents = build_store_agents(db=db, store_id=store_id, days=7)
    if agents is None:
        raise HTTPException(status_code=404, detail="store not found")

    events = apply_decision_overrides(
        build_operating_events(agents.store_state),
        load_decision_map(db, store_id),
    ).events
    event = next((item for item in events if item.fingerprint == fingerprint), None) if fingerprint else None
    event = event or pick_primary_event(events)
    if event is None:
        raise HTTPException(status_code=404, detail="no operating event available")

    request = build_runtime_bridge_run_request(
        state=agents.store_state,
        event=event,
        goal_text="",
    )
    return _preview_bridge_response(store_id, request, event.id)
