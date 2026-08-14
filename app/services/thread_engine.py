"""Thread Engine — 经营线程的创建、推进、同步。

经营线程是可跨日/跨周持续推进的故事线。
不同于一次性任务,线程承载"午餐增长计划""牛肉饭做到前三"这种
需要持续多步推进的经营主线。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.thread import OperatingThread
from app.schemas.arbiter import OperatingThreadBrief


def _json_loads_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _json_dumps_list(rows: list[str]) -> str:
    return json.dumps([row for row in rows if row], ensure_ascii=False)


def _thread_to_brief(thread: OperatingThread) -> OperatingThreadBrief:
    return OperatingThreadBrief(
        id=thread.id,
        title=thread.title,
        goal=thread.goal_text,
        done=_json_loads_list(thread.done_json),
        doing=_json_loads_list(thread.doing_json),
        next_step=thread.next_step or "",
        current_result=thread.current_result or "",
        ai_judgment=thread.ai_judgment or "",
        needs_owner=thread.needs_owner,
    )


def create_thread(
    db: Session,
    store_id: str,
    title: str,
    goal_text: str,
    goal_id: str | None = None,
    *,
    thread_id: str | None = None,
) -> OperatingThread:
    """创建一个经营线程。"""
    thread = OperatingThread(
        id=thread_id or None,
        store_id=store_id,
        goal_id=goal_id,
        title=title,
        goal_text=goal_text,
        status="active",
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def ensure_thread_for_action(
    db: Session,
    store_id: str,
    action_title: str,
    *,
    goal_text: str | None = None,
    preferred_id: str | None = None,
) -> OperatingThread:
    """获取或创建门店的活跃经营线程,用于绑定 Recommendation/Experiment。

    策略:
    1. 如果门店已有 active 线程 → 复用(同一件事持续推进)
    2. 如果没有 → 创建一个新的

    这样所有进入执行流程的 Rec/Exp 都能绑定到 work_thread_id,
    实现三栏(左:发现 / 中:确认 / 右:执行)看的是同一件事。
    """
    preferred = str(preferred_id or "").strip()
    if preferred:
        existing = db.execute(
            select(OperatingThread).where(
                OperatingThread.store_id == store_id,
                OperatingThread.id == preferred,
            )
        ).scalar_one_or_none()
        if existing:
            return existing

    title = (action_title or "").strip()
    goal = (goal_text or action_title or "持续推进经营优化").strip()

    # 复用门店的任意活跃线程(同一门店同一时间推进同一件事)
    existing = db.execute(
        select(OperatingThread)
        .where(
            OperatingThread.store_id == store_id,
            OperatingThread.status == "active",
        )
        .order_by(OperatingThread.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if existing:
        return existing

    # 没有活跃线程 → 创建一个通用的
    return create_thread(
        db,
        store_id=store_id,
        title=title[:100] if title else "经营优化",
        goal_text=goal,
        thread_id=preferred or None,
    )


def update_thread_progress(
    db: Session,
    thread_id: str,
    *,
    done: list[str] | None = None,
    doing: list[str] | None = None,
    next_step: str | None = None,
    current_result: str | None = None,
    ai_judgment: str | None = None,
    needs_owner: bool | None = None,
) -> OperatingThread | None:
    """推进线程进度。"""
    thread = db.get(OperatingThread, thread_id)
    if thread is None:
        return None
    if done is not None:
        thread.done_json = json.dumps(done, ensure_ascii=False)
    if doing is not None:
        thread.doing_json = json.dumps(doing, ensure_ascii=False)
    if next_step is not None:
        thread.next_step = next_step
    if current_result is not None:
        thread.current_result = current_result
    if ai_judgment is not None:
        thread.ai_judgment = ai_judgment
    if needs_owner is not None:
        thread.needs_owner = needs_owner
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def load_active_threads(db: Session, store_id: str) -> list[OperatingThreadBrief]:
    """加载门店所有活跃线程。"""
    threads = list(
        db.execute(
            select(OperatingThread)
            .where(OperatingThread.store_id == store_id, OperatingThread.status == "active")
            .order_by(OperatingThread.created_at.desc())
        ).scalars()
    )
    return [_thread_to_brief(t) for t in threads]


def sync_threads_from_agents(
    db: Session,
    store_id: str,
    agents: Any,
) -> list[OperatingThreadBrief]:
    """从 agent 结果同步线程状态。

    如果有 active Goal 但没有对应线程，自动创建一个。
    已有线程的进度从 growth/strategy_memory 更新。
    """
    from app.models.goal import Goal

    # 找活跃 Goal
    goals = list(
        db.execute(
            select(Goal).where(Goal.store_id == store_id, Goal.status == "active")
        ).scalars()
    )

    for goal in goals:
        # 检查是否已有对应线程
        existing = db.execute(
            select(OperatingThread).where(
                OperatingThread.store_id == store_id,
                OperatingThread.goal_id == goal.id,
                OperatingThread.status == "active",
            )
        ).scalar_one_or_none()

        if existing is None:
            # 自动创建线程
            create_thread(
                db, store_id,
                title=goal.raw_text[:100],
                goal_text=goal.raw_text,
                goal_id=goal.id,
            )

    # 更新已有线程的进度（从 growth agent 取当前状态）
    threads = list(
        db.execute(
            select(OperatingThread)
            .where(OperatingThread.store_id == store_id, OperatingThread.status == "active")
        ).scalars()
    )

    growth = getattr(agents, "growth", None) if agents else None
    for thread in threads:
        doing: list[str] = []
        done: list[str] = []
        if growth:
            if growth.current_action:
                action = growth.current_action
                if action.execution_phase == "observe":
                    doing.append(f"{action.title}（观察中）")
                elif action.execution_phase == "execute_now":
                    doing.append(f"待启动：{action.title}")
            if growth.experiments_summary:
                positive = growth.experiments_summary.get("positive", 0)
                if positive:
                    done.append(f"已有 {positive} 条动作验证有效")

        # 简单更新（不覆盖已有内容，只在空时填充）
        if not thread.doing_json and doing:
            thread.doing_json = json.dumps(doing, ensure_ascii=False)
        if not thread.done_json and done:
            thread.done_json = json.dumps(done, ensure_ascii=False)
        if growth and growth.selected_opportunity and not thread.next_step:
            thread.next_step = f"当前推进：{growth.selected_opportunity.title}"
        if growth and not thread.ai_judgment:
            thread.ai_judgment = growth.learning_summary or "进度正常，暂时不需要你介入。"
        db.add(thread)

    db.commit()
    return load_active_threads(db, store_id)


def sync_loop_thread(db: Session, item: Any, *, pack: dict[str, Any] | None = None) -> OperatingThread:
    """把 Closed Loop 当前状态同步到 OperatingThread，保证 work_thread 可读。"""
    payload = pack if isinstance(pack, dict) else {}
    if not payload:
        try:
            payload = json.loads(getattr(item, "pack_json", "") or "{}")
        except json.JSONDecodeError:
            payload = {}

    thread = ensure_thread_for_action(
        db,
        item.store_id,
        getattr(item, "title", "") or "经营闭环",
        goal_text=getattr(item, "title", "") or "持续推进经营闭环",
        preferred_id=getattr(item, "id", None),
    )
    thread.title = getattr(item, "title", "") or thread.title
    thread.goal_text = getattr(item, "title", "") or thread.goal_text

    status = str(payload.get("thread_status") or "").strip().upper()
    writeback = payload.get("writeback") if isinstance(payload.get("writeback"), dict) else {}
    evidence_count = len(_evidence_rows(item))
    observe_hours = int(getattr(item, "observe_hours", 0) or payload.get("observe_hours") or 48)
    result = str(getattr(item, "result", "") or "").strip().lower()
    result_label = {
        "positive": "有效",
        "negative": "无效",
        "neutral": "变化不明显",
        "unknown": "待平台继续处理",
        "pending": "还在观察",
    }.get(result, "进行中")

    doing: list[str] = []
    done: list[str] = []
    current_result = ""
    next_step = ""
    needs_owner = False

    if evidence_count:
        done.append(f"已补 {evidence_count} 份证据")
    if writeback.get("ok") and writeback.get("summary"):
        done.append(str(writeback.get("summary")))
    if writeback.get("ok") is False and writeback.get("error"):
        current_result = f"执行未完成：{writeback.get('error')}"

    if status in {"NEED_APPROVAL", "READY_TO_EXECUTE", ""}:
        doing.append("待确认执行")
        current_result = current_result or (f"已补 {evidence_count} 份证据，待确认提交" if evidence_count else "")
        next_step = "确认并执行"
        needs_owner = True
    elif status in {"APPROVED", "EXECUTING"}:
        doing.append("正在执行")
        current_result = current_result or str(writeback.get("summary") or "执行中")
        next_step = "等待执行完成"
    elif status == "OBSERVING":
        doing.append(f"观察中 · {observe_hours} 小时")
        current_result = current_result or str(writeback.get("summary") or getattr(item, "notes", "") or "已进入观察窗")
        next_step = "等待结果"
    elif status == "WAITING_RESULT":
        doing.append("结果待确认")
        current_result = str(getattr(item, "notes", "") or writeback.get("summary") or f"结果：{result_label}")
        next_step = "确认结果并归档"
        needs_owner = True
    elif status in {"COMPLETED", "NO_EFFECT", "CANCELLED", "FAILED"}:
        summary = str(getattr(item, "notes", "") or current_result or f"结果：{result_label}")
        if summary:
            done.append(summary)
        current_result = summary
        next_step = ""

    if not current_result:
        current_result = str(getattr(item, "judgment", "") or getattr(item, "finding", "") or "")

    thread.done_json = _json_dumps_list(done) if done else None
    thread.doing_json = _json_dumps_list(doing) if doing else None
    thread.next_step = next_step or None
    thread.current_result = current_result or None
    thread.ai_judgment = str(getattr(item, "judgment", "") or getattr(item, "finding", "") or "") or None
    thread.needs_owner = needs_owner
    db.add(thread)
    db.flush()
    return thread


def _evidence_rows(item: Any) -> list[dict[str, Any]]:
    raw = getattr(item, "evidence_json", None)
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []
