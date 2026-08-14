from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

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


@celery_app.task(name="platform_intel.collect_official")
def collect_official_platform_intel() -> dict:
    from app.services.platform_intel import collect_official_intel

    db = SessionLocal()
    try:
        return collect_official_intel(db)
    finally:
        db.close()


@celery_app.task(name="oci.diff_p0_rules")
def diff_p0_rule_sources() -> dict:
    from app.services.oci.fetchers import diff_enabled_rule_sources

    db = SessionLocal()
    try:
        return diff_enabled_rule_sources(db)
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
        try:
            from app.services.seed_launch import daily_sla_digest, push_daily_sla

            digest = daily_sla_digest(db, store_id)
            result["daily_sla"] = digest
            result["daily_sla_pushed"] = bool(push_daily_sla(db, store_id, digest))
        except Exception as exc:  # noqa: BLE001
            result["daily_sla_error"] = str(exc)[:80]
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
            try:
                from app.services.decision_flow import build_decision_flow
                from app.services.operating_clock import apply_light_tick

                flow = build_decision_flow(
                    queue=poie_result.ops_queue,
                    events=events,
                    db=db,
                    store_id=store_id,
                )
                result["decision_flow_phase"] = flow.get("phase")
                result["light_tick"] = apply_light_tick(
                    db, store_id, flow=flow, queue=poie_result.ops_queue
                )
            except Exception as exc:  # noqa: BLE001
                result["light_tick_error"] = str(exc)[:80]
            # POIE 内部已接入 notification 推送
    except Exception as exc:  # noqa: BLE001 — POIE 失败不阻塞 Clock
        result["poie_error"] = str(exc)[:80]

    # ═══ WP2: 执行分级仲裁 —— AUTO_AND_REPORT 真正自动执行（高峰保护时段不动菜单） ═══
    if phase not in ("lunch_protect",):
        try:
            from app.services.execution_policy import auto_execute_recommendations

            auto_results = auto_execute_recommendations(db, store_id)
            if auto_results:
                result["auto_executed"] = [
                    r for r in auto_results if r.get("applied")
                ]
                result["auto_dropped"] = sum(1 for r in auto_results if r.get("mode") == "DROP")
        except Exception as exc:  # noqa: BLE001 — 自动执行失败不阻塞 Clock
            result["auto_execute_error"] = str(exc)[:80]

    return result


# ═══ WP1: 店级节律调度 —— 对的时间干对的事 ═══


def _clock_marker_key(store_id: str, phase: str, day: str) -> str:
    from app.services.operating_clock import clock_marker_key

    return clock_marker_key(store_id, phase, day)


def _clock_already_ran(db: Session, store_id: str, phase: str, day: str) -> bool:
    from app.services.operating_clock import clock_already_ran

    return clock_already_ran(db, store_id, phase, day)


def _mark_clock_ran(db: Session, store_id: str, phase: str, day: str) -> None:
    from app.services.operating_clock import mark_clock_ran

    mark_clock_ran(db, store_id, phase, day)


@celery_app.task(name="ops.rhythm_tick")
def rhythm_tick() -> dict:
    """WP1: 每 30 分钟一次的节律心跳——逐店按自己的经营节律命中 phase 才执行。

    与进程内时钟共用 tick_all_stores，每天每相位幂等一次。
    """
    from app.services.operating_clock import tick_all_stores

    return tick_all_stores(heavy=True)


@celery_app.task(name="ops.follow_up_decisions")
def follow_up_decisions() -> dict:
    """WP3: next_check_at 消费者——AI 说过的每句"观察 48 小时"都会兑现成结果通知。

    扫描到期的 OperatingDecision，评估结果，推送通知，沉淀 strategy_memory。
    """
    from datetime import timezone as _tz
    from app.models.operating_decision import OperatingDecision

    db = SessionLocal()
    try:
        now_utc = datetime.now(_tz.utc)
        due = list(
            db.execute(
                select(OperatingDecision).where(
                    OperatingDecision.next_check_at.is_not(None),
                    OperatingDecision.next_check_at <= now_utc,
                    OperatingDecision.status.in_(("created", "arbitrated", "executing", "observed")),
                )
            ).scalars()
        )
        results = []
        for decision in due:
            try:
                outcome = _evaluate_decision_outcome(db, decision)
                if outcome.get("conclusive"):
                    decision.status = "resolved"
                    decision.resolved_at = now_utc
                    decision.next_check_at = None
                else:
                    decision.status = "observed"
                    decision.next_check_at = now_utc + timedelta(hours=24)
                db.add(decision)
                results.append({"decision_id": decision.id, "outcome": outcome.get("verdict", "unknown")})
            except Exception as exc:  # noqa: BLE001
                results.append({"decision_id": decision.id, "error": str(exc)[:80]})
        db.commit()
        loop_tick = {"checked": 0, "ready": []}
        try:
            from app.services.closed_loop import tick_observing_loops

            loop_tick = tick_observing_loops(db)
        except Exception as exc:  # noqa: BLE001
            loop_tick = {"error": str(exc)[:80]}
        nag = {"count": 0}
        try:
            from app.services.store_ops import nag_overdue_human_tasks

            nag = nag_overdue_human_tasks(db)
        except Exception as exc:  # noqa: BLE001
            nag = {"error": str(exc)[:80]}
        return {"checked": len(due), "results": results, "loops": loop_tick, "nags": nag}
    finally:
        db.close()


def _evaluate_decision_outcome(db: Session, decision: OperatingDecision) -> dict:
    """评估单个决策的结果——含 Decision Core 活动复盘。"""
    from app.services.experiment_attribution import evaluate_experiment

    # 如果有关联的 experiment，复用归因逻辑
    if decision.work_thread_id:
        from app.models.ohre import Experiment

        exp = db.execute(
            select(Experiment)
            .where(Experiment.recommendation_id == decision.id)
            .limit(1)
        ).scalar_one_or_none()
        if exp and exp.result in ("pending", None):
            outcome = evaluate_experiment(db, exp, days=7)

            # Decision Core 活动复盘：检查 stop_conditions 是否触发
            verdict = outcome.result
            try:
                import json as _json
                from app.models.ohre import Recommendation

                rec = db.get(Recommendation, exp.recommendation_id)
                if rec and rec.content_json:
                    content = _json.loads(rec.content_json)
                    if content.get("source") == "decision_core_campaign":
                        # 检查 guardrail
                        stop_conditions = content.get("stop_conditions") or []
                        guardrail_metrics = content.get("guardrail_metrics") or []
                        # 如果 lift 为负 → 触发 stop
                        if outcome.lift_pct is not None and outcome.lift_pct <= -2:
                            verdict = "negative"
                        # 推送活动复盘通知
                        from app.services.notification_service import notify_store_owner

                        notify_store_owner(
                            db,
                            store_id=decision.store_id,
                            notification_type="experiment_result",
                            title=f"活动测试结果：{verdict}",
                            body=f"订单变化 {outcome.lift_pct:+.1f}%。{'建议保留' if verdict == 'positive' else '建议停止' if verdict == 'negative' else '效果不明显，继续观察'}",
                            priority="high" if verdict == "negative" else "normal",
                        )
            except Exception:  # noqa: BLE001
                pass

            return {
                "conclusive": outcome.result in ("positive", "negative", "neutral", "unknown"),
                "verdict": verdict,
                "lift_pct": outcome.lift_pct,
            }
    # 无实验：检查 confidence 是否足够
    return {"conclusive": False, "verdict": "pending"}
