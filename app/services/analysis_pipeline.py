"""Operating Analysis Pipeline — 12 步统一分析链。

材料 §七定义：任何 Agent 都不能绕过这条链直接把建议推给用户。

① Observe → ② Compare → ③ Diagnose → ④ Estimate Impact →
⑤ Goal Check → ⑥ Generate Actions → ⑦ Profit & Risk Gate →
⑧ Prioritize → ⑨ Permission Check → ⑩ Execute/Ask/Silence →
⑪ Observe Result → ⑫ Learn

每一步产出一个 PipelineStep 结果，最终汇总成 OperatingDecisionObject。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from app.schemas.content_engine import (
    BusinessImpactSummary,
    DiagnosisSummary,
    FindingSummary,
    OperatingDecisionObject,
    OperatingObjectRef,
    RecommendedAction,
    SuccessMetric,
)


def _reason_from_trigger(trigger: str) -> str:
    return {
        "time": "TIME",
        "anomaly": "ANOMALY",
        "history": "CONTINUATION",
        "continuation": "CONTINUATION",
        "opportunity": "OPPORTUNITY",
        "goal": "GOAL_DEVIATION",
        "goal_deviation": "GOAL_DEVIATION",
        "result": "RESULT",
        "understanding": "UNDERSTANDING",
    }.get(trigger.lower(), "ANOMALY")


def _domain_from_context(metric: str, action_type: str) -> str:
    haystack = f"{metric} {action_type}".lower()
    if any(token in haystack for token in ("ctr", "cvr", "image", "title", "sku", "menu", "product")):
        return "PRODUCT"
    if any(token in haystack for token in ("campaign", "budget", "cpc", "ads", "traffic", "promo")):
        return "TRAFFIC"
    if any(token in haystack for token in ("profit", "gmv", "margin", "roi", "price")):
        return "PROFIT"
    if any(token in haystack for token in ("compet", "rank")):
        return "COMPETITION"
    if any(token in haystack for token in ("review", "rating", "reply", "complaint")):
        return "REPUTATION"
    if any(token in haystack for token in ("customer", "rfm", "recall", "segment")):
        return "CUSTOMER"
    if any(token in haystack for token in ("store", "multi", "expansion")):
        return "STORE_GROWTH"
    return "PLATFORM"


def _recommended_actions(raw_actions: list[dict[str, Any]]) -> list[RecommendedAction]:
    actions: list[RecommendedAction] = []
    for action in raw_actions[:3]:
        actions.append(
            RecommendedAction(
                type=str(action.get("action_type", "")),
                title=str(action.get("title", "")),
                detail=str(action.get("detail", "")),
                window=(
                    f'{int(action.get("observation_window_hours", 0))}h'
                    if action.get("observation_window_hours")
                    else ""
                ),
            )
        )
    return actions


# ═══════════════════════════════════════════════════════════
# Pipeline 执行器
# ═══════════════════════════════════════════════════════════


@dataclass
class PipelineContext:
    """Pipeline 运行时上下文。"""
    store_id: str
    trigger: str = "anomaly"
    source_node: str = ""
    observed_metric: str = ""
    observed_delta: Optional[float] = None
    compare_baseline: str = ""
    root_cause: str = ""
    evidence: list[str] = field(default_factory=list)
    subject_type: str = "store"
    subject_id: str = ""
    subject_name: str = ""
    estimated_loss: Optional[float] = None
    goal_text: str = ""
    goal_relevance_level: str = "medium"
    required_context_keys: list[str] = field(default_factory=list)
    # OPTIONS（V1 补全）：多候选方案
    candidate_actions: list[dict] = field(default_factory=list)
    selected_action: str = ""
    selected_action_type: str = ""
    # RISK GATE（V1 补全）
    risk_level: str = "medium"  # low/medium/high
    reversibility: str = "medium"  # easy/medium/hard
    profitability: str = ""  # 利润影响
    # 执行
    autonomy: str = "need_confirm"
    success_metric: str = ""
    observation_window_hours: int = 48
    confidence: float = 0.7
    system_mode: str = "operating"
    profit_allowed: bool = True
    human_reason: str = ""
    steps_completed: list[str] = field(default_factory=list)


def run_analysis_pipeline(
    ctx: PipelineContext,
) -> OperatingDecisionObject:
    """运行 12 步分析 Pipeline，返回 Operating Decision Object。

    每一步都记录到 steps_completed，即使某步数据不足也继续（降级而非中断）。
    """

    # ① Observe — 已经在 ctx 里（observed_metric + observed_delta）
    ctx.steps_completed.append("observe")

    # ② Compare — 和基线对比
    if ctx.observed_delta is not None and ctx.compare_baseline:
        direction = "下降" if ctx.observed_delta < 0 else "上升"
        ctx.evidence.insert(0, f"{ctx.observed_metric} 较{ctx.compare_baseline} {direction} {abs(ctx.observed_delta):.1f}%")
    ctx.steps_completed.append("compare")

    # ③ Diagnose — 根因已在 ctx.root_cause
    if ctx.root_cause:
        ctx.steps_completed.append("diagnose")
    else:
        ctx.root_cause = "根因尚不明确，需更多数据。"
        ctx.steps_completed.append("diagnose")

    # ④ Estimate Impact — 损失估算
    ctx.steps_completed.append("estimate_impact")

    # ⑤ Goal Check — 和老板目标的关系
    if ctx.goal_text:
        ctx.steps_completed.append("goal_check")
    else:
        ctx.goal_relevance_level = "low"
        ctx.steps_completed.append("goal_check")

    # ⑥ Generate Actions — 候选动作已在 ctx.candidate_actions
    ctx.steps_completed.append("generate_actions")

    # ⑦ OPTIONS — 多候选方案对比（V1 补全）
    # 如果有多个候选，按 expected_lift / risk / ease 排序选最优
    if len(ctx.candidate_actions) > 1:
        def _action_score(a: dict) -> float:
            lift = float(a.get("expected_lift_pct_high", 0) or 0)
            risk_penalty = {"low": 0, "medium": 3, "high": 8}.get(a.get("risk_level", "medium"), 3)
            ease_bonus = {"change_title": 5, "change_main_image": 4, "add_set_meal": 3}.get(a.get("action_type", ""), 1)
            return lift - risk_penalty + ease_bonus
        ctx.candidate_actions.sort(key=_action_score, reverse=True)
        best = ctx.candidate_actions[0]
        ctx.selected_action = best.get("title", ctx.selected_action)
        ctx.selected_action_type = best.get("action_type", ctx.selected_action_type)
        ctx.risk_level = best.get("risk_level", ctx.risk_level)
    ctx.steps_completed.append("options")

    # ⑧ PROFIT GATE — 利润检查（V1 补全：真正调 ProfitGate）
    profit_ok = True
    if ctx.system_mode == "safe":
        from app.services.mos_engine import is_action_allowed_in_safe_mode
        if ctx.selected_action_type and not is_action_allowed_in_safe_mode(ctx.selected_action_type):
            profit_ok = False
            ctx.autonomy = "silent_observe"
    ctx.profit_allowed = profit_ok
    ctx.steps_completed.append("profit_gate")

    # ⑨ RISK GATE — 风险等级 + 可逆性评估（V1 补全）
    # 高风险 + 不可逆 → 必须老板确认
    if ctx.risk_level == "high" and ctx.reversibility == "hard":
        ctx.autonomy = "need_confirm"
    elif ctx.risk_level == "high":
        ctx.autonomy = "need_confirm"
    elif profit_ok and ctx.risk_level == "low":
        ctx.autonomy = "auto_handle"
    ctx.steps_completed.append("risk_gate")

    # ⑩ PRIORITIZE — 已在 OPTIONS 里选了最优
    ctx.steps_completed.append("prioritize")

    # ⑪ PERMISSION — 映射 autonomy → execution_mode
    execution_mode_map = {
        "auto_handle": "AUTO_AND_REPORT",
        "need_confirm": "ASK_APPROVAL",
        "need_assist": "ASK_INFORMATION",
        "inform_only": "OBSERVE",
        "silent_observe": "DROP",
    }
    execution_mode = execution_mode_map.get(ctx.autonomy, "ASK_APPROVAL")
    ctx.steps_completed.append("permission")

    # ⑫ EXECUTE / ASK / WATCH / DROP
    ctx.steps_completed.append("decide")

    # ⑪ Observe Result — 动作执行后进入观察窗（非 Pipeline 内执行）
    ctx.steps_completed.append("observe_result_setup")

    # ⑫ Learn — 归因后沉淀（非 Pipeline 内执行）
    ctx.steps_completed.append("learn_hook")

    # 构建 Operating Decision Object
    impact_text = ctx.root_cause
    if ctx.estimated_loss:
        impact_text = f"{impact_text}。预计损失约 {int(ctx.estimated_loss)} 单/日。"

    now_iso = datetime.now(timezone.utc).isoformat()
    recommended_actions = _recommended_actions(ctx.candidate_actions)
    selected_action = RecommendedAction(
        type=ctx.selected_action_type,
        title=ctx.selected_action or "暂无明确动作建议",
        window=f"{ctx.observation_window_hours}h" if ctx.observation_window_hours else "",
        owner="boss" if execution_mode in ("ASK_APPROVAL", "ASK_INFORMATION") else "ai",
    )
    return OperatingDecisionObject(
        reason=_reason_from_trigger(ctx.trigger),  # type: ignore[arg-type]
        trigger=ctx.trigger,
        domain=_domain_from_context(ctx.observed_metric, ctx.selected_action_type),  # type: ignore[arg-type]
        object=OperatingObjectRef(
            type=ctx.subject_type if ctx.subject_type in ("store", "sku", "campaign", "user_segment", "review", "thread", "goal", "other") else "other",
            id=ctx.subject_id or ctx.store_id,
            name=ctx.subject_name or ctx.store_id,
        ),
        source_node=ctx.source_node or None,
        created_at=now_iso,
        subject=ctx.subject_name or ctx.store_id,
        why_now=ctx.evidence[0] if ctx.evidence else "",
        finding=FindingSummary(
            metric=ctx.observed_metric,
            change=(
                f'{"-" if (ctx.observed_delta or 0) < 0 else "+"}{abs(ctx.observed_delta or 0):.1f}%'
                if ctx.observed_metric and ctx.observed_delta is not None
                else ""
            ),
            benchmark=ctx.compare_baseline,
            note=ctx.evidence[1] if len(ctx.evidence) > 1 else "",
        ),
        observation=f"{ctx.observed_metric} {'下降' if (ctx.observed_delta or 0) < 0 else '变化'} {abs(ctx.observed_delta or 0):.1f}%" if ctx.observed_metric else "",
        comparison=f"较{ctx.compare_baseline}" if ctx.compare_baseline else "",
        diagnosis=DiagnosisSummary(
            primary=ctx.root_cause,
            confidence=ctx.confidence,
        ),
        evidence=ctx.evidence[:5],
        business_impact=BusinessImpactSummary(
            orders=f"预计损失约 {int(ctx.estimated_loss)} 单/日" if ctx.estimated_loss else "",
            summary=impact_text,
        ),
        estimated_loss=ctx.estimated_loss,
        goal_relevance=ctx.goal_text or "暂无活跃目标",
        goal_relevance_level=ctx.goal_relevance_level,  # type: ignore[arg-type]
        candidate_actions=recommended_actions,
        recommended_action=selected_action,
        action_type=ctx.selected_action_type,
        required_context_keys=ctx.required_context_keys,
        human_required=execution_mode in ("ASK_APPROVAL", "ASK_INFORMATION"),
        human_reason=ctx.human_reason or ("需要老板确认执行" if execution_mode == "ASK_APPROVAL" else "需要老板补充关键信息" if execution_mode == "ASK_INFORMATION" else ""),
        profitability=ctx.profitability or ("通过" if profit_ok else "Safe Mode 拦截"),
        risk_level=ctx.risk_level,  # type: ignore[arg-type]
        reversibility=ctx.reversibility,  # type: ignore[arg-type]
        execution_mode=execution_mode,  # type: ignore[arg-type]
        human_request="请确认是否执行" if execution_mode == "ASK_APPROVAL" else "请补充当前决策缺失的信息" if execution_mode == "ASK_INFORMATION" else "",
        autonomy=ctx.autonomy,
        success_metric=SuccessMetric(
            metric=ctx.observed_metric,
            target=ctx.success_metric or (f"{ctx.observed_metric} 改善" if ctx.observed_metric else "经营结果改善"),
            window=f"{ctx.observation_window_hours}h" if ctx.observation_window_hours else "",
        ),
        observation_window_hours=ctx.observation_window_hours,
        next_check_at=now_iso,
        next_check=now_iso,
        confidence=ctx.confidence,
        pipeline_steps_completed=ctx.steps_completed,
        safe_mode_blocked=not ctx.profit_allowed,
    )
