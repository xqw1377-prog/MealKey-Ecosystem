"""AI store-manager homepage brief: judgment first, not KPI wall.

V2 升级（步骤 4+5）：
- 接收完整 StoreAgentsResponse，计算 MealKey Score 5 维加权统一分；
- 从 diagnosis/competition 收集 3 条问题；
- 从 growth/storefront/service 收集 3 条今日任务（带量化预计影响）。
旧字段（top_problem_title 等）保留做兼容。
"""

from __future__ import annotations

from typing import Optional

from app.schemas.agents import GrowthAgentResult, StoreAgentsResponse, StorefrontAgentResult
from app.schemas.events import EventEngineResult
from app.schemas.mealkey_score import MealKeyScore, OperationScore
from app.schemas.strategy_memory import StrategyMemorySnapshot
from app.schemas.store_state import (
    BriefProblem,
    BriefResult,
    BriefTask,
    ManagerHomeBrief,
    ParallelNote,
    PrimaryExperimentBrief,
    ProfitSummaryBrief,
    StoreState,
)
from app.services.mealkey_score import compute_mealkey_score, compute_operation_score
from app.services.priority_arbiter import build_ops_queue


def _collect_problems(agents: StoreAgentsResponse, events: EventEngineResult | None = None) -> list[BriefProblem]:
    """从今日事件 + diagnosis + competition 收集最多 3 条问题。

    事件优先（alert/handle_today 的实时异常最紧急），根因分析次之。
    """
    problems: list[BriefProblem] = []

    # 事件优先：今日需要处理的异常（售罄/闭店/活动失效等量化影响事件）
    if events and events.events:
        for event in events.events:
            if event.manager_decision not in {"handle_today", "alert_owner"}:
                continue
            detail = event.estimated_impact or event.detail or ""
            if event.estimated_impact_amount:
                detail = f"{detail}（预计损失约{int(event.estimated_impact_amount)}单）"
            problems.append(
                BriefProblem(
                    title=event.title,
                    detail=detail[:140],
                    severity=event.severity or "medium",
                    source_agent=event.recommended_agent or "event_engine",
                )
            )
            if len(problems) >= 2:  # 事件最多占 2 条，留 1 条给根因
                break

    # diagnosis 根因（填充剩余位置）
    for root in (agents.diagnosis.root_causes or []):
        if len(problems) >= 3:
            break
        problems.append(
            BriefProblem(
                title=root.title,
                detail=root.explanation[:120] if root.explanation else "",
                severity="high" if root.confidence >= 0.7 else "medium",
                source_agent="diagnosis",
            )
        )

    # competition 威胁信号（兜底）
    if len(problems) < 3 and agents.competition.threat_signals:
        threat = agents.competition.threat_signals[0]
        problems.append(
            BriefProblem(
                title=threat if isinstance(threat, str) else str(threat),
                detail="商圈竞争压力上升，关注竞品动作。",
                severity="medium",
                source_agent="competition",
            )
        )

    if not problems and agents.diagnosis.primary_problem:
        label_map = {
            "store_ctr_down": "第一眼吸引力下降",
            "store_cvr_down": "进店后转化变弱",
        }
        problems.append(
            BriefProblem(
                title=label_map.get(agents.diagnosis.primary_problem, agents.diagnosis.primary_problem),
                detail=agents.diagnosis.daily_summary[:120] if agents.diagnosis.daily_summary else "",
                severity="high",
                source_agent="diagnosis",
            )
        )

    return problems[:3]


def _collect_tasks(agents: StoreAgentsResponse) -> list[BriefTask]:
    """从 growth + storefront + service 收集最多 3 条今日任务（带量化影响）。"""
    tasks: list[BriefTask] = []

    if agents.growth.current_action:
        action = agents.growth.current_action
        tasks.append(
            BriefTask(
                title=action.title,
                detail=(action.phase_reason or "")[:120],
                expected_metric=action.expected_metric,
                agent_key="growth",
                recommendation_id=action.recommendation_id,
                status=getattr(action, "status", None),
            )
        )
    elif agents.growth.selected_opportunity:
        opp = agents.growth.selected_opportunity
        tasks.append(
            BriefTask(
                title=opp.title,
                detail=opp.problem[:120] if opp.problem else "",
                expected_metric=opp.expected_metric,
                expected_lift_low=opp.expected_lift_pct_low,
                expected_lift_high=opp.expected_lift_pct_high,
                agent_key="growth",
                recommendation_id=opp.recommendation_id,
                status=getattr(opp, "status", None),
            )
        )

    if agents.storefront.priority_actions:
        action = agents.storefront.priority_actions[0]
        tasks.append(
            BriefTask(
                title=action.title,
                detail=action.detail[:120] if action.detail else "",
                expected_metric=action.expected_metric,
                expected_lift_low=action.expected_lift_pct_low,
                expected_lift_high=action.expected_lift_pct_high,
                agent_key="storefront",
            )
        )

    for agent_key, agent_result in [
        ("service", agents.service),
        ("review", agents.review),
    ]:
        if agent_result.priority_actions:
            action = agent_result.priority_actions[0]
            tasks.append(
                BriefTask(
                    title=action.title,
                    detail=action.detail[:100] if action.detail else "",
                    expected_metric=action.expected_metric,
                    expected_lift_low=action.expected_lift_pct_low,
                    expected_lift_high=action.expected_lift_pct_high,
                    agent_key=agent_key,
                )
            )
            break

    return tasks[:3]


def _collect_results(db, store_id: str) -> list[BriefResult]:
    """从 strategy_memory 读取最近归因完成的实验结果（第 6 类触发）。

    让老板看到"上次做的事有没有效"——AI 对自己的建议负责。
    """
    try:
        from app.services.strategy_memory import load_strategy_memory

        snapshot = load_strategy_memory(db, store_id, limit=10)
    except Exception:  # noqa: BLE001
        return []

    results: list[BriefResult] = []
    # 优先展示有明确结论的（positive/negative），neutral 次之
    for item in snapshot.items:
        if item.result not in {"positive", "negative", "neutral"}:
            continue
        outcome_label = {
            "positive": "有效",
            "negative": "无效",
            "neutral": "效果不明显",
        }.get(item.result, "未知")

        detail = item.lesson
        if item.lift_pct is not None:
            detail = f"{detail}（lift {item.lift_pct:+.1f}%）"

        results.append(
            BriefResult(
                title=f"「{item.action_type}」实验{outcome_label}",
                outcome=item.result,
                detail=detail[:140],
                action_type=item.action_type,
                lift_pct=item.lift_pct,
                recommendation_id=None,
                experiment_id=item.source_experiment_id,
            )
        )

    # P1-A: 附加预估-实际对账卡
    try:
        from app.models.ohre import Recommendation
        from sqlalchemy import select as _select
        import json as _json

        recent_recs = db.execute(
            _select(Recommendation)
            .where(Recommendation.store_id == store_id)
            .order_by(Recommendation.created_at.desc())
            .limit(15)
        ).scalars().all()
        for rec in recent_recs:
            content = {}
            if rec.content_json:
                try:
                    content = _json.loads(rec.content_json)
                except _json.JSONDecodeError:
                    continue
            verification = content.get("verification")
            if not verification:
                continue
            expected = verification.get("expected_lift_pct", 0)
            actual = verification.get("actual_lift_pct", 0)
            verdict = verification.get("verdict", "unknown")
            verdict_label = {"beat": "超出预期", "met": "达标", "partial": "部分达标", "missed": "未达标"}.get(verdict, "未知")
            # 避免和 strategy_memory 的结果重复
            if any(r.action_type == rec.action_type and r.lift_pct == actual for r in results):
                continue
            results.append(
                BriefResult(
                    title=f"预估 +{expected:.0f}% → 实际 {actual:+.1f}%（{verdict_label}）",
                    outcome="positive" if verdict in ("beat", "met") else "neutral" if verdict == "partial" else "negative",
                    detail=f"「{rec.action_type}」预估提升 {expected:.0f}%，实际 {actual:+.1f}%。归因质量：{verification.get('attribution_quality', 'medium')}",
                    action_type=rec.action_type,
                    lift_pct=actual,
                    recommendation_id=rec.id,
                )
            )
            if len(results) >= 6:
                break
    except Exception:  # noqa: BLE001
        pass

    return results[:6]


def _build_parallel_notes(
    agents: StoreAgentsResponse,
    events: EventEngineResult | None,
    legacy_notes: list[str] | None,
) -> list[ParallelNote]:
    notes: list[ParallelNote] = []
    if agents.service.pending_replies:
        title = agents.service.priority_actions[0].title if agents.service.priority_actions else "客服积压待处理"
        notes.append(
            ParallelNote(
                agent_key="service",
                title=f"{title}（约 {agents.service.pending_replies} 条）",
                kind="confirm",
            )
        )
    if agents.review.themes:
        theme = agents.review.themes[0].label
        notes.append(ParallelNote(agent_key="review", title=f"已扫描评价主题：{theme}", kind="scan"))
    if events and any(e.event_type == "ACTIVITY_EXPIRING" for e in events.events):
        notes.append(ParallelNote(agent_key="promo", title="有活动即将到期/失效", kind="confirm"))
    if agents.ads.priority_actions and agents.ads.unlock_ready:
        notes.append(
            ParallelNote(
                agent_key="ads",
                title=agents.ads.priority_actions[0].title,
                kind="confirm",
            )
        )
    if agents.competition.threat_signals:
        notes.append(
            ParallelNote(
                agent_key="competition",
                title=f"已扫描核心竞品变化 {len(agents.competition.threat_signals)} 项",
                kind="scan",
            )
        )

    if not notes and legacy_notes:
        for raw in legacy_notes:
            text = str(raw or "")
            if text.startswith("[") and "]" in text:
                agent_key = text[1 : text.index("]")]
                title = text[text.index("]") + 1 :].strip()
            else:
                agent_key = "service"
                title = text
            notes.append(ParallelNote(agent_key=agent_key, title=title, kind="auto"))
    return notes[:6]


def _build_primary_experiment(
    agents: StoreAgentsResponse | None,
    growth: GrowthAgentResult | None,
) -> PrimaryExperimentBrief | None:
    if not agents and not growth:
        return None

    growth = growth or (agents.growth if agents else None)
    if growth is None:
        return None

    title = None
    recommendation_id = None
    expected_metric = ""
    lift_low = None
    lift_high = None
    status = None
    window_hours = 48

    if growth.current_action:
        action = growth.current_action
        title = action.title
        recommendation_id = action.recommendation_id
        expected_metric = action.expected_metric or ""
        status = getattr(action, "status", None)
        window_hours = getattr(action, "window_hours", None) or 48
    elif growth.selected_opportunity:
        opp = growth.selected_opportunity
        title = opp.title
        recommendation_id = opp.recommendation_id
        expected_metric = opp.expected_metric or ""
        lift_low = opp.expected_lift_pct_low
        lift_high = opp.expected_lift_pct_high
        status = getattr(opp, "status", None)
        window_hours = getattr(opp, "window_hours", None) or 48
    elif growth.today_priority:
        title = growth.today_priority

    if not title:
        return None

    return PrimaryExperimentBrief(
        title=title,
        recommendation_id=recommendation_id,
        experiment_id=None,
        status=status,
        expected_metric=expected_metric,
        expected_lift_low=lift_low,
        expected_lift_high=lift_high,
        window_hours=int(window_hours or 48),
        can_evaluate=False,
        result=None,
    )


def enrich_primary_experiment_from_dashboard(
    brief: ManagerHomeBrief,
    *,
    action_packages: list[dict] | None = None,
    experiments: list[dict] | None = None,
) -> ManagerHomeBrief:
    """用 dashboard/DB 的 recommendation/experiment 补齐主实验闭环字段。"""
    primary = brief.primary_experiment
    if primary is None and brief.primary_experiment_title:
        primary = PrimaryExperimentBrief(title=brief.primary_experiment_title)

    actions = list(action_packages or [])
    exps = list(experiments or [])

    # 没有主实验时，用第一条可执行 recommendation 兜底
    if primary is None:
        if not actions:
            return brief
        top = actions[0]
        primary = PrimaryExperimentBrief(
            title=top.get("title") or "今日主实验",
            recommendation_id=top.get("id"),
            status=top.get("status"),
            expected_metric=top.get("expected_metric") or "",
            expected_lift_low=top.get("expected_lift_pct_low"),
            expected_lift_high=top.get("expected_lift_pct_high"),
            window_hours=int(top.get("window_hours") or 48),
        )

    matched_action = None
    if primary.recommendation_id:
        matched_action = next((a for a in actions if a.get("id") == primary.recommendation_id), None)
    if matched_action is None and primary.title:
        matched_action = next((a for a in actions if a.get("title") == primary.title), None)
    if matched_action is None and primary.title:
        # 模糊：标题互相包含
        matched_action = next(
            (
                a
                for a in actions
                if primary.title in (a.get("title") or "") or (a.get("title") or "") in primary.title
            ),
            None,
        )
    # 仍无匹配时：若只有一条可执行动作，才绑定，避免错绑
    if matched_action is None and len(actions) == 1:
        matched_action = actions[0]
        primary.title = matched_action.get("title") or primary.title

    if matched_action:
        primary.recommendation_id = matched_action.get("id") or primary.recommendation_id
        primary.status = matched_action.get("status") or primary.status
        primary.expected_metric = matched_action.get("expected_metric") or primary.expected_metric
        primary.window_hours = int(matched_action.get("window_hours") or primary.window_hours or 48)
        primary.expected_lift_low = matched_action.get("expected_lift_pct_low", primary.expected_lift_low)
        primary.expected_lift_high = matched_action.get("expected_lift_pct_high", primary.expected_lift_high)
        # 可执行动作标题优先（保证按钮与文案一致）
        if matched_action.get("title"):
            primary.title = matched_action["title"]

    matched_exp = None
    if primary.recommendation_id:
        matched_exp = next(
            (e for e in exps if e.get("recommendation_id") == primary.recommendation_id),
            None,
        )
    if matched_exp is None:
        matched_exp = next((e for e in exps if (e.get("result") or "pending") == "pending"), None)
    if matched_exp:
        primary.experiment_id = matched_exp.get("id")
        primary.result = matched_exp.get("result")
        primary.can_evaluate = bool(matched_exp.get("can_evaluate"))
        if matched_exp.get("window_hours"):
            primary.window_hours = int(matched_exp["window_hours"])

    for index, task in enumerate(brief.tasks):
        if not matched_action:
            break
        same_id = task.recommendation_id == matched_action.get("id")
        same_title = task.title == matched_action.get("title")
        # 第一条任务通常就是主实验叙事，允许在无 id 时回写
        is_primary_slot = index == 0 and not task.recommendation_id
        if same_id or same_title or is_primary_slot:
            task.recommendation_id = matched_action.get("id") or task.recommendation_id
            task.status = matched_action.get("status") or task.status
            if is_primary_slot and matched_action.get("title"):
                task.title = matched_action["title"]
                task.expected_metric = matched_action.get("expected_metric") or task.expected_metric
                task.expected_lift_low = matched_action.get(
                    "expected_lift_pct_low", task.expected_lift_low
                )
                task.expected_lift_high = matched_action.get(
                    "expected_lift_pct_high", task.expected_lift_high
                )

    brief.primary_experiment = primary
    if primary.title:
        brief.primary_experiment_title = primary.title
    return brief


def build_manager_home_brief(
    state: StoreState,
    *,
    events: EventEngineResult | None = None,
    growth: GrowthAgentResult | None = None,
    storefront: StorefrontAgentResult | None = None,
    parallel_service_notes: list[str] | None = None,
    agents: StoreAgentsResponse | None = None,
    strategy_memory: StrategyMemorySnapshot | None = None,
    db=None,
    store_id: str | None = None,
) -> ManagerHomeBrief:
    """构建首页晨报。

    V2：传入完整 agents 时，计算 MealKey Score + 3 问题 + 3 任务。
    V1 兼容：未传 agents 时走旧逻辑（单问题+单机会）。
    """
    top_problem_title = None
    top_problem_detail = None
    if events and events.events:
        actionable = [
            e for e in events.events if e.manager_decision in {"handle_today", "alert_owner"}
        ]
        if actionable:
            top = actionable[0]
            top_problem_title = top.title
            top_problem_detail = top.estimated_impact or top.detail
    if top_problem_title is None and state.primary_problem:
        top_problem_title = {
            "store_ctr_down": "第一眼吸引力下降",
            "store_cvr_down": "进店后转化变弱",
        }.get(state.primary_problem.type, state.primary_problem.type)
        top_problem_detail = state.business.judgment

    top_opportunity_title = None
    top_opportunity_detail = None
    if state.benchmark.judgment:
        top_opportunity_title = "商圈对标机会"
        top_opportunity_detail = state.benchmark.judgment
    elif storefront and storefront.priority_actions:
        action = storefront.priority_actions[0]
        top_opportunity_title = action.title
        top_opportunity_detail = action.detail

    primary_experiment_title = None
    primary_experiment_window = None
    if growth and growth.selected_opportunity:
        primary_experiment_title = growth.selected_opportunity.title
        primary_experiment_window = f"{growth.selected_opportunity.expected_metric} · 建议 24-48h 验证"
    elif growth and growth.today_priority:
        primary_experiment_title = growth.today_priority
        primary_experiment_window = "观察窗口 24-48h"

    business_judgment = state.business.judgment
    if state.benchmark.available and state.benchmark.judgment:
        business_judgment = f"{state.business.judgment} {state.benchmark.judgment}".strip()

    mealkey_score: Optional[MealKeyScore] = None
    operation_score: Optional[OperationScore] = None
    problems: list[BriefProblem] = []
    tasks: list[BriefTask] = []
    parallel_notes: list[ParallelNote] = []
    primary_experiment: Optional[PrimaryExperimentBrief] = None
    # V3：3 区前台
    needs_you: list[BriefTask] = []
    auto_doing: list[ParallelNote] = []
    results: list[BriefResult] = []
    active_goals: list = []
    deviation_alerts: list = []

    if agents is not None:
        mealkey_score = compute_mealkey_score(agents)
        operation_score = compute_operation_score(agents.store_state.platform_health)
        problems = _collect_problems(agents, events)
        tasks = _collect_tasks(agents)
        parallel_notes = _build_parallel_notes(agents, events, parallel_service_notes)
        primary_experiment = _build_primary_experiment(agents, growth)

        # V3：构建 3 区前台
        # 「现在需要你」= 事件里 need_confirm + need_assist 的 + growth 当前主动作
        if events and events.events:
            for event in events.events:
                if event.ai_action in {"need_confirm", "need_assist"}:
                    needs_you.append(
                        BriefTask(
                            title=event.title,
                            detail=(event.estimated_impact or event.detail or "")[:120],
                            expected_metric=event.affected_metric or "",
                            agent_key=event.recommended_agent or "",
                        )
                    )
                    if len(needs_you) >= 3:
                        break
        # growth 当前主动作也是「需要你」
        if len(needs_you) < 3 and growth and growth.current_action:
            needs_you.append(
                BriefTask(
                    title=growth.current_action.title,
                    detail=(growth.current_action.phase_reason or "")[:120],
                    expected_metric=growth.current_action.expected_metric,
                    agent_key="growth",
                    recommendation_id=growth.current_action.recommendation_id,
                )
            )

        # 「MealKey 正在做」= auto_handle 的并行动作
        auto_doing = [n for n in parallel_notes if n.kind == "auto"][:5]

        # 「结果」= 最近归因完成的实验
        if db is not None and store_id:
            results = _collect_results(db, store_id)

        # 目标偏差（第 5 类触发）
        if db is not None and store_id:
            try:
                from app.services.goal_engine import check_goal_deviation

                deviation_alerts = [g.model_dump(mode="json") for g in check_goal_deviation(db, store_id)]
            except Exception:  # noqa: BLE001
                pass
        if mealkey_score.judgment:
            business_judgment = mealkey_score.judgment
        if problems and not top_problem_title:
            top_problem_title = problems[0].title
            top_problem_detail = problems[0].detail
        if tasks and not primary_experiment_title:
            primary_experiment_title = tasks[0].title
            if tasks[0].expected_metric:
                primary_experiment_window = f"{tasks[0].expected_metric} · 建议 24-48h 验证"
    else:
        primary_experiment = _build_primary_experiment(None, growth)
        for note in parallel_service_notes or []:
            text = str(note or "")
            if text.startswith("[") and "]" in text:
                agent_key = text[1 : text.index("]")]
                title = text[text.index("]") + 1 :].strip()
            else:
                agent_key = "service"
                title = text
            parallel_notes.append(ParallelNote(agent_key=agent_key, title=title, kind="auto"))

    profit_summary = ProfitSummaryBrief(
        contribution_profit=state.profit.contribution_profit,
        contribution_profit_delta_pct=state.profit.contribution_profit_delta_pct,
        contribution_profit_per_order=state.profit.contribution_profit_per_order,
        take_home_rate=state.profit.take_home_rate,
        take_home_rate_delta_pct=state.profit.take_home_rate_delta_pct,
        data_quality=state.profit.data_quality,
        judgment=state.profit.judgment or "",
    )

    # open_event_count: 老板需要处理的 + 全部 open（首页右侧也展示 record 类）
    open_event_count = 0
    if events:
        open_event_count = events.handle_today_count + events.alert_count
        if open_event_count == 0:
            open_event_count = sum(
                1 for e in events.events if e.status not in {"ignored", "resolved"}
            )

    brief = ManagerHomeBrief(
        store_name=state.store.name,
        business_health_score=mealkey_score.total if mealkey_score else state.business.health_score,
        business_judgment=business_judgment,
        top_problem_title=top_problem_title,
        top_problem_detail=top_problem_detail,
        top_opportunity_title=top_opportunity_title,
        top_opportunity_detail=top_opportunity_detail,
        primary_experiment_title=primary_experiment.title if primary_experiment else primary_experiment_title,
        primary_experiment_window=primary_experiment_window,
        parallel_service_notes=parallel_service_notes or [f"[{n.agent_key}] {n.title}" for n in parallel_notes],
        open_event_count=open_event_count,
        platform_health_score=state.platform_health.score,
        take_home_rate=state.profit.take_home_rate,
        mealkey_score=mealkey_score,
        operation_score=operation_score,
        problems=problems,
        tasks=tasks,
        parallel_notes=parallel_notes,
        primary_experiment=primary_experiment,
        profit_summary=profit_summary,
        needs_you=needs_you,
        auto_doing=auto_doing,
        results=results,
        goal_prompt="你想让 MealKey 帮你做到什么？" if db is not None else None,
        active_goals=active_goals,
        deviation_alerts=deviation_alerts,
    )
    brief.ops_queue = build_ops_queue(
        brief,
        events=events,
        agents=agents,
        strategy_memory=strategy_memory,
    )
    return brief
