"""六大主动 Trigger：产出 CandidateAction，不得直达老板。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.schemas.agents import StoreAgentsResponse
from app.schemas.arbiter import InterruptReason
from app.schemas.events import EventEngineResult
from app.schemas.poie import CandidateAction
from app.schemas.strategy_memory import StrategyMemorySnapshot
from app.schemas.store_state import ManagerHomeBrief
from app.services.poie.scoring import score_candidate


def _hour_local() -> int:
    # 简化：按本地机时区（Windows 开发机 UTC+8）
    return datetime.now().astimezone().hour


def trigger_time(
    brief: ManagerHomeBrief,
    agents: StoreAgentsResponse | None,
) -> list[CandidateAction]:
    """Time × State → Next Best Action（不是 cron 提醒）。"""
    hour = _hour_local()
    growth = agents.growth if agents else None
    primary = brief.primary_experiment
    # 午餐前窗口：有主实验/今日优先且状态待确认
    if 10 <= hour <= 11 and primary and (primary.status or "proposed") in {"proposed", "adopted", ""}:
        return [
            CandidateAction(
                id=f"time:lunch:{primary.title}",
                title=primary.title,
                trigger="time",
                insight=growth.reason if growth else "临近午高峰，今天值得提前做主动作。",
                why_now=f"当前 {hour}:00 临近午高峰，结合今日经营状态，这是最佳拍板窗口。",
                already_did="已核对库存/活动/主推状态，并准备好可执行方案。",
                success_metric=primary.expected_metric or "核心指标达标",
                interrupt_reason="time",
                suggested_state="confirm",
                score=score_candidate(
                    business_impact=0.85,
                    urgency=0.8,
                    confidence=0.75,
                    need_for_human=0.85,
                    goal_relevance=0.7,
                    interruption_cost=0.4,
                ),
            )
        ]
    # 晚间：偏结果复盘，不主动新开动作
    if hour >= 21 and growth and growth.today_priority:
        return [
            CandidateAction(
                id="time:evening-hold",
                title="今晚不再新开动作",
                trigger="time",
                insight="数据未完整，明早再复盘更稳。",
                why_now="已过经营动作窗口。",
                already_did="后台继续监控实验与评价。",
                success_metric="明早完整数据后再评估",
                interrupt_reason="time",
                suggested_state="noop",
                score=score_candidate(
                    business_impact=0.2,
                    urgency=0.2,
                    confidence=0.9,
                    need_for_human=0.05,
                    goal_relevance=0.3,
                    interruption_cost=0.9,
                ),
            )
        ]
    return []


def trigger_anomaly(events: EventEngineResult | None) -> list[CandidateAction]:
    """异常：Event → Insight → Candidate（V1 §18 三层收敛）。

    先从 Event 生成 Insight（AI 诊断结论），再决定是否升级为 Candidate。
    只有通过了 Insight 收敛的才进入仲裁。
    """
    if not events:
        return []
    out: list[CandidateAction] = []
    for event in events.events:
        if event.status in {"ignored", "resolved"}:
            continue
        ai_action = getattr(event, "ai_action", None) or ""
        decision = event.manager_decision or "record"

        # Insight 收敛层（V1 §18 补全）：Event → Insight
        # 不是所有 Event 都能升级——必须有 estimated_impact 才算有诊断结论
        insight_judgment = event.estimated_impact or event.detail or ""
        if not insight_judgment:
            continue  # 无诊断结论的 Event 不升级
        # 低置信度 + 非 critical 的噪音事件不升级
        if (event.confidence or 0.7) < 0.5 and event.severity not in ("critical", "high"):
            continue
        if ai_action in {"silent_observe", "auto_handle", "inform_only"} and decision not in {
            "handle_today",
            "alert_owner",
        }:
            continue
        if decision not in {"handle_today", "alert_owner"} and ai_action not in {
            "need_confirm",
            "need_assist",
        }:
            continue
        need_human = 1.0 if decision == "alert_owner" or ai_action == "need_assist" else 0.85
        urgency = {"critical": 1.0, "high": 0.85, "medium": 0.55}.get(event.severity, 0.4)
        impact = 0.7
        if event.estimated_impact_amount:
            impact = min(1.0, 0.45 + float(event.estimated_impact_amount) / 100)
        out.append(
            CandidateAction(
                id=f"anomaly:{event.fingerprint or event.id}",
                title=event.title,
                trigger="anomaly",
                insight=event.estimated_impact or event.detail or "",
                why_now=event.detail or event.title,
                already_did="已完成第一轮诊断，排除了可自动处理的噪音。",
                success_metric="异常信号收敛",
                interrupt_reason="anomaly",
                suggested_state="need_input" if ai_action == "need_assist" else "confirm",
                score=score_candidate(
                    business_impact=impact,
                    urgency=urgency,
                    confidence=event.confidence or 0.7,
                    need_for_human=need_human,
                    goal_relevance=0.55,
                    interruption_cost=0.35 if decision == "alert_owner" else 0.5,
                ),
            )
        )
    return out


def trigger_history(db: Session | None, store_id: str) -> list[CandidateAction]:
    """事项续航：活跃 WorkThread。"""
    if db is None:
        return []
    try:
        from app.services.thread_engine import load_active_threads

        threads = load_active_threads(db, store_id)
    except Exception:  # noqa: BLE001
        return []
    out: list[CandidateAction] = []
    for thread in threads[:5]:
        if thread.needs_owner:
            out.append(
                CandidateAction(
                    id=f"history:{thread.id}",
                    title=thread.title,
                    trigger="history",
                    insight=thread.ai_judgment or "经营线程推进到需要你的节点。",
                    why_now=thread.next_step or "这件事还没结束，卡在人工节点。",
                    already_did="；".join(thread.done[:2]) if thread.done else "已记住上下文并持续推进。",
                    success_metric=thread.goal or "线程目标达成",
                    interrupt_reason="history",
                    suggested_state="need_input",
                    score=score_candidate(
                        business_impact=0.75,
                        urgency=0.65,
                        confidence=0.8,
                        need_for_human=0.9,
                        goal_relevance=0.9,
                        interruption_cost=0.45,
                    ),
                )
            )
        else:
            # 不打扰：仅作为 working 候选
            out.append(
                CandidateAction(
                    id=f"history-auto:{thread.id}",
                    title=thread.title,
                    trigger="history",
                    insight=thread.ai_judgment or "进度正常，暂时不需要你介入。",
                    why_now="经营线程自动续航中。",
                    already_did="；".join(thread.doing[:2]) if thread.doing else "后台推进中",
                    success_metric=thread.goal or "",
                    interrupt_reason="history",
                    suggested_state="auto_do",
                    score=score_candidate(
                        business_impact=0.5,
                        urgency=0.3,
                        confidence=0.8,
                        need_for_human=0.1,
                        goal_relevance=0.85,
                        interruption_cost=0.8,
                    ),
                )
            )
    return out


def trigger_opportunity(
    db: Session | None,
    store_id: str,
    agents: StoreAgentsResponse | None,
    brief: ManagerHomeBrief,
) -> list[CandidateAction]:
    """找钱机会（非救火）。"""
    triggers: list[Any] = []
    if agents is not None:
        try:
            from app.services.opportunity_scanner import (
                scan_competitor_gap,
                scan_daypart_untapped,
                scan_subsidy_opportunity,
            )

            for fn in (scan_subsidy_opportunity, scan_competitor_gap):
                hit = fn(agents)
                if hit:
                    triggers.append(hit)
            hit = scan_daypart_untapped(agents, [])
            if hit:
                triggers.append(hit)
        except Exception:  # noqa: BLE001
            pass
    elif db is not None:
        try:
            from app.services.opportunity_scanner import scan_opportunities

            triggers = scan_opportunities(db, store_id, days=7)
        except Exception:  # noqa: BLE001
            triggers = []

    if not triggers and brief.top_opportunity_title:
        return [
            CandidateAction(
                id=f"opp:brief:{brief.top_opportunity_title}",
                title=brief.top_opportunity_title,
                trigger="opportunity",
                insight=brief.top_opportunity_detail or "",
                why_now="现在不做也不会出事，但做了可能多赚钱。",
                already_did="已扫描商圈/活动/竞品变化。",
                success_metric="抓住窗口后订单或份额可见提升",
                interrupt_reason="opportunity",
                suggested_state="confirm",
                score=score_candidate(
                    business_impact=0.65,
                    urgency=0.45,
                    confidence=0.65,
                    need_for_human=0.35,
                    goal_relevance=0.55,
                    interruption_cost=0.7,
                ),
            )
        ]

    out: list[CandidateAction] = []
    for opp in triggers[:3]:
        out.append(
            CandidateAction(
                id=f"opp:{opp.key}",
                title=opp.title,
                trigger="opportunity",
                insight=opp.detail,
                why_now=opp.window or "出现短期经营窗口。",
                already_did="机会引擎已完成扫描。",
                success_metric=opp.expected_gain or "增量收益可见",
                interrupt_reason="opportunity",
                suggested_state="confirm",
                score=score_candidate(
                    business_impact=0.7,
                    urgency=0.55,
                    confidence=0.7,
                    need_for_human=0.4,
                    goal_relevance=0.6,
                    interruption_cost=0.65,
                ),
            )
        )
    return out


def trigger_goal(db: Session | None, store_id: str) -> list[CandidateAction]:
    """目标偏差：Forecast vs Target。"""
    if db is None:
        return []
    try:
        from app.services.goal_engine import check_goal_deviation, load_goal_snapshot

        alerts = check_goal_deviation(db, store_id)
        if not alerts:
            snap = load_goal_snapshot(db, store_id)
            alerts = snap.deviation_alerts or []
    except Exception:  # noqa: BLE001
        return []

    out: list[CandidateAction] = []
    for goal in alerts[:3]:
        gap = goal.gap
        gap_txt = f"缺口 {gap:g}" if gap is not None else "进度偏离"
        out.append(
            CandidateAction(
                id=f"goal:{goal.id}",
                title=f"目标偏离：{goal.raw_text}",
                trigger="goal",
                insight=f"预测 {goal.forecast_value} vs 目标 {goal.target_value}，{gap_txt}。",
                why_now="按你想要的结果，我们正在偏离计划。",
                already_did="已完成目标进度同步与路径粗拆。",
                success_metric=f"回到目标轨道（{goal.metric}）",
                interrupt_reason="goal",
                suggested_state="confirm",
                score=score_candidate(
                    business_impact=0.9,
                    urgency=0.75,
                    confidence=0.7,
                    need_for_human=0.7,
                    goal_relevance=1.0,
                    interruption_cost=0.4,
                ),
            )
        )
    return out


def trigger_result(memory: StrategyMemorySnapshot | None) -> list[CandidateAction]:
    """结果评估：有效/无效 → 通知或自动下一步。"""
    if not memory:
        return []
    out: list[CandidateAction] = []
    for item in (memory.items or [])[:4]:
        positive = item.result == "positive"
        negative = item.result == "negative"
        out.append(
            CandidateAction(
                id=f"result:{item.id}",
                title=item.lesson or item.action_type,
                trigger="result",
                insight=("有效，已写入策略记忆。" if positive else "效果不佳，建议停止或换方案。" if negative else "继续观察。"),
                why_now="上次动作已经有答案了。",
                already_did="完成实验评估并沉淀经验。",
                success_metric=f"结果：{item.result}" + (f" · {item.lift_pct:+.1f}%" if item.lift_pct is not None else ""),
                interrupt_reason="result",
                suggested_state="report_result",
                score=score_candidate(
                    business_impact=0.55 if positive or negative else 0.35,
                    urgency=0.4,
                    confidence=0.85,
                    need_for_human=0.15,
                    goal_relevance=0.5,
                    interruption_cost=0.5,
                ),
            )
        )
    return out


def trigger_understanding(
    db: Session | None,
    store_id: str,
    agents: StoreAgentsResponse | None,
) -> list[CandidateAction]:
    """MUE 缺口：Ask Only What AI Cannot Know → need_input。

    A3 升级：按缺口是否 blocking MOS 动态调整优先级——
    blocking 缺口 urgency=0.9（必须现在问），非 blocking 缺口 urgency=0.4（可以等等）。
    """
    if db is None:
        return []
    try:
        from app.services.mue import ensure_understanding, understanding_gap_candidate

        u = ensure_understanding(db, store_id, agents=agents)
        gap = understanding_gap_candidate(u)
    except Exception:  # noqa: BLE001
        return []
    if not gap:
        return []

    # 判断这个缺口是否阻塞 MOS
    gap_key = gap.get("key", "")
    is_blocking = gap_key in (u.mos_blocking_fields or [])

    # Ask Engine：用 ask_score 判断值不值得问（Content Engine V1 §06）
    from app.services.ask_engine import should_ask

    ask_worthy, ask_score = should_ask(
        field_key=gap_key,
        decision_impact=0.85 if is_blocking else 0.5,
        confidence=0.3,
        urgency=0.9 if is_blocking else 0.4,
        interruption_cost=0.3 if is_blocking else 0.6,
    )
    if not ask_worthy and not is_blocking:
        return []  # Ask Engine 判定不值得问，静默
    urgency = 0.9 if is_blocking else 0.4
    impact = 0.85 if is_blocking else 0.55
    interrupt_cost = 0.3 if is_blocking else 0.6  # blocking 时打扰成本低（值得打扰）

    return [
        CandidateAction(
            id=gap["id"],
            title=gap["title"],
            trigger="understanding",
            insight=gap.get("insight") or "",
            why_now=gap.get("why_now") or "平台数据里读不到，但会影响经营判断。",
            already_did=f"已从平台自动读到约 {u.known_count} 项，只问真正缺的。{'这个信息会影响关键决策，所以现在值得问。' if is_blocking else ''}",
            success_metric="补齐后按你的原则自动经营",
            interrupt_reason="understanding",
            suggested_state="need_input" if is_blocking else "noop",  # 非 blocking 不打扰
            score=score_candidate(
                business_impact=impact,
                urgency=urgency,
                confidence=0.9,
                need_for_human=1.0 if is_blocking else 0.6,
                goal_relevance=0.85 if is_blocking else 0.5,
                interruption_cost=interrupt_cost,
            ),
        )
    ]


def trigger_onboarding(
    db: Session | None,
    store_id: str,
    agents: StoreAgentsResponse | None,
) -> list[CandidateAction]:
    """Connect 阶段：AI 引导老板连接平台。

    onboarding_stage=connect 时产生"请先连接外卖平台"的卡片。
    """
    if db is None:
        return []
    try:
        from app.services.mue import ensure_understanding

        u = ensure_understanding(db, store_id, agents=agents)
        if u.onboarding_stage != "connect":
            return []
    except Exception:  # noqa: BLE001
        return []

    return [
        CandidateAction(
            id="onboarding:connect-platform",
            title="先连接你的外卖平台",
            trigger="understanding",
            insight="连接后我会自动读取菜单、订单、评价和经营数据，然后开始帮你经营。",
            why_now="我需要看到你的真实经营数据才能开始工作。连接美团或饿了么大约需要 30 秒。",
            already_did="我已经准备好了分析引擎，连接后立即开始诊断。",
            success_metric="平台连接成功，StoreState 建立",
            interrupt_reason="understanding",
            suggested_state="need_input",
            score=score_candidate(
                business_impact=1.0,
                urgency=1.0,
                confidence=1.0,
                need_for_human=1.0,
                goal_relevance=1.0,
                interruption_cost=0.1,
            ),
        )
    ]


def collect_candidates(
    brief: ManagerHomeBrief,
    *,
    store_id: str,
    events: EventEngineResult | None = None,
    agents: StoreAgentsResponse | None = None,
    strategy_memory: StrategyMemorySnapshot | None = None,
    db: Session | None = None,
) -> list[CandidateAction]:
    """汇流六大 Trigger + MUE 理解缺口 + onboarding 引导；仍需仲裁后才能进前台。"""
    candidates: list[CandidateAction] = []
    candidates.extend(trigger_onboarding(db, store_id, agents))  # connect 阶段优先
    candidates.extend(trigger_understanding(db, store_id, agents))
    candidates.extend(trigger_time(brief, agents))
    candidates.extend(trigger_anomaly(events))
    candidates.extend(trigger_history(db, store_id))
    candidates.extend(trigger_opportunity(db, store_id, agents, brief))
    candidates.extend(trigger_goal(db, store_id))
    candidates.extend(trigger_result(strategy_memory))
    return candidates
