"""POIE 仲裁实现（V1）：决定什么值得打扰老板，以及进入哪一种五态。

正式入口见 `app.services.poie.run_poie`。
优先级：经营价值 × 紧迫度 × 置信度 × 目标相关 × 是否需要人工 ÷ 打扰成本
"""

from __future__ import annotations

from typing import Optional

from app.schemas.agents import StoreAgentsResponse
from app.schemas.arbiter import (
    ActiveGoalBrief,
    DecisionAction,
    DecisionCard,
    OperatingThreadBrief,
    OpsQueueBrief,
)
from app.schemas.events import EventEngineResult, OperatingEvent
from app.schemas.strategy_memory import StrategyMemorySnapshot
from app.schemas.store_state import ManagerHomeBrief, PrimaryExperimentBrief


_SEVERITY_URGENCY = {
    "critical": 1.0,
    "high": 0.85,
    "medium": 0.55,
    "low": 0.3,
    "info": 0.15,
}

_DECISION_NEED_HUMAN = {
    "alert_owner": 1.0,
    "handle_today": 0.85,
    "record": 0.15,
    "ignore": 0.05,
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_interrupt(
    *,
    value: float,
    urgency: float,
    confidence: float,
    need_human: float,
    disturb_cost: float = 0.55,
) -> float:
    """经营价值 × 紧迫度 × 置信度 × 人工介入 ÷ 打扰成本。"""
    cost = max(0.15, disturb_cost)
    raw = (value * urgency * max(0.2, confidence) * need_human) / cost
    return round(_clamp(raw * 100), 2)


# WP5: 打扰分学习——越用越懂老板
def resolve_disturb_cost(db, store_id: str, card_type: str = "default") -> float:
    """从老板的采纳/忽略行为学习打扰成本。

    近30天该类型卡：采纳率高 → cost 降（多推）；连续忽略 → cost 升（少推）。
    边界 [0.35, 0.9]，默认 0.55。
    """
    try:
        from sqlalchemy import select, func
        from app.models.ohre import Recommendation
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        # 统计近30天采纳 vs 忽略
        total = db.execute(
            select(func.count(Recommendation.id)).where(
                Recommendation.store_id == store_id,
                Recommendation.created_at >= cutoff,
            )
        ).scalar_one()

        if total == 0:
            return 0.55

        adopted = db.execute(
            select(func.count(Recommendation.id)).where(
                Recommendation.store_id == store_id,
                Recommendation.created_at >= cutoff,
                Recommendation.status.in_(("adopted", "executed")),
            )
        ).scalar_one()

        adoption_rate = adopted / total

        # 采纳率高 → cost 降（多推）；低 → cost 升（少推）
        # 映射：adoption_rate 0.0→0.9, 0.5→0.55, 1.0→0.35
        cost = 0.9 - adoption_rate * 0.55
        return round(max(0.35, min(0.9, cost)), 2)
    except Exception:  # noqa: BLE001
        return 0.55


def map_event_state(event: OperatingEvent) -> str:
    decision = event.manager_decision or "record"
    if decision in {"ignore"}:
        return "noop"
    if decision == "record":
        return "noop"
    if decision in {"handle_today", "alert_owner"}:
        return "confirm"
    return "noop"


def _event_card(event: OperatingEvent, *, disturb_cost: float = 0.55) -> DecisionCard | None:
    state = map_event_state(event)
    if state == "noop":
        return None

    urgency = _SEVERITY_URGENCY.get(event.severity, 0.5)
    need_human = _DECISION_NEED_HUMAN.get(event.manager_decision or "record", 0.5)
    value = 0.7
    if event.estimated_impact_amount:
        value = _clamp(0.45 + min(event.estimated_impact_amount, 80) / 100, 0.4, 1.0)
    priority = score_interrupt(
        value=value,
        urgency=urgency,
        confidence=event.confidence or 0.7,
        need_human=need_human,
        disturb_cost=0.35 if event.manager_decision == "alert_owner" else disturb_cost,
    )
    # 低于门槛：知道但不打扰
    if priority < 42 and event.manager_decision != "alert_owner":
        return None

    fingerprint = event.fingerprint or f"{event.event_type}|{event.affected_metric or ''}|{event.title}"
    why = event.detail or event.title
    judgment = event.estimated_impact or "已完成第一轮诊断，需要你确认下一步。"
    already = "已核对相关指标与近期变化，排除了可自动处理的噪音。"
    if event.evidence:
        already = f"已核对：{'；'.join(event.evidence[:2])}"

    return DecisionCard(
        id=f"event:{fingerprint}",
        title=event.title,
        arbiter_state="confirm",
        interrupt_reason="anomaly",
        queue_bucket="need_you",
        priority_score=priority,
        why_now=why[:160],
        ai_judgment=judgment[:160],
        ai_already_did=already[:160],
        need_from_owner="确认今天是否处理，或先记录观察。",
        success_metric="处理后异常信号收敛，不再连续触发。",
        summary=judgment[:120],
        meta="异常",
        actions=[
            DecisionAction(
                label="同意处理",
                kind="event_decision",
                class_name="primary",
                event_fingerprint=fingerprint,
                event_decision="handle_today",
            ),
            DecisionAction(
                label="先说说你的顾虑",
                kind="focus_intent",
                class_name="ghost",
            ),
            DecisionAction(
                label="别管我",
                kind="event_decision",
                class_name="ghost",
                event_fingerprint=fingerprint,
                event_decision="ignore",
            ),
        ],
    )


def _primary_experiment_card(
    primary: PrimaryExperimentBrief | None,
    *,
    brief: ManagerHomeBrief,
    disturb_cost: float = 0.55,
) -> DecisionCard | None:
    if not primary or not primary.title:
        return None

    status = (primary.status or "proposed").lower()
    lift = ""
    if primary.expected_lift_high is not None:
        low = primary.expected_lift_low or 0
        lift = f"{low}-{primary.expected_lift_high}%"
    metric = primary.expected_metric or "核心指标"
    window = primary.window_hours or 48

    if primary.can_evaluate and primary.experiment_id:
        return DecisionCard(
            id=f"exp-eval:{primary.experiment_id}",
            title=primary.title,
            arbiter_state="report_result",
            interrupt_reason="result",
            queue_bucket="need_you",
            priority_score=78,
            why_now=f"{window}h 观察窗已到，可以判定上次动作有没有效。",
            ai_judgment="结果已可评估；我会据此更新策略记忆。",
            ai_already_did="实验已跑完观察窗，并完成前后对比准备。",
            need_from_owner="确认评估结果，或让我直接给出有效/无效结论。",
            success_metric=f"{metric} 达到预设阈值即判定有效。",
            summary="观察窗已到，请看结果。",
            meta="结果待确认",
            actions=[
                DecisionAction(
                    label="看结果",
                    kind="evaluate",
                    class_name="primary",
                    experiment_id=primary.experiment_id,
                )
            ],
        )

    if status in {"executed", "pending"} and primary.experiment_id:
        return DecisionCard(
            id=f"exp-run:{primary.experiment_id}",
            title=primary.title,
            arbiter_state="auto_do",
            interrupt_reason="history",
            queue_bucket="working",
            priority_score=35,
            why_now="主实验正在跑，暂不需要你介入。",
            ai_judgment="继续观察，有结论再找你。",
            ai_already_did=f"已启动实验，窗口 {window}h。",
            need_from_owner="不需要你操作。",
            success_metric=f"{metric}{(' ' + lift) if lift else ''} 达标即有效。",
            summary=f"实验进行中，剩余观察窗口约 {window}h。",
            meta="观察中",
            actions=[],
        )

    # 待确认
    priority = score_interrupt(value=0.85, urgency=0.7, confidence=0.75, need_human=0.9, disturb_cost=disturb_cost)
    why = brief.top_problem_detail or brief.business_judgment or "今天最值得推进的一件事已经准备好。"
    return DecisionCard(
        id=f"exp-confirm:{primary.recommendation_id or primary.title}",
        title=primary.title,
        arbiter_state="confirm" if status != "adopted" else "need_input",
        interrupt_reason="time",
        queue_bucket="need_you",
        priority_score=priority,
        why_now=why[:160],
        ai_judgment=(
            f"建议先做单变量实验，窗口 {window}h"
            + (f"，预计 {lift}" if lift else "")
            + "。不建议同时改价格。"
        ),
        ai_already_did="已完成诊断与方案准备，只差你确认启动。"
        if status != "adopted"
        else "方案已就绪，确认后我会开始执行并自动观察。",
        need_from_owner="确认是否开始实验。" if status != "adopted" else "确认执行，我会继续盯结果。",
        success_metric=f"{metric} ≥ 预设提升即判定有效" + (f"（目标约 {lift}）" if lift else "。"),
        summary=brief.primary_experiment_window or f"建议开始 {window}h 实验",
        meta="主实验",
        actions=[
            DecisionAction(
                label="交给 MealKey 执行",
                kind="execute" if status == "adopted" else "adopt",
                class_name="primary",
                recommendation_id=primary.recommendation_id,
            )
            if primary.recommendation_id
            else DecisionAction(
                label="交给 MealKey 执行",
                kind="focus_intent",
                class_name="primary",
            ),
            DecisionAction(
                label="先说说你的顾虑",
                kind="focus_intent",
                class_name="ghost",
            ),
            DecisionAction(
                label="先不处理",
                kind="focus_intent",
                class_name="ghost",
            ),
        ],
    )


def _working_cards(agents: StoreAgentsResponse | None, brief: ManagerHomeBrief) -> list[DecisionCard]:
    cards: list[DecisionCard] = []
    for idx, note in enumerate(brief.parallel_notes or []):
        if note.kind == "confirm":
            cards.append(
                DecisionCard(
                    id=f"note-confirm:{idx}:{note.title}",
                    title=note.title,
                    arbiter_state="need_input",
                    interrupt_reason="anomaly",
                    queue_bucket="need_you",
                    priority_score=60,
                    why_now="这件事缺你的输入或线下协助。",
                    ai_judgment="我已把能做的准备好了，卡在人工节点。",
                    ai_already_did="方案/草稿已就绪。",
                    need_from_owner="提供缺失信息或完成线下动作。",
                    success_metric="补齐后我即可继续执行。",
                    summary=note.title,
                    meta=note.agent_key or "协助",
                    actions=[
                        DecisionAction(
                            label="去处理",
                            kind="scroll",
                            class_name="primary",
                            scroll_target="section-ai",
                        )
                    ],
                )
            )
            continue
        cards.append(
            DecisionCard(
                id=f"note-auto:{idx}:{note.title}",
                title=note.title,
                arbiter_state="auto_do",
                interrupt_reason="time",
                queue_bucket="working",
                priority_score=20,
                why_now="常规经营动作，无需打扰。",
                ai_judgment="我自己处理即可。",
                ai_already_did="已接管执行。",
                need_from_owner="不需要你操作。",
                success_metric="持续运行，异常时再升级。",
                summary="后台自动处理中",
                meta=note.agent_key or "自动",
            )
        )

    if agents and agents.service and agents.service.pending_replies:
        cards.append(
            DecisionCard(
                id="auto:reviews",
                title=f"已自动回复 / 处理评价相关事项（积压约 {agents.service.pending_replies} 条）",
                arbiter_state="auto_do",
                interrupt_reason="time",
                queue_bucket="working",
                priority_score=18,
                why_now="客服与评价属于默认可自动处理范围。",
                ai_judgment="低风险动作，我先做。",
                ai_already_did="正在回复与分流。",
                need_from_owner="不需要你操作。",
                success_metric="积压下降，差评主题可控。",
                summary="评价/客服自动处理中",
                meta="service",
            )
        )

    if not any(c.queue_bucket == "working" for c in cards):
        cards.append(
            DecisionCard(
                id="auto:guardian",
                title="午餐 CPC · 评价回复 · 竞品扫描 · 高价值用户观察",
                arbiter_state="auto_do",
                interrupt_reason="time",
                queue_bucket="working",
                priority_score=10,
                why_now="默认经营守护开启。",
                ai_judgment="没有必须打断你的事项时，我继续巡店。",
                ai_already_did="后台监控已运行。",
                need_from_owner="不需要你操作。",
                success_metric="有真正需要你的事才会出现在「现在需要你」。",
                summary="默认守护中",
                meta="守护",
            )
        )
    return cards


def _result_cards(memory: StrategyMemorySnapshot | None) -> list[DecisionCard]:
    cards: list[DecisionCard] = []
    if not memory:
        return cards
    for item in (memory.items or [])[:4]:
        positive = item.result == "positive"
        negative = item.result == "negative"
        lift = "" if item.lift_pct is None else f"{item.lift_pct:+.1f}%"
        title = item.lesson or item.action_type or "策略结果"
        cards.append(
            DecisionCard(
                id=f"memory:{item.id if hasattr(item, 'id') else title}",
                title=title,
                arbiter_state="report_result",
                interrupt_reason="result",
                queue_bucket="result",
                priority_score=50 if positive or negative else 30,
                why_now="上次动作已经有答案了。",
                ai_judgment=("有效，已加入本店策略记忆。" if positive else "效果不佳，建议停止或换方案。" if negative else "继续观察。"),
                ai_already_did="完成实验评估并写入策略记忆。",
                need_from_owner="不需要操作，知道结果即可。",
                success_metric=f"结果：{item.result or 'unknown'}{(' · ' + lift) if lift else ''}",
                summary=item.reuse_when or item.avoid_when or title,
                meta="有效" if positive else "无效/止损" if negative else "已沉淀",
            )
        )
    return cards


def _opportunity_card(brief: ManagerHomeBrief, *, disturb_cost: float = 0.55) -> DecisionCard | None:
    if not brief.top_opportunity_title:
        return None
    priority = score_interrupt(value=0.65, urgency=0.45, confidence=0.65, need_human=0.35, disturb_cost=disturb_cost)
    if priority < 28:
        return None
    return DecisionCard(
        id=f"opp:{brief.top_opportunity_title}",
        title=brief.top_opportunity_title,
        arbiter_state="confirm",
        interrupt_reason="opportunity",
        queue_bucket="opportunity",
        priority_score=priority,
        why_now="现在不做也不会出事，但做了可能多赚钱。",
        ai_judgment=brief.top_opportunity_detail or "出现短期窗口，值得关注。",
        ai_already_did="已扫描商圈/活动/竞品变化。",
        need_from_owner="若要抓住机会，确认是否推进。",
        success_metric="抓住窗口后订单或份额可见提升。",
        summary=brief.top_opportunity_detail or "",
        meta="机会",
        actions=[
            DecisionAction(
                label="看看怎么做",
                kind="scroll",
                class_name="primary",
                scroll_target="section-growth",
            ),
            DecisionAction(
                label="先记下",
                kind="focus_intent",
                class_name="ghost",
            ),
        ],
    )


def _active_goal(agents: StoreAgentsResponse | None) -> ActiveGoalBrief | None:
    if not agents or not agents.growth:
        return None
    growth = agents.growth
    title = growth.weekly_goal or ""
    if not title and growth.selected_opportunity:
        title = growth.selected_opportunity.title
    if not title:
        return None

    current = growth.today_priority or ""
    next_step = ""
    if growth.current_action:
        next_step = growth.current_action.title or growth.current_action.phase_reason or ""
    elif growth.action_queue:
        next_step = growth.action_queue[0].title or ""

    progress = ""
    if growth.selected_opportunity:
        opp = growth.selected_opportunity
        bits = [opp.expected_metric or ""]
        if opp.expected_lift_pct_high is not None:
            bits.append(f"预计 +{opp.expected_lift_pct_low or 0}-{opp.expected_lift_pct_high}%")
        progress = " · ".join([b for b in bits if b])

    blocked = ""
    if growth.do_not_do:
        blocked = growth.do_not_do[0]

    return ActiveGoalBrief(
        title=title,
        current_status=current or "推进中",
        progress_summary=progress or (growth.learning_summary or ""),
        next_step=next_step or "继续按主实验推进",
        blocked_by=blocked,
        ai_judgment=growth.reason or "我会围绕这个目标安排每天动作。",
    )


def _threads(
    agents: StoreAgentsResponse | None,
    brief: ManagerHomeBrief,
    memory: StrategyMemorySnapshot | None,
) -> list[OperatingThreadBrief]:
    threads: list[OperatingThreadBrief] = []
    goal = _active_goal(agents)
    if goal:
        done = []
        doing = []
        if brief.primary_experiment and brief.primary_experiment.title:
            status = (brief.primary_experiment.status or "").lower()
            label = brief.primary_experiment.title
            if status in {"executed", "pending"} or brief.primary_experiment.experiment_id:
                doing.append(label)
            elif status in {"proposed", "adopted", ""}:
                doing.append(f"待启动：{label}")
        if memory:
            for item in (memory.items or [])[:2]:
                if item.result == "positive":
                    done.append(item.lesson or item.action_type or "已验证动作")
        threads.append(
            OperatingThreadBrief(
                id="thread:active-goal",
                title=goal.title,
                goal=goal.title,
                done=done,
                doing=doing or ([goal.next_step] if goal.next_step else []),
                next_step=goal.next_step,
                current_result=goal.progress_summary,
                ai_judgment=goal.ai_judgment or "进度正常时不打扰你。",
                needs_owner=bool(brief.primary_experiment and (brief.primary_experiment.status or "proposed") in {"proposed", "adopted", ""}),
            )
        )
    return threads


def build_ops_queue(
    brief: ManagerHomeBrief,
    *,
    events: EventEngineResult | None = None,
    agents: StoreAgentsResponse | None = None,
    strategy_memory: StrategyMemorySnapshot | None = None,
    db=None,
    store_id: str | None = None,
) -> OpsQueueBrief:
    """把事件/实验/记忆仲裁成首页四队列 + Goal/线程。

    V2：传入 db + store_id 时，线程从 DB 读持久化数据（跨日存活）。
    """
    need_you: list[DecisionCard] = []
    working: list[DecisionCard] = []
    results: list[DecisionCard] = []
    opportunities: list[DecisionCard] = []
    noop = 0

    base_disturb_cost = resolve_disturb_cost(db, store_id) if db is not None and store_id else 0.55
    if events:
        for event in events.events:
            if event.status in {"ignored", "resolved"}:
                noop += 1
                continue
            card = _event_card(event, disturb_cost=base_disturb_cost)
            if card is None:
                noop += 1
                continue
            need_you.append(card)

    primary_card = _primary_experiment_card(brief.primary_experiment, brief=brief, disturb_cost=base_disturb_cost)
    if primary_card:
        if primary_card.queue_bucket == "working":
            working.append(primary_card)
        else:
            # 主实验优先置顶
            need_you.insert(0, primary_card)

    for card in _working_cards(agents, brief):
        if card.queue_bucket == "need_you":
            need_you.append(card)
        else:
            working.append(card)

    results.extend(_result_cards(strategy_memory))
    opp = _opportunity_card(brief, disturb_cost=base_disturb_cost)
    if opp:
        opportunities.append(opp)

    # 排序：高优先级在前；need_you 只保留 1 张 NBA（少打扰）
    need_you.sort(key=lambda c: c.priority_score, reverse=True)
    filtered = max(0, len(need_you) - 1)
    noop += filtered
    need_you = need_you[:1]
    working = working[:6]
    results = results[:4]
    opportunities = opportunities[:2]

    return OpsQueueBrief(
        need_you=need_you,
        working=working,
        results=results,
        opportunities=opportunities,
        active_goal=_active_goal(agents),
        threads=_load_threads(db, store_id, agents, brief, strategy_memory),
        filtered_noop_count=noop,
    )


def _load_threads(db, store_id, agents, brief, strategy_memory) -> list:
    """优先从 DB 读持久化线程，无 DB 时回退到内存拼凑。"""
    if db is not None and store_id:
        try:
            from app.services.thread_engine import load_active_threads

            db_threads = load_active_threads(db, store_id)
            if db_threads:
                return db_threads
        except Exception:  # noqa: BLE001
            pass
    return _threads(agents, brief, strategy_memory)
