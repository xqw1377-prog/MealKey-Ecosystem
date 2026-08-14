"""Closed Loop Skeleton：一件事从发现走到已执行/观察/结果。

三栏都是同一条 ClosedLoopItem 的投影。
改标题可走平台工具写回：Permission → Tool Call → Read Back → 仍进入 mark_loop_executed。
写回失败则停在 now，老板仍可用「已修改」人工确认。
观察窗到期必须回来，不能把事项停在建议上。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.closed_loop import ClosedLoopItem
from app.models.entities import MenuItem
from app.models.ohre import Experiment, Recommendation
from app.services.action_registry import build_action_spec
from app.services.copy_humanize import humanize_operator_text
from app.services.execution_pack import pack_from_card
from app.services.operating_rhythm import local_now

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("now", "executed", "observing", "result_ready", "not_executed")
BLOCKING_NOW = ("executed", "observing", "result_ready")
ACTIVE_NOW = ("now",)
WAITING = ("executed", "observing")
CANONICAL_STATUSES = {
    "DISCOVERED",
    "ANALYZING",
    "NEED_INFORMATION",
    "NEED_APPROVAL",
    "READY_TO_EXECUTE",
    "EXECUTING",
    "OBSERVING",
    "WAITING_RESULT",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "NO_EFFECT",
}


def _json_load(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _pack_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _requires_approval(pack: dict[str, Any]) -> bool:
    action_spec = pack.get("action_spec") if isinstance(pack.get("action_spec"), dict) else {}
    return bool(action_spec.get("requires_approval", True))


def _canonical_status(item: ClosedLoopItem, pack: dict[str, Any]) -> str:
    packed = str(pack.get("thread_status") or "").strip().upper()
    if packed in CANONICAL_STATUSES:
        return packed
    status = str(item.status or "").strip()
    result = str(item.result or "").strip().lower()
    if status == "not_executed":
        return "CANCELLED"
    if status in {"executed"}:
        return "OBSERVING"
    if status == "observing":
        return "WAITING_RESULT"
    if status == "result_ready":
        if result in {"negative", "neutral"}:
            return "NO_EFFECT"
        return "COMPLETED"
    if status == "closed":
        if result in {"negative", "neutral"}:
            return "NO_EFFECT"
        return "COMPLETED"
    if status == "now":
        return "NEED_APPROVAL" if _requires_approval(pack) else "READY_TO_EXECUTE"
    return "READY_TO_EXECUTE"


def _thread_stage(item: ClosedLoopItem, pack: dict[str, Any]) -> str:
    packed = str(pack.get("thread_status") or "").strip().upper()
    if packed in CANONICAL_STATUSES:
        return packed
    status = str(item.status or "").strip()
    if status == "executed":
        return "OBSERVING"
    if status == "observing":
        return "WAITING_RESULT"
    if status == "result_ready":
        return "WAITING_RESULT"
    if status == "not_executed":
        return "CANCELLED"
    return "READY_TO_EXECUTE"


def _work_thread_id(db: Session, item: ClosedLoopItem) -> str:
    from app.services.thread_engine import ensure_thread_for_action

    thread = ensure_thread_for_action(
        db,
        item.store_id,
        item.title or "经营闭环",
        goal_text=item.title or "持续推进经营闭环",
        preferred_id=item.id,
    )
    return thread.id


def _sync_work_thread(db: Session, item: ClosedLoopItem, pack: dict[str, Any] | None = None) -> None:
    from app.services.thread_engine import sync_loop_thread

    sync_loop_thread(db, item, pack=pack)


def _thread_history(pack: dict[str, Any]) -> list[dict[str, Any]]:
    history = pack.get("thread_history")
    return history if isinstance(history, list) else []


def _append_thread_state(
    pack: dict[str, Any],
    state: str,
    *,
    at: datetime | None = None,
    note: str = "",
    executor: str = "",
) -> dict[str, Any]:
    name = str(state or "").strip().upper()
    if not name:
        return pack
    at = _aware(at) or _utcnow()
    history = [row for row in _thread_history(pack) if isinstance(row, dict)]
    last = history[-1] if history else {}
    if str(last.get("state") or "").upper() == name:
        if note and not last.get("note"):
            last["note"] = note
        if executor and not last.get("executor"):
            last["executor"] = executor
        last["at"] = at.isoformat()
        history[-1] = last
    else:
        row = {"state": name, "at": at.isoformat()}
        if note:
            row["note"] = note
        if executor:
            row["executor"] = executor
        history.append(row)
    pack["thread_history"] = history
    pack["thread_status"] = name
    pack["thread_status_updated_at"] = at.isoformat()
    return pack


def _fingerprint(store_id: str, now: dict[str, Any], action_type: str) -> str:
    source = str(now.get("source_card_id") or now.get("id") or "").strip()
    if source:
        return f"{store_id}:{source}"
    day = local_now().strftime("%Y-%m-%d")
    title = humanize_operator_text(now.get("title") or "now")[:40]
    return f"{store_id}:{action_type}:{title}:{day}"


def _related_event(now: dict[str, Any], events) -> Any:
    event_list = getattr(events, "events", None) or []
    if not event_list:
        return None
    blob = f"{now.get('title') or ''} {now.get('why_now') or ''} {now.get('business_impact') or ''}"
    action = (
        str(((now.get("execution_pack") or {}).get("action_type") or "")).strip()
        if isinstance(now.get("execution_pack"), dict)
        else ""
    )
    for event in event_list:
        et = str(getattr(event, "event_type", "") or "")
        title = str(getattr(event, "title", "") or "")
        if action == "change_main_image" and et in {"CTR_DROP"}:
            return event
        if action == "change_title" and et in {"CTR_DROP", "CVR_DROP"}:
            return event
        if action == "batch_reply_negative_reviews" and et in {"RATING_DROP"}:
            return event
        if action == "reply_ordinary_reviews" and et in {"RATING_DROP", "REVIEW_BACKLOG"}:
            return event
        if title and title in blob:
            return event
    return event_list[0] if event_list else None


def ensure_now_loop(
    db: Session,
    store_id: str,
    *,
    decision_flow: dict[str, Any],
    events=None,
) -> Optional[ClosedLoopItem]:
    blocking = _latest_blocking_loop(db, store_id)
    if blocking is not None:
        return blocking
    ingest_now = _latest_ingest_now(db, store_id)
    if ingest_now is not None:
        return ingest_now

    now = (decision_flow or {}).get("now") or {}
    if not now.get("title") or not now.get("source_card_id"):
        return _latest_open_loop(db, store_id)
    pack = now.get("execution_pack") if isinstance(now.get("execution_pack"), dict) else pack_from_card(now)
    if not pack:
        pack = pack_from_card(now) or {}
    if not pack.get("action_spec"):
        pack["action_spec"] = build_action_spec(
            str(pack.get("action_type") or "ops_hint"),
            object_name=str(pack.get("object_name") or ""),
            title=str(pack.get("title") or now.get("title") or ""),
            pack=pack,
            reason=str(now.get("ai_already_did") or now.get("why_now") or ""),
        )
    action_type = str(pack.get("action_type") or "ops_hint")
    fp = _fingerprint(store_id, now, action_type)
    item = db.execute(
        select(ClosedLoopItem)
        .where(ClosedLoopItem.store_id == store_id, ClosedLoopItem.fingerprint == fp)
        .order_by(ClosedLoopItem.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    event = _related_event(now, events)
    finding = humanize_operator_text(
        (getattr(event, "estimated_impact", None) or getattr(event, "detail", None) or now.get("why_now") or "")
        if event is not None
        else (now.get("why_now") or now.get("business_impact") or "")
    )
    judgment = humanize_operator_text(now.get("ai_already_did") or now.get("why_now") or pack.get("current_problem") or "")
    title = humanize_operator_text(now.get("title") or pack.get("title") or "当前经营事项")
    if str(pack.get("execution_mode") or "").upper() == "HUMAN_TASK":
        spec = pack.get("action_spec") if isinstance(pack.get("action_spec"), dict) else {}
        spec["requires_approval"] = False
        spec["execution_method"] = "store_execute"
        pack["action_spec"] = spec
        pack["requires_approval"] = False
    initial_thread_status = "NEED_APPROVAL" if _requires_approval(pack) else "READY_TO_EXECUTE"
    _append_thread_state(pack, initial_thread_status, note="这件经营事项进入当前工作区。")
    due_hours = int(pack.get("due_hours") or 8)
    due_at = _utcnow() + timedelta(hours=due_hours) if str(pack.get("execution_mode") or "").upper() == "HUMAN_TASK" else None
    if item is None or item.status == "closed":
        item = ClosedLoopItem(
            store_id=store_id,
            fingerprint=fp,
            source_card_id=str(now.get("source_card_id") or now.get("id") or ""),
            source_event_id=str(getattr(event, "id", "") or ""),
            title=title,
            finding=finding,
            judgment=judgment,
            action_type=action_type,
            object_name=str(pack.get("object_name") or pack.get("title") or "")[:80],
            pack_json=_pack_dump(pack),
            status="now",
            execution_mode=str(pack.get("execution_mode") or "")[:24],
            assignee_name=str(pack.get("assignee_name") or "")[:80],
            assignee_role=str(pack.get("assignee_role") or ("manager" if pack.get("execution_mode") == "HUMAN_TASK" else ""))[:24],
            due_at=due_at,
            observe_hours=int(pack.get("observe_hours") or 48),
            success_metric=str(pack.get("success_metric") or "点击率"),
            success_target=str(pack.get("success_target") or ""),
            guardrail=str(pack.get("guardrail") or ""),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        _work_thread_id(db, item)
        _sync_work_thread(db, item, pack)
        db.commit()
        return item
    if item.status == "not_executed":
        item.status = "now"
        item.notes = "上次还没改，这件事重新回到现在。"
        item.result = "pending"
    if item.status in ACTIVE_NOW:
        item.title = title
        item.finding = finding or item.finding
        item.judgment = judgment or item.judgment
        item.pack_json = _pack_dump(pack)
        item.action_type = action_type
        item.success_metric = str(pack.get("success_metric") or item.success_metric)
        item.success_target = str(pack.get("success_target") or item.success_target)
        item.guardrail = str(pack.get("guardrail") or item.guardrail)
        if event is not None and not item.source_event_id:
            item.source_event_id = str(getattr(event, "id", "") or "")
        db.commit()
        db.refresh(item)
        _work_thread_id(db, item)
        _sync_work_thread(db, item, pack)
        db.commit()
    return item


def _latest_open_loop(db: Session, store_id: str) -> Optional[ClosedLoopItem]:
    return db.execute(
        select(ClosedLoopItem)
        .where(ClosedLoopItem.store_id == store_id, ClosedLoopItem.status.in_(OPEN_STATUSES))
        .order_by(ClosedLoopItem.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _latest_ingest_now(db: Session, store_id: str) -> Optional[ClosedLoopItem]:
    return db.execute(
        select(ClosedLoopItem)
        .where(
            ClosedLoopItem.store_id == store_id,
            ClosedLoopItem.status == "now",
            ClosedLoopItem.source_card_id.startswith("ingest:"),
        )
        .order_by(ClosedLoopItem.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _latest_blocking_loop(db: Session, store_id: str) -> Optional[ClosedLoopItem]:
    return db.execute(
        select(ClosedLoopItem)
        .where(ClosedLoopItem.store_id == store_id, ClosedLoopItem.status.in_(BLOCKING_NOW))
        .order_by(ClosedLoopItem.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_loop(db: Session, store_id: str, loop_id: str) -> Optional[ClosedLoopItem]:
    item = db.get(ClosedLoopItem, loop_id)
    if item is None or item.store_id != store_id:
        return None
    return item


def mark_loop_executed(
    db: Session,
    store_id: str,
    loop_id: str,
    *,
    executor: str = "OWNER",
    notes: str | None = None,
) -> ClosedLoopItem:
    item = get_loop(db, store_id, loop_id)
    if item is None:
        raise ValueError("loop not found")
    from app.services.store_ops import is_human_task, require_evidence

    if is_human_task(item):
        require_evidence(item)
        if executor == "OWNER":
            executor = "STORE"
    now = _utcnow()
    hours = item.observe_hours or 48
    pack = _json_load(item.pack_json)
    if _requires_approval(pack):
        _append_thread_state(pack, "APPROVED", at=now, note="老板确认按这条方案执行。", executor=executor or "OWNER")
    _append_thread_state(pack, "EXECUTING", at=now, note="动作已执行，进入观察窗。", executor=executor or "OWNER")
    _append_thread_state(pack, "OBSERVING", at=now, note="观察窗已开启，正在等待结果。", executor=executor or "OWNER")
    item.status = "observing"
    item.executed_at = now
    item.executor = executor or "OWNER"
    item.observe_until = now + timedelta(hours=hours)
    item.result = "pending"
    item.pack_json = _pack_dump(pack)
    if notes:
        item.notes = notes
    rec = _ensure_recommendation(db, item)
    item.recommendation_id = rec.id
    if rec.adopted_at is None:
        rec.adopted_at = now
    rec.status = "executed"
    rec.executed_at = now
    experiment = _ensure_experiment(db, rec, item, executor=item.executor)
    item.experiment_id = experiment.id
    _sync_work_thread(db, item, pack)
    db.commit()
    db.refresh(item)
    return item


def execute_loop_platform_writeback(db: Session, store_id: str, loop_id: str) -> ClosedLoopItem:
    """老板确认后：工具写回平台，读回成功才进入观察窗。失败不改 loop 状态。"""
    from app.services.platform_write import (
        ReadBackMismatchError,
        WriteFailedError,
        WritePermissionError,
        execute_confirmed_writeback,
    )

    item = get_loop(db, store_id, loop_id)
    if item is None:
        raise ValueError("loop not found")
    if item.status != "now":
        raise ValueError("这件事不在「现在」，不能再写回平台")
    pack = _json_load(item.pack_json)
    try:
        result = execute_confirmed_writeback(db, store_id, item, pack)
    except (WriteFailedError, ReadBackMismatchError, WritePermissionError) as exc:
        _attach_writeback(item, {"ok": False, "error": str(exc), "op": item.action_type})
        _sync_work_thread(db, item)
        db.commit()
        raise
    _attach_writeback(item, result.as_pack())
    if result.mode == "human_paste":
        _sync_work_thread(db, item)
        db.commit()
        db.refresh(item)
        return item
    return mark_loop_executed(
        db,
        store_id,
        loop_id,
        executor="PLATFORM",
        notes=result.summary,
    )


def _attach_writeback(item: ClosedLoopItem, payload: dict[str, Any]) -> None:
    pack = _json_load(item.pack_json)
    pack["writeback"] = payload
    item.pack_json = _pack_dump(pack)


def mark_loop_not_executed(db: Session, store_id: str, loop_id: str) -> ClosedLoopItem:
    item = get_loop(db, store_id, loop_id)
    if item is None:
        raise ValueError("loop not found")
    from app.services.store_ops import is_human_task

    pack = _json_load(item.pack_json)
    _append_thread_state(pack, "CANCELLED", note="老板确认这一次先不执行。", executor=item.executor or "OWNER")
    item.status = "not_executed"
    item.notes = "老板确认这一次门店先不做。" if is_human_task(item, pack) else "老板确认这一次还没在平台上改。"
    item.executed_at = None
    item.observe_until = None
    item.pack_json = _pack_dump(pack)
    _sync_work_thread(db, item, pack)
    db.commit()
    db.refresh(item)
    return item


def mark_loop_acked(db: Session, store_id: str, loop_id: str) -> ClosedLoopItem:
    item = get_loop(db, store_id, loop_id)
    if item is None:
        raise ValueError("loop not found")
    pack = _json_load(item.pack_json)
    final_state = "NO_EFFECT" if str(item.result or "").lower() in {"negative", "neutral"} else "COMPLETED"
    _append_thread_state(pack, final_state, note="老板已看过这次结果。", executor=item.executor or "OWNER")
    item.status = "closed"
    if not item.notes:
        item.notes = "老板已看过这次结果。"
    item.pack_json = _pack_dump(pack)
    _sync_work_thread(db, item, pack)
    db.commit()
    db.refresh(item)
    return item


def tick_observing_loops(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """观察窗到期：同一件事必须回到「结果出来了」。"""
    now = _aware(now) or _utcnow()
    due = list(
        db.execute(
            select(ClosedLoopItem).where(
                ClosedLoopItem.status.in_(("observing", "executed")),
                ClosedLoopItem.observe_until.is_not(None),
            )
        ).scalars()
    )
    ready: list[str] = []
    for item in due:
        until = _aware(item.observe_until)
        if until is None or until > now:
            continue
        _close_observation(db, item)
        ready.append(item.id)
    if ready:
        db.commit()
        for loop_id in ready:
            item = db.get(ClosedLoopItem, loop_id)
            if item is not None:
                db.refresh(item)
    return {"checked": len(due), "ready": ready}


def _close_observation(db: Session, item: ClosedLoopItem) -> None:
    now = _utcnow()
    result = "unknown"
    pack = _json_load(item.pack_json)
    writeback = pack.get("writeback") if isinstance(pack.get("writeback"), dict) else {}
    summary = (
        f"观察窗已到。成功标准：{item.success_metric or '经营结果'}"
        f"{(' ' + item.success_target) if item.success_target else ''}。"
        f"护栏：{item.guardrail or '不要叠改其他变量'}。"
        "请对照平台数据确认这次有没有效。"
    )
    lift_pct = None
    from app.services.store_ops import is_human_task, verify_ops_result

    if is_human_task(item):
        result, summary, lift_pct = verify_ops_result(db, item)
        experiment = db.get(Experiment, item.experiment_id) if item.experiment_id else None
        if experiment is not None:
            experiment.result = result
            if lift_pct is not None:
                experiment.lift_pct = lift_pct
            experiment.notes = summary
            try:
                from app.services.strategy_memory import upsert_strategy_memory_from_experiment

                if result in {"positive", "negative", "neutral"}:
                    upsert_strategy_memory_from_experiment(db, experiment)
            except Exception as exc:  # noqa: BLE001
                logger.warning("human task memory write failed for %s: %s", item.id, exc)
    else:
        experiment = db.get(Experiment, item.experiment_id) if item.experiment_id else None
        if experiment is not None:
            if experiment.result in {None, "pending"}:
                try:
                    from app.services.experiment_attribution import evaluate_experiment

                    outcome = evaluate_experiment(db, experiment, days=7)
                    result = str(outcome.result or experiment.result or "unknown")
                    if outcome.lift_pct is not None:
                        lift_pct = float(outcome.lift_pct)
                        summary = (
                            f"观察窗已到。{item.success_metric or '指标'}变化 "
                            f"{outcome.lift_pct:+.1f}%。结果：{_result_label(result)}。"
                        )
                    elif outcome.skipped:
                        summary = f"观察窗已到。还没有足够读数自动判定，先记为待确认。{outcome.reason or ''}"
                except Exception as exc:  # noqa: BLE001
                    logger.warning("loop experiment evaluate failed for %s: %s", item.id, exc)
                    result = experiment.result or "unknown"
            else:
                result = experiment.result
                if experiment.lift_pct is not None:
                    lift_pct = float(experiment.lift_pct)
                    summary = (
                        f"观察窗已到。{item.success_metric or '指标'}变化 "
                        f"{experiment.lift_pct:+.1f}%。结果：{_result_label(result)}。"
                    )
    if item.action_type == "appeal_pack" and writeback.get("ok"):
        result = "unknown"
        ticket_id = str(writeback.get("ticket_id") or writeback.get("external_ref") or "").strip()
        evidence_count = int(writeback.get("evidence_count") or 0)
        summary = (
            f"申诉工单 {ticket_id or '已提交'} 已读回确认。"
            f"{f' 本次附了 {evidence_count} 份证据。' if evidence_count else ''}"
            "平台最终处理结果还没自动接入，先记为待继续跟进。"
        )
    _append_thread_state(pack, "WAITING_RESULT", at=now, note="观察窗已结束，等待老板确认结果。", executor=item.executor or "OWNER")
    item.status = "result_ready"
    item.result = result or "unknown"
    item.notes = humanize_operator_text(summary)
    if lift_pct is not None:
        pack["lift_pct"] = lift_pct
    item.pack_json = _pack_dump(pack)
    _sync_work_thread(db, item, pack)
    from app.services.commercial.growth import maybe_mint_result_card

    maybe_mint_result_card(db, item, lift_pct=lift_pct)
    try:
        from app.services.notification_service import notify_store_owner

        notify_store_owner(
            db,
            store_id=item.store_id,
            notification_type="experiment_result",
            title=(
                f"还不能自动判定：{item.title}"
                if result in {"unknown", "pending"}
                else f"结果出来了：{item.title}"
            ),
            body=item.notes or summary,
            priority="normal",
            related_decision_id=item.id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("loop result notify failed for %s: %s", item.id, exc)


def _result_label(result: str) -> str:
    return {
        "positive": "有效",
        "negative": "无效",
        "neutral": "变化不明显",
        "unknown": "还不能自动判定",
        "pending": "还在等数据",
    }.get(result, result or "待确认")


def _ensure_recommendation(db: Session, item: ClosedLoopItem) -> Recommendation:
    if item.recommendation_id:
        rec = db.get(Recommendation, item.recommendation_id)
        if rec is not None:
            return rec
    rec = Recommendation(
        store_id=item.store_id,
        scope="store",
        object_ref=f"loop:{item.id}",
        action_type=item.action_type or "ops_hint",
        expected_metric=_metric_key(item.success_metric),
        window_hours=item.observe_hours or 48,
        rollback_rule=item.guardrail or "",
        confidence=0.78,
        status="adopted",
        content_json=item.pack_json,
        adopted_at=_utcnow(),
    )
    db.add(rec)
    db.flush()

    # 绑定 work_thread_id
    from app.services.thread_engine import ensure_thread_for_action
    thread = ensure_thread_for_action(
        db,
        item.store_id,
        item.title or "经营闭环",
        goal_text=item.title or "持续推进经营闭环",
        preferred_id=item.id,
    )
    rec.work_thread_id = thread.id
    db.flush()
    return rec


def _ensure_experiment(
    db: Session,
    rec: Recommendation,
    item: ClosedLoopItem,
    *,
    executor: str = "OWNER",
) -> Experiment:
    existing = db.execute(
        select(Experiment).where(Experiment.recommendation_id == rec.id).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        existing.result = existing.result or "pending"
        existing.notes = existing.notes or "已执行，进入观察窗。"
        existing.executor = existing.executor or executor
        if not existing.item_id:
            existing.item_id = _resolve_item_id(db, item)
        return existing
    start = (_aware(item.executed_at) or _utcnow()).date()
    end = (_aware(item.observe_until) or _utcnow() + timedelta(hours=48)).date()
    via_platform = executor == "PLATFORM"
    experiment = Experiment(
        recommendation_id=rec.id,
        store_id=item.store_id,
        work_thread_id=rec.work_thread_id,
        observe_from=start,
        observe_to=end,
        control_desc=(
            "平台工具写回后读回确认，MealKey 进入观察窗。"
            if via_platform
            else "人工在平台执行，MealKey 记录执行并等待观察窗。"
        ),
        attribution_quality="medium",
        result="pending",
        notes=f"观察 {item.observe_hours or 48} 小时。成功：{item.success_metric} {item.success_target}。护栏：{item.guardrail}",
        success_metric_json=json.dumps(
            {"metric": item.success_metric, "target": item.success_target},
            ensure_ascii=False,
        ),
        guardrails_json=json.dumps({"text": item.guardrail}, ensure_ascii=False),
        executor=executor,
        primary_variable=_primary_variable(item.action_type),
        item_id=_resolve_item_id(db, item),
    )
    db.add(experiment)
    db.flush()
    return experiment


def _resolve_item_id(db: Session, item: ClosedLoopItem) -> Optional[str]:
    ref = str(getattr(item, "object_ref", "") or "").strip()
    if ref.startswith("item:"):
        candidate = ref.split(":", 1)[1].strip()
        if candidate and db.get(MenuItem, candidate) is not None:
            return candidate
    name = str(item.object_name or "").strip()
    if not name:
        return None
    rows = db.execute(select(MenuItem).where(MenuItem.store_id == item.store_id)).scalars().all()
    for menu_item in rows:
        version = menu_item.current_version
        if version and str(version.name or "").strip() == name:
            return menu_item.id
    return None


def _metric_key(label: str) -> str:
    text = humanize_operator_text(label)
    if "转化" in text:
        return "cvr"
    if "评分" in text:
        return "rating"
    if "订单" in text:
        return "orders"
    return "ctr"


def _primary_variable(action_type: str) -> str:
    return {
        "change_main_image": "image",
        "change_title": "title",
        "batch_reply_negative_reviews": "reply",
        "reply_ordinary_reviews": "reply",
    }.get(action_type, "ops")


def _left_slot(thread_status: str) -> str:
    status = str(thread_status or "").strip().upper()
    if status in {"APPROVED", "EXECUTING", "ANALYZING"}:
        return "active"
    if status == "OBSERVING":
        return "waiting"
    if status in {"COMPLETED", "NO_EFFECT", "CANCELLED", "FAILED"}:
        return "done"
    return "need"


def _left_meta(thread_status: str, item: ClosedLoopItem) -> str:
    status = str(thread_status or "").strip().upper()
    return {
        "DISCOVERED": "新发现",
        "ANALYZING": "分析中",
        "NEED_INFORMATION": "等你补信息",
        "NEED_APPROVAL": "需要你确认",
        "READY_TO_EXECUTE": "待执行",
        "APPROVED": "已确认",
        "EXECUTING": "正在执行",
        "OBSERVING": f"等待结果 · {item.observe_hours or 48} 小时",
        "WAITING_RESULT": "结果出来了",
        "COMPLETED": "已完成",
        "NO_EFFECT": "已归档",
        "CANCELLED": "这次未执行",
        "FAILED": "执行失败",
    }.get(status, "进行中")


def _center_type(thread_status: str) -> str:
    status = str(thread_status or "").strip().upper()
    if status in {"WAITING_RESULT", "COMPLETED", "NO_EFFECT"}:
        return "RESULT"
    if status in {"APPROVED", "EXECUTING", "OBSERVING", "ANALYZING"}:
        return "PROGRESS"
    return "APPROVAL"


def _center_status(thread_status: str, item: ClosedLoopItem) -> str:
    status = str(thread_status or "").strip().upper()
    return {
        "DISCOVERED": "刚发现这件事",
        "ANALYZING": "MealKey 正在分析",
        "NEED_INFORMATION": "还差关键信息",
        "NEED_APPROVAL": "现在需要你确认执行",
        "READY_TO_EXECUTE": "执行包已准备好",
        "APPROVED": "老板已确认，准备执行",
        "EXECUTING": "动作正在执行",
        "OBSERVING": f"观察中 · {item.observe_hours or 48} 小时",
        "WAITING_RESULT": "结果出来了",
        "COMPLETED": "这条闭环已完成",
        "NO_EFFECT": "结果已归档",
        "CANCELLED": "这次先不执行",
        "FAILED": "执行失败",
    }.get(status, "进行中")


def _right_status(thread_status: str) -> str:
    status = str(thread_status or "").strip().upper()
    if status in {"WAITING_RESULT", "COMPLETED", "NO_EFFECT"}:
        return "RESULT"
    if status in {"APPROVED", "EXECUTING", "OBSERVING", "ANALYZING"}:
        return "OBSERVE"
    if status in {"CANCELLED", "FAILED"}:
        return "ARCHIVED"
    return "need_you"


def project_loop(item: ClosedLoopItem) -> dict[str, Any]:
    from app.services.platform_write import is_platform_writeable

    pack = _json_load(item.pack_json)
    if not pack.get("action_spec"):
        pack["action_spec"] = build_action_spec(
            item.action_type,
            object_name=item.object_name or item.title,
            title=pack.get("title") or item.title,
            pack=pack,
            reason=item.judgment or item.finding,
        )
    status = item.status
    if status == "executed":
        status = "observing"
    work_thread_id = item.id
    thread_status = _canonical_status(item, pack)
    thread_stage = _thread_stage(item, pack)
    waiting = thread_status == "OBSERVING"
    result_ready = thread_status == "WAITING_RESULT"
    left_slot = _left_slot(thread_status)
    left_meta = _left_meta(thread_status, item)
    center_status = _center_status(thread_status, item)
    center_type = _center_type(thread_status)
    right_status = _right_status(thread_status)
    from app.services.store_ops import evidence_list, has_evidence, is_human_task

    human_task = is_human_task(item, pack)
    from app.core.config import settings

    writeback_mode = str((pack.get("writeback") or {}).get("mode") or "")
    if not writeback_mode:
        writeback_mode = (
            "http"
            if str(settings.platform_connector_url or "").strip()
            else ("mock" if settings.is_dev else "human_paste")
        )
    platform_writeable = (
        is_platform_writeable(item.action_type)
        and thread_status in {"NEED_APPROVAL", "READY_TO_EXECUTE"}
        and not human_task
        and writeback_mode != "human_paste"
    )
    return {
        "id": item.id,
        "fingerprint": item.fingerprint,
        "source_card_id": item.source_card_id,
        "source_event_id": item.source_event_id,
        "title": item.title,
        "finding": item.finding,
        "judgment": item.judgment,
        "action_type": item.action_type,
        "status": status,
        "legacy_status": status,
        "work_thread_id": work_thread_id,
        "thread_status": thread_status,
        "thread_stage": thread_stage,
        "waiting": waiting,
        "result_ready": result_ready,
        "executed_at": item.executed_at.isoformat() if item.executed_at else "",
        "observe_hours": item.observe_hours,
        "observe_until": item.observe_until.isoformat() if item.observe_until else "",
        "success_metric": item.success_metric,
        "success_target": item.success_target,
        "guardrail": item.guardrail,
        "recommendation_id": item.recommendation_id or "",
        "experiment_id": item.experiment_id or "",
        "result": item.result,
        "result_summary": humanize_operator_text(item.notes or ""),
        "share_card": pack.get("share_card"),
        "executor": item.executor or "OWNER",
        "execution_mode": item.execution_mode or pack.get("execution_mode") or "",
        "human_task": human_task,
        "assignee_name": item.assignee_name or pack.get("assignee_name") or "",
        "assignee_role": item.assignee_role or "",
        "due_at": item.due_at.isoformat() if item.due_at else "",
        "has_evidence": has_evidence(item),
        "evidence": evidence_list(item),
        "evidence_needed": pack.get("evidence_needed") or "",
        "task_url": pack.get("task_url") or "",
        "platform_writeable": platform_writeable,
        "writeback_mode": writeback_mode,
        "execution_pack": pack,
        "action_spec": pack.get("action_spec") or {},
        "thread_history": _thread_history(pack),
        "left": {
            "id": item.id,
            "work_thread_id": work_thread_id,
            "kind": "loop",
            "slot": left_slot,
            "title": item.title,
            "meta": left_meta,
            "thread_status": thread_status,
            "summary": item.finding or item.judgment,
            "work": "ask" if left_slot in {"active", "waiting", "done"} else "need",
            "prompt": f"关于「{item.title}」，现在怎样了？",
        },
        "center": {
            "id": item.id,
            "work_thread_id": work_thread_id,
            "type": center_type,
            "title": item.title,
            "prompt": item.notes or item.judgment or item.finding,
            "explanation": item.finding,
            "status": center_status,
            "thread_status": thread_status,
            "execution_pack": pack,
            "action_spec": pack.get("action_spec") or {},
        },
        "right": {
            "id": item.id,
            "work_thread_id": work_thread_id,
            "reason": "RESULT" if result_ready else "ANOMALY",
            "summary": item.title,
            "finding": item.finding,
            "decision": item.notes or item.judgment,
            "status": right_status,
            "thread_status": thread_status,
            "occurred_at": (item.created_at.isoformat() if item.created_at else ""),
        },
    }


def apply_loop_to_workspace(payload: dict[str, Any], loop: ClosedLoopItem | None) -> dict[str, Any]:
    if loop is None:
        return payload
    projected = project_loop(loop)
    loop_id = projected["id"]
    flow = ((payload.get("center") or {}).get("decision_flow") or {})
    now = flow.get("now") or {}
    if now:
        now["id"] = loop_id
        now["loop_id"] = loop_id
        now["work_thread_id"] = projected["work_thread_id"]
        now["action_spec"] = projected["action_spec"]
        flow["now"] = now
    guide = (payload.get("center") or {}).get("guide") or {}
    guide["id"] = loop_id
    guide["work_thread_id"] = projected["work_thread_id"]
    guide["execution_pack"] = projected["execution_pack"]
    guide["action_spec"] = projected["action_spec"]
    payload.setdefault("center", {})
    payload["center"]["guide"] = guide
    payload["center"]["decision_flow"] = flow
    payload["center"]["loop"] = projected
    payload["center"]["active_thread_id"] = projected["work_thread_id"]

    left = payload.setdefault("left", {})
    left_item = projected["left"]
    same_ids = {loop_id, loop.source_card_id, loop.source_event_id}

    def _same_matter(row: dict[str, Any]) -> bool:
        iid = str(row.get("id") or "")
        related = str(row.get("related_now_id") or row.get("source_card_id") or "")
        return iid in same_ids or related in same_ids

    need = [row for row in (left.get("need_you") or []) if not _same_matter(row)]
    active = [row for row in (left.get("active") or []) if not _same_matter(row)]
    waiting = [row for row in (left.get("waiting") or []) if not _same_matter(row)]
    done = [row for row in (left.get("completed") or []) if not _same_matter(row)]
    slot = str(left_item.get("slot") or "").strip()
    if slot == "waiting":
        waiting = [left_item] + waiting
    elif slot == "active":
        active = [left_item] + active
    elif slot == "done":
        done = [left_item] + done
    else:
        need = [left_item] + need
    left["need_you"] = need
    left["active"] = active
    left["waiting"] = waiting
    left["completed"] = done

    right = payload.setdefault("right", {})
    feed = [
        row
        for row in (right.get("proactive_feed") or [])
        if str(row.get("id") or "") not in {loop_id, loop.source_event_id, loop.source_card_id}
    ]
    right["proactive_feed"] = [projected["right"]] + feed
    return payload
