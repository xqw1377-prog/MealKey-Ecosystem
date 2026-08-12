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
) -> OperatingThread:
    """创建一个经营线程。"""
    thread = OperatingThread(
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
