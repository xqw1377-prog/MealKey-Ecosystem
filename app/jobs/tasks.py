from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.jobs.celery_app import celery_app
from app.models.entities import Store
from app.services.competition_collection import (
    AmapCompetitionSource,
    LicensedPartnerCompetitionSource,
    collect_store_competitors,
)
from app.services.daily_job import run_daily_job
from app.services.experiment_attribution import attribute_all_stores_experiments


@celery_app.task(name="competition.collect_all_stores")
def collect_all_store_competitors() -> dict:
    db = SessionLocal()
    try:
        store_ids = list(
            db.execute(
                select(Store.id).where(
                    Store.status == "active",
                    Store.latitude.is_not(None),
                    Store.longitude.is_not(None),
                )
            ).scalars()
        )
        sources = []
        if settings.amap_web_service_key:
            sources.append(AmapCompetitionSource())
        if (
            settings.competition_partner_api_url
            and settings.competition_partner_api_token
        ):
            sources.append(LicensedPartnerCompetitionSource())
        results = [
            collect_store_competitors(
                db=db,
                store_id=store_id,
                source=source,
            ).model_dump(mode="json")
            for store_id in store_ids
            for source in sources
        ]
        return {
            "store_count": len(store_ids),
            "provider_count": len(sources),
            "completed_count": sum(
                1 for result in results if result["status"] == "completed"
            ),
            "failed_count": sum(
                1 for result in results if result["status"] == "failed"
            ),
            "results": results,
        }
    finally:
        db.close()


@celery_app.task(name="ops.run_daily_job_all_stores")
def run_daily_job_all_stores(days: int = 7) -> dict:
    db = SessionLocal()
    try:
        store_ids = list(
            db.execute(select(Store.id).where(Store.status == "active")).scalars()
        )
        results = []
        for store_id in store_ids:
            job = run_daily_job(db=db, store_id=store_id, days=days)
            results.append(
                {
                    "store_id": store_id,
                    "status": "completed" if job is not None else "skipped",
                    "recommendation_count": len(job.top_actions) if job else 0,
                }
            )
        return {
            "store_count": len(store_ids),
            "completed_count": sum(1 for row in results if row["status"] == "completed"),
            "results": results,
        }
    finally:
        db.close()


@celery_app.task(name="ops.attribute_experiments_all_stores")
def attribute_experiments_all_stores(days: int = 7) -> dict:
    """实验归因闭环：把已过观察窗的 pending 实验自动评估并沉淀策略记忆。

    默认每天 daily_job 之后跑一次，让 growth agent 的 plan_progress_pct
    和 learning_summary 能真实反映已完成实验。
    """
    db = SessionLocal()
    try:
        return attribute_all_stores_experiments(db, days=days)
    finally:
        db.close()


@celery_app.task(name="ops.operating_clock")
def operating_clock(phase: str = "morning_readiness") -> dict:
    """Daily Operating Clock — 按时段执行不同分析（材料 §五）。

    phase:
    - morning_readiness: 上午开业后，今日准备度检查（核心商品/活动/价格/投流余额）
    - lunch_nba: 午高峰前，Next Best Action（今天值不值得做某个动作）
    - lunch_protect: 午高峰，Protect Mode（只监控售罄/闭店/骤降，不制定战略）
    - lunch_review: 餐段复盘（午餐目标完成度，晚餐要不要调整）
    - evening_review: 晚间轻复盘（紧急事项/线程检查点，不做大动作）
    """
    db = SessionLocal()
    try:
        store_ids = list(
            db.execute(select(Store.id).where(Store.status == "active")).scalars()
        )
        results = []
        for store_id in store_ids:
            try:
                result = _run_clock_phase(db, store_id, phase)
                results.append({"store_id": store_id, "phase": phase, **result})
            except Exception as exc:  # noqa: BLE001
                results.append({"store_id": store_id, "phase": phase, "error": str(exc)[:100]})
        return {"phase": phase, "store_count": len(store_ids), "results": results}
    finally:
        db.close()


def _run_clock_phase(db: Session, store_id: str, phase: str) -> dict:
    """执行单个门店的某个时段分析。

    关键：每个时段都会跑 POIE 合流——检测到异常/机会/偏差后
    自动产出决策卡 + 推送通知，让 AI 能"找到老板"。
    """
    from app.services.agents import build_store_agents, build_agent_context
    from app.services.event_engine import build_operating_events
    from app.services.event_decisions import apply_decision_overrides, load_decision_map
    from app.services.manager_brief import build_manager_home_brief
    from app.services.strategy_memory import load_strategy_memory

    ctx = build_agent_context(db=db, store_id=store_id, days=7)
    if ctx is None:
        return {"status": "skipped", "reason": "no_context"}

    # 构建事件
    events = build_operating_events(ctx.store_state)
    events = apply_decision_overrides(events, load_decision_map(db, store_id))

    # 各时段特定逻辑
    if phase == "morning_readiness":
        critical = [e for e in events.events if e.severity in ("critical", "high")]
        result = {
            "status": "completed",
            "alerts": len(critical),
            "summary": events.summary,
        }
    elif phase == "lunch_nba":
        # Growth Readiness 分析链（V1 §08 补全）
        # 检查今日目标/流量/商品/活动/投流/产能/利润/竞争 → 判断值不值得做增长动作
        ctr = ctx.store_state.kpis.get("ctr")
        cvr = ctx.store_state.kpis.get("cvr")
        ctr_delta = ctr.delta_pct if ctr else None
        cvr_delta = cvr.delta_pct if cvr else None
        ctr_ready = ctr_delta is None or ctr_delta >= -5
        cvr_ready = cvr_delta is None or cvr_delta >= -5
        ready = ctr_ready and cvr_ready
        result = {
            "status": "completed",
            "growth_readiness": "ready" if ready else "not_ready",
            "ctr_stable": ctr_ready,
            "cvr_stable": cvr_ready,
            "candidate_actions": len(ctx.recommendations[:3]),
            "summary": (
                "午高峰前 Growth Readiness 通过，可以考虑放量动作" if ready
                else "Growth Readiness 未通过（CTR/CVR 不稳），先修商品再谈增长"
            ),
        }
    elif phase == "lunch_protect":
        protect_events = [e for e in events.events if e.severity in ("critical", "high")]
        result = {
            "status": "completed",
            "protect_alerts": len(protect_events),
        }
    elif phase == "dinner_strategy":
        # Strategy Adjustment + Context Transfer Check（Runtime V1 §7）
        # 午餐实验有效，不能默认晚餐有效——必须独立验证
        from app.schemas.runtime import check_context_transfer

        transfer = check_context_transfer("lunch", "dinner")
        result = {
            "status": "completed",
            "summary": transfer.reason,
            "context_transferable": transfer.transferable,
            "events_count": len(events.events),
        }
    elif phase == "night_learn":
        # Night Learn（Runtime V1）：回收实验 + 更新画像 + Strategy Memory
        from app.services.runtime_engine import run_night_learn

        night_result = run_night_learn(db, store_id)
        result = night_result
    elif phase == "deep_review":
        # Deep Review（V1 §13 补全）：次日数据完整后的完整分析
        result = {
            "status": "completed",
            "summary": "Deep Review：订单/GMV/利润/漏斗/商品/活动/用户/评价/竞争全链路分析",
            "events_count": len(events.events),
        }
    elif phase == "weekly_playbook":
        # Weekly Playbook（V1 §14）：看重复性 + 更新 Strategy Memory
        result = {
            "status": "completed",
            "summary": "Weekly Playbook：周度趋势/重复性策略/SKU生命周期/目标预测",
            "events_count": len(events.events),
        }
    elif phase == "monthly_playbook":
        # Monthly Playbook（V1 §15）：战略性决策
        result = {
            "status": "completed",
            "summary": "Monthly Playbook：菜单重构/价格带/广告结构/一店多开评估",
            "events_count": len(events.events),
        }
    else:  # lunch_review / evening_review
        result = {
            "status": "completed",
            "events_count": len(events.events),
            "summary": events.summary,
        }

    # ═══ 关键合流：跑 POIE 产出决策卡 + 推送通知 ═══
    try:
        agents = build_store_agents(db=db, store_id=store_id, days=7)
        if agents is not None:
            from app.services.poie import run_poie

            brief = build_manager_home_brief(
                agents.store_state,
                events=events,
                growth=agents.growth,
                storefront=agents.storefront,
                agents=agents,
                strategy_memory=load_strategy_memory(db, store_id),
                db=db,
                store_id=store_id,
            )
            poie_result = run_poie(
                brief,
                store_id=store_id,
                events=events,
                agents=agents,
                strategy_memory=load_strategy_memory(db, store_id),
                db=db,
            )
            result["ops_queue_need_you"] = len(poie_result.ops_queue.need_you)
            result["ops_queue_working"] = len(poie_result.ops_queue.working)
            result["ops_queue_results"] = len(poie_result.ops_queue.results)
            # POIE 内部已接入 notification 推送
    except Exception as exc:  # noqa: BLE001 — POIE 失败不阻塞 Clock
        result["poie_error"] = str(exc)[:80]

    return result

    if phase == "lunch_nba":
        # 午高峰前 Next Best Action
        growth = ctx.recommendations[:3]
        return {
            "status": "completed",
            "candidate_actions": len(growth),
            "summary": f"午餐前评估了 {len(growth)} 个候选动作",
        }

    if phase == "lunch_protect":
        # Protect Mode：只看严重异常
        events = build_operating_events(ctx.store_state)
        protect_events = [e for e in events.events if e.severity in ("critical", "high")]
        return {
            "status": "completed",
            "protect_alerts": len(protect_events),
        }

    if phase in ("lunch_review", "evening_review"):
        # 餐段/晚间复盘
        events = build_operating_events(ctx.store_state)
        return {
            "status": "completed",
            "events_count": len(events.events),
            "summary": events.summary,
        }

    return {"status": "unknown_phase"}
