"""POIE 主入口：Trigger 产物 → 仲裁 → 首页经营队列投影。

Agent 是手脚；StoreState 是感官；Memory 是经验；本引擎是大脑。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.schemas.agents import StoreAgentsResponse
from app.schemas.arbiter import OpsQueueBrief
from app.schemas.events import EventEngineResult
from app.schemas.poie import Goal, PoieRunResult, WorkThread
from app.schemas.strategy_memory import StrategyMemorySnapshot
from app.schemas.store_state import ManagerHomeBrief
from app.services.poie.arbitrate import merge_candidates_into_queue
from app.services.poie.scoring import score_candidate
from app.services.poie.triggers import collect_candidates
from app.services.priority_arbiter import build_ops_queue

__all__ = ["run_poie", "score_candidate", "project_ops_queue"]


def _goals_from_brief_and_db(
    brief: ManagerHomeBrief,
    *,
    db: Session | None,
    store_id: str | None,
) -> list[Goal]:
    goals: list[Goal] = []
    if brief.ops_queue and brief.ops_queue.active_goal:
        g = brief.ops_queue.active_goal
        goals.append(
            Goal(
                id="active-goal",
                store_id=store_id or "",
                raw_text=g.title,
                metric="custom",
                on_track=None,
            )
        )
    if db is None or not store_id:
        return goals
    try:
        from app.services.goal_engine import load_goal_snapshot

        snapshot = load_goal_snapshot(db, store_id)
        for item in list(snapshot.active_goals or []) + list(snapshot.deviation_alerts or []):
            goals.append(
                Goal(
                    id=str(item.id),
                    store_id=store_id,
                    raw_text=item.raw_text,
                    metric=item.metric,
                    target_value=item.target_value,
                    current_value=item.current_value,
                    forecast_value=item.forecast_value,
                    gap=item.gap,
                    on_track=item.on_track,
                )
            )
    except Exception:  # noqa: BLE001 — POIE 不因 Goal 子系统失败而中断
        pass
    return goals


def _overlay_db_threads(queue: OpsQueueBrief, db: Session | None, store_id: str, agents) -> list[WorkThread]:
    """用持久化 OperatingThread 覆盖/补齐队列中的 threads。"""
    if db is None:
        return [
            WorkThread(
                id=item.id,
                store_id=store_id,
                title=item.title,
                stage=item.next_step or "",
                done=item.done,
                doing=item.doing,
                next_step=item.next_step,
                needs_owner=item.needs_owner,
            )
            for item in queue.threads or []
        ]
    try:
        from app.services.thread_engine import load_active_threads, sync_threads_from_agents

        if agents is not None:
            sync_threads_from_agents(db, store_id, agents)
        briefs = load_active_threads(db, store_id)
        if briefs:
            queue.threads = briefs
    except Exception:  # noqa: BLE001
        pass

    return [
        WorkThread(
            id=item.id,
            store_id=store_id,
            title=item.title,
            stage=item.next_step or "",
            done=item.done,
            doing=item.doing,
            next_step=item.next_step,
            needs_owner=item.needs_owner,
        )
        for item in queue.threads or []
    ]


def run_poie(
    brief: ManagerHomeBrief,
    *,
    store_id: str,
    events: EventEngineResult | None = None,
    agents: StoreAgentsResponse | None = None,
    strategy_memory: StrategyMemorySnapshot | None = None,
    db: Session | None = None,
) -> PoieRunResult:
    """运行主动经营智能引擎：六大 Trigger → 仲裁 → 经营队列。"""
    if db is not None:
        try:
            from app.services.goal_engine import update_goal_progress

            update_goal_progress(db, store_id, days=7)
        except Exception:  # noqa: BLE001
            pass

    queue = build_ops_queue(
        brief,
        events=events,
        agents=agents,
        strategy_memory=strategy_memory,
    )

    candidates = collect_candidates(
        brief,
        store_id=store_id,
        events=events,
        agents=agents,
        strategy_memory=strategy_memory,
        db=db,
    )
    queue = merge_candidates_into_queue(queue, candidates)
    # merge 可能抬高 need_you；noop 过滤计数在 arbitrate 内已累加

    goals = _goals_from_brief_and_db(brief, db=db, store_id=store_id)
    if goals and queue.need_you:
        top = queue.need_you[0]
        if "目标" not in (top.meta or ""):
            top.meta = f"{top.meta} · 目标相关" if top.meta else "目标相关"

    # 访谈未完成时不挂伪目标条（避免 growth 默认叙事冒充老板目标）
    interviewing = any(
        (c.interrupt_reason == "understanding" or c.meta == "understanding") for c in queue.need_you
    )
    if interviewing:
        queue.active_goal = None
    else:
        # 首页目标条：仅在有真实老板 Goal 时展示；不用 growth 周目标冒充
        if goals:
            g0 = goals[0]
            from app.schemas.arbiter import ActiveGoalBrief

            status = "偏离计划" if g0.on_track is False else ("推进中" if g0.on_track else "已记录")
            queue.active_goal = ActiveGoalBrief(
                title=g0.raw_text,
                current_status=status,
                progress_summary=(
                    f"当前 {g0.current_value:g} / 目标 {g0.target_value:g}"
                    if g0.current_value is not None and g0.target_value is not None
                    else ""
                ),
                next_step="需要你时我会出现在「现在需要你」",
                ai_judgment="按你的目标持续推进，不必反复交代。",
            )
        else:
            queue.active_goal = None

    work_threads = _overlay_db_threads(queue, db, store_id, agents)

    # 候选总数：V1 arbiter 粗估 + Trigger 候选
    event_n = len(events.events) if events else 0
    note_n = len(brief.parallel_notes or [])
    mem_n = len(strategy_memory.items) if strategy_memory else 0
    baseline = event_n + note_n + mem_n + (1 if brief.primary_experiment else 0)
    candidates_total = max(baseline, len(candidates))
    # 被筛掉 = Trigger 中未进 need_you/working/result/opp 的部分粗估
    surfaced = (
        len(queue.need_you)
        + len(queue.working)
        + len(queue.results)
        + len(queue.opportunities)
    )
    filtered = max(queue.filtered_noop_count, max(0, candidates_total - surfaced))
    queue.filtered_noop_count = filtered

    # 理解缺口才在这里通知；经营 NBA 由 operating_clock.light tick 按节律推，避免高峰刷增长
    if db is not None and queue.need_you:
        top_card = queue.need_you[0]
        is_understanding = (
            top_card.interrupt_reason == "understanding"
            or (top_card.meta or "") == "understanding"
            or str(top_card.id).startswith("understanding:")
        )
        if is_understanding:
            try:
                from app.services.notification_service import notify_store_owner

                notify_store_owner(
                    db,
                    store_id=store_id,
                    notification_type="need_you",
                    title=top_card.title[:60],
                    body=(top_card.why_now or top_card.ai_judgment or "")[:200],
                    priority="high" if top_card.arbiter_state == "need_input" else "normal",
                    related_decision_id=str(top_card.id)[:64],
                    clock_phase="understanding",
                )
            except Exception:  # noqa: BLE001 — 通知失败不阻塞 POIE
                pass

    # Safe Mode 时产生提醒通知
    if db is not None:
        try:
            from app.services.mue import ensure_understanding
            from app.services.mos_engine import determine_system_mode

            mu = ensure_understanding(db, store_id=store_id, agents=agents)
            if determine_system_mode(mu) == "safe" and mu.mos_blocking_fields:
                from app.services.notification_service import notify_store_owner

                blockers = "、".join(mu.mos_blocking_fields[:3])
                notify_store_owner(
                    db,
                    store_id=store_id,
                    notification_type="safe_mode",
                    title="还需要你确认几项基本信息",
                    body=f"以下信息会影响经营判断：{blockers}。回答后我就可以开始自动经营了。",
                    priority="normal",
                )
        except Exception:  # noqa: BLE001
            pass

    return PoieRunResult(
        store_id=store_id,
        generated_at=datetime.now(timezone.utc),
        candidates_total=candidates_total,
        filtered_noop_count=filtered,
        ops_queue=queue,
        active_goals=goals,
        work_threads=work_threads,
    )


def project_ops_queue(poie: PoieRunResult) -> OpsQueueBrief:
    """前台只消费经营队列投影。"""
    return poie.ops_queue
