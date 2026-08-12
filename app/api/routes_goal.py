"""Goal CRUD 路由 — 老板设定长期经营目标。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.goal import Goal
from app.schemas.goal import GoalCreateRequest, GoalSnapshot, GoalView
from app.services.goal_engine import (
    _goal_to_view,
    create_goal,
    load_goal_snapshot,
    update_goal_progress,
)

router = APIRouter()


@router.get("/stores/{store_id}/goals", response_model=GoalSnapshot)
def list_goals(store_id: str, db: Session = Depends(get_db)):
    """列出门店所有目标。"""
    return load_goal_snapshot(db, store_id)


@router.post("/stores/{store_id}/goals", response_model=GoalView)
def create_store_goal(
    store_id: str,
    request: GoalCreateRequest,
    db: Session = Depends(get_db),
):
    """创建一个长期目标。

    老板说"牛肉饭做到前三"或"本月 20 万"，AI 记住并持续推进。
    """
    goal = create_goal(db, store_id, request)
    try:
        update_goal_progress(db, store_id, days=7)
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.thread_engine import create_thread, load_active_threads

        existing = [
            t
            for t in load_active_threads(db, store_id)
            if t.goal == goal.raw_text or t.title == goal.raw_text[:100]
        ]
        if not existing:
            create_thread(
                db,
                store_id,
                title=goal.raw_text[:100],
                goal_text=goal.raw_text,
                goal_id=goal.id,
            )
    except Exception:  # noqa: BLE001
        pass
    return _goal_to_view(goal)


@router.post("/stores/{store_id}/goals/sync", response_model=dict)
def sync_goal_progress(
    store_id: str,
    days: int = Query(default=7, ge=1),
    db: Session = Depends(get_db),
):
    """同步目标进度（AI 从经营数据回填当前值 + 算 gap）。"""
    updated = update_goal_progress(db, store_id, days=days)
    snapshot = load_goal_snapshot(db, store_id)
    return {
        "store_id": store_id,
        "updated": updated,
        "deviation_count": len(snapshot.deviation_alerts),
        "deviations": [g.model_dump(mode="json") for g in snapshot.deviation_alerts],
    }


@router.patch("/stores/{store_id}/goals/{goal_id}", response_model=GoalView)
def update_goal_status(
    store_id: str,
    goal_id: str,
    status: str = Query(...),
    db: Session = Depends(get_db),
):
    """更新目标状态（active/achieved/abandoned）。"""
    goal = db.get(Goal, goal_id)
    if goal is None or goal.store_id != store_id:
        raise HTTPException(status_code=404, detail="goal not found")
    if status not in {"active", "achieved", "abandoned"}:
        raise HTTPException(status_code=400, detail="status must be active/achieved/abandoned")
    goal.status = status
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return _goal_to_view(goal)
