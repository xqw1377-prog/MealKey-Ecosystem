from __future__ import annotations
from typing import Any
from app.models.ohre import Recommendation
from app.schemas.agents import (
    AdsAgentResult,
    AgentWorkflowItem,
    CompetitionAgentResult,
    CrmAgentResult,
    DiagnosisAgentResult,
    GrowthActionView,
    GrowthAgentResult,
    GrowthOpportunityView,
    GrowthPlanStep,
    GrowthScoreFactors,
    MenuAgentResult,
    ProductAgentResult,
    PromoAgentResult,
    ReviewAgentResult,
    ServiceAgentResult,
    StoreMatrixAgentResult,
)
from app.services.profit_gate import evaluate_profit_gate
from app.schemas.strategy_memory import StrategyMemorySnapshot
from app.services.agent_narrator import narrate_growth

from .types import _AgentContext
from .helpers import (
    _agent_meta,
    _normalize_text,
    _problem_summary,
    _recommendation_evidence,
    _recommendation_priority,
    _recommendation_summary,
    _recommendation_title,
)
from .workflow import (
    _current_action,
    _dedupe_workflow_items,
    _experiment_map,
    _workflow_item,
    _workflow_phase_rank,
)
from .menu import _alignment_readiness, _document_blockers

def _dedupe_growth_actions(actions: list[GrowthActionView]) -> list[GrowthActionView]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[GrowthActionView] = []
    for action in actions:
        key = (
            action.action_type,
            _normalize_text(action.title),
            _normalize_text(action.object_name),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped

def _growth_is_discount_action(action_type: str | None) -> bool:
    return action_type in {
        "store_discount",
        "join_lunch_campaign",
        "match_competitor_promo",
        "launch_value_bundle_promo",
        "boost_hero_item_ads",
        "shift_ads_to_high_cvr_item",
    }

def _growth_action_bias(action_type: str | None) -> tuple[int, int]:
    if action_type in {
        "change_main_image",
        "change_title",
        "refresh_hero_image",
        "refresh_signature_card",
        "fix_top_review_theme",
        "batch_reply_negative_reviews",
        "reply_ordinary_reviews",
    }:
        return (0, 0)
    if action_type in {
        "menu_patch",
        "menu_cleanup",
        "add_set_meal",
        "adjust_price_value",
        "surface_set_meal",
        "recall_churn_risk_users",
        "nurture_new_customers",
    }:
        return (0, 1)
    if action_type in {"diagnosis_priority", "competition_response", "pin_positive_review_themes"}:
        return (0, 2)
    if action_type in {
        "open_lunch_online_store",
        "open_night_online_store",
        "open_value_online_store",
    }:
        return (1, 4)
    if _growth_is_discount_action(action_type):
        return (1, 3)
    return (0, 4)

def _growth_synthetic_current_action(ctx: _AgentContext, selected: GrowthOpportunityView) -> AgentWorkflowItem:
    focus_note = (
        f"当前先推进 {selected.title}，折扣动作保留作后备，只有前序低风险动作无效时再考虑。"
        if not _growth_is_discount_action(selected.action_type)
        else "当前先推进这条动作，并在观察窗结束后再决定是否切换。"
    )
    confidence = 0.7
    if selected.factors is not None:
        confidence = max(0.3, min(0.95, float(selected.factors.confidence) / 5.0))
    return AgentWorkflowItem(
        recommendation_id=selected.recommendation_id or selected.key,
        title=selected.title,
        action_type=selected.action_type,
        object_ref=f"synthetic:{selected.key}",
        object_name=selected.object_name,
        status="proposed",
        execution_phase="execute_now",
        phase_reason=focus_note,
        expected_metric=selected.expected_metric,
        window_hours=72,
        confidence=confidence,
        evidence=selected.evidence[:4],
        generated_content={
            "source_agent": selected.source_agent,
            "synthetic": True,
            "selection_reason": focus_note,
        },
        next_decision=f"先看 {selected.expected_metric} 是否进入正向变化，再决定要不要切到折扣动作。",
    )

def _growth_sync_queue_with_selection(
    ctx: _AgentContext,
    queue: list[AgentWorkflowItem],
    selected: GrowthOpportunityView | None,
) -> tuple[list[AgentWorkflowItem], AgentWorkflowItem | None]:
    current_action = _current_action(queue)
    if (
        current_action is None
        or selected is None
        or not _growth_is_discount_action(current_action.action_type)
        or current_action.execution_phase != "execute_now"
        or _growth_is_discount_action(selected.action_type)
    ):
        return queue, current_action

    deferred_reason = (
        f"这条折扣动作先保留在队列里，但今天先推进 {selected.title}。"
        " 只有前序低风险动作无效时，再考虑启用折扣。"
    )
    synced_queue: list[AgentWorkflowItem] = []
    for item in queue:
        if item.recommendation_id == current_action.recommendation_id:
            synced_queue.append(
                item.model_copy(
                    update={
                        "execution_phase": "deferred",
                        "phase_reason": deferred_reason,
                        "next_decision": f"先看 {selected.expected_metric} 的变化，再决定是否需要折扣。",
                        "generated_content": {
                            **item.generated_content,
                            "deferred_reason": deferred_reason,
                            "is_backup": True,
                        },
                    }
                )
            )
        else:
            synced_queue.append(item)

    selected_queue_item = None
    if selected.recommendation_id:
        selected_queue_item = next(
            (item for item in synced_queue if item.recommendation_id == selected.recommendation_id),
            None,
        )
    if selected_queue_item is None:
        selected_queue_item = _growth_synthetic_current_action(ctx, selected)
    return synced_queue, selected_queue_item

def _action_view(rec: Recommendation, item_names: dict[str, str]) -> GrowthActionView:
    object_name = "门店整体"
    if rec.object_ref.startswith("item:"):
        object_name = item_names.get(rec.object_ref.split(":", 1)[1], "当前主推商品")
    return GrowthActionView(
        action_type=rec.action_type,
        title=_recommendation_title(rec.action_type),
        object_name=object_name,
        summary=_recommendation_summary(rec.action_type),
        expected_metric=rec.expected_metric,
        window_hours=rec.window_hours,
        confidence=float(rec.confidence),
        score=round(_recommendation_priority(rec), 2),
    )

def _growth_score(
    expected_impact: float,
    confidence: float,
    ease: float,
    strategic_fit: float,
    risk: float,
) -> tuple[float, GrowthScoreFactors]:
    factors = GrowthScoreFactors(
        expected_impact=round(expected_impact, 2),
        confidence=round(confidence, 2),
        ease_of_execution=round(ease, 2),
        strategic_fit=round(strategic_fit, 2),
        risk=round(max(1.0, risk), 2),
    )
    score = expected_impact * confidence * ease * strategic_fit / max(1.0, risk) / 6.25
    return round(min(100.0, score), 1), factors

def _recommendation_source(action_type: str) -> str:
    if action_type in {"menu_patch", "menu_cleanup"}:
        return "menu"
    if action_type in {"change_main_image", "change_title", "add_set_meal", "adjust_price_value"}:
        return "product"
    if action_type in {
        "refresh_hero_image",
        "refresh_signature_card",
        "optimize_category_ia",
        "surface_set_meal",
        "reinforce_rating_zone",
    }:
        return "storefront"
    if action_type in {"join_lunch_campaign", "launch_value_bundle_promo", "match_competitor_promo"}:
        return "promo"
    if action_type in {"boost_hero_item_ads", "shift_ads_to_high_cvr_item", "pause_broad_ads"}:
        return "ads"
    if action_type in {"recall_churn_risk_users", "nurture_new_customers", "reward_vip_repeat"}:
        return "crm"
    if action_type in {
        "batch_reply_negative_reviews",
        "reply_ordinary_reviews",
        "publish_service_reply_scripts",
        "escalate_portion_complaints",
    }:
        return "service"
    if action_type in {
        "fix_top_review_theme",
        "pin_positive_review_themes",
        "reply_rating_critical_reviews",
    }:
        return "review"
    if action_type in {
        "open_lunch_online_store",
        "open_night_online_store",
        "open_value_online_store",
    }:
        return "store_matrix"
    return "diagnosis"

def _append_matrix_opportunities(
    pool: list[GrowthOpportunityView],
    *,
    agent_key: str,
    actions: list[Any],
    unlock_ready: bool = True,
    store_name: str,
    strategy_memory: StrategyMemorySnapshot | None = None,
) -> None:
    if not actions:
        return
    action = actions[0]
    if agent_key in {"promo", "ads", "store_matrix"} and not unlock_ready:
        return
    impact = min(5.0, max(1.0, float(getattr(action, "expected_lift_pct_high", 4) or 4) / 2.5))
    risk = 3.5 if agent_key in {"promo", "ads", "store_matrix"} else 1.4
    ease = 4.5 if agent_key in {"service", "review"} else 3.0
    fit = 4.0 if unlock_ready else 2.5
    fit_delta, risk_delta = _memory_fit_bias(action.action_type, strategy_memory)
    fit = min(5.0, max(1.0, fit + fit_delta))
    risk = min(5.0, max(1.0, risk + risk_delta))
    score, factors = _growth_score(impact, 3.4, ease, fit, risk)
    pool.append(
        GrowthOpportunityView(
            key=f"{agent_key}:{action.action_type}:{action.object_name}",
            source_agent=agent_key,
            title=action.title,
            problem=action.detail,
            action_type=action.action_type,
            object_name=action.object_name or store_name,
            expected_metric=action.expected_metric,
            expected_lift_pct_low=action.expected_lift_pct_low,
            expected_lift_pct_high=action.expected_lift_pct_high,
            score=score,
            factors=factors,
            evidence=list(action.evidence or [])[:3],
            executable=True,
        )
    )

def _memory_fit_bias(action_type: str, memory: StrategyMemorySnapshot | None) -> tuple[float, float]:
    """Return (fit_delta, risk_delta) from Strategy Memory lessons."""
    if memory is None or not memory.items:
        return 0.0, 0.0
    fit_delta = 0.0
    risk_delta = 0.0
    for item in memory.items:
        if item.action_type != action_type:
            continue
        if item.result == "positive":
            fit_delta += 0.6
            risk_delta -= 0.3
        elif item.result == "negative":
            fit_delta -= 0.8
            risk_delta += 1.2
        elif item.result == "neutral":
            fit_delta -= 0.2
    return max(-1.5, min(1.5, fit_delta)), max(-1.0, min(2.0, risk_delta))

def _growth_opportunity_pool(
    ctx: _AgentContext,
    competition: CompetitionAgentResult,
    menu: MenuAgentResult,
    product: ProductAgentResult,
    diagnosis: DiagnosisAgentResult,
    promo: PromoAgentResult | None = None,
    ads: AdsAgentResult | None = None,
    crm: CrmAgentResult | None = None,
    service: ServiceAgentResult | None = None,
    review: ReviewAgentResult | None = None,
    store_matrix: StoreMatrixAgentResult | None = None,
    strategy_memory: StrategyMemorySnapshot | None = None,
) -> list[GrowthOpportunityView]:
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    primary_metric = "ctr" if product.diagnosis_stage == "ctr" else "cvr" if product.diagnosis_stage == "cvr" else "orders"
    ease_map = {
        "change_main_image": 5.0,
        "change_title": 5.0,
        "refresh_hero_image": 5.0,
        "refresh_signature_card": 4.8,
        "optimize_category_ia": 4.4,
        "reinforce_rating_zone": 4.2,
        "surface_set_meal": 3.4,
        "menu_cleanup": 4.3,
        "menu_patch": 3.6,
        "add_set_meal": 3.2,
        "adjust_price_value": 3.0,
        "store_discount": 2.0,
        "fix_top_review_theme": 4.0,
        "batch_reply_negative_reviews": 4.8,
        "reply_ordinary_reviews": 5.0,
        "pin_positive_review_themes": 4.5,
        "reply_rating_critical_reviews": 4.6,
        "recall_churn_risk_users": 3.5,
        "nurture_new_customers": 3.6,
        "reward_vip_repeat": 4.0,
        "publish_service_reply_scripts": 4.7,
        "escalate_portion_complaints": 3.4,
        "launch_value_bundle_promo": 2.8,
        "join_lunch_campaign": 2.2,
        "match_competitor_promo": 2.0,
        "boost_hero_item_ads": 2.0,
        "shift_ads_to_high_cvr_item": 2.3,
        "pause_broad_ads": 4.5,
        "open_lunch_online_store": 1.6,
        "open_night_online_store": 1.5,
        "open_value_online_store": 1.5,
    }
    risk_map = {
        "change_main_image": 1.0,
        "change_title": 1.0,
        "refresh_hero_image": 1.0,
        "refresh_signature_card": 1.1,
        "optimize_category_ia": 1.3,
        "reinforce_rating_zone": 1.2,
        "surface_set_meal": 1.8,
        "menu_cleanup": 1.8,
        "menu_patch": 1.6,
        "add_set_meal": 2.0,
        "adjust_price_value": 2.2,
        "store_discount": 4.0,
        "fix_top_review_theme": 1.5,
        "batch_reply_negative_reviews": 1.0,
        "reply_ordinary_reviews": 0.8,
        "pin_positive_review_themes": 1.1,
        "reply_rating_critical_reviews": 1.1,
        "recall_churn_risk_users": 2.0,
        "nurture_new_customers": 1.8,
        "reward_vip_repeat": 1.4,
        "publish_service_reply_scripts": 1.0,
        "escalate_portion_complaints": 1.8,
        "launch_value_bundle_promo": 2.8,
        "join_lunch_campaign": 3.6,
        "match_competitor_promo": 3.8,
        "boost_hero_item_ads": 4.0,
        "shift_ads_to_high_cvr_item": 3.5,
        "pause_broad_ads": 1.2,
        "open_lunch_online_store": 4.2,
        "open_night_online_store": 4.3,
        "open_value_online_store": 4.3,
    }
    experiment_map = _experiment_map(ctx)
    pool: list[GrowthOpportunityView] = []
    for rec in ctx.recommendations:
        action = _action_view(rec, item_names)
        experiment = experiment_map.get(rec.id)
        impact = min(5.0, max(1.0, float(rec.expected_lift_pct_high or rec.expected_lift_pct_low or 4) / 2.5))
        confidence = min(5.0, max(1.0, float(rec.confidence or 0.5) * 5))
        fit = 5.0 if rec.expected_metric == primary_metric else 4.0 if rec.object_ref.startswith("item:") else 3.2
        risk = risk_map.get(rec.action_type, 2.0)
        if experiment and experiment.result == "positive":
            confidence = min(5.0, confidence + 0.7)
            fit = min(5.0, fit + 0.5)
        elif experiment and experiment.result == "negative":
            confidence = max(1.0, confidence - 1.8)
            risk = min(5.0, risk + 2.0)
        elif experiment and experiment.result == "neutral":
            confidence = max(1.0, confidence - 0.8)
        fit_delta, risk_delta = _memory_fit_bias(rec.action_type, strategy_memory)
        fit = min(5.0, max(1.0, fit + fit_delta))
        risk = min(5.0, max(1.0, risk + risk_delta))
        score, factors = _growth_score(
            impact,
            confidence,
            ease_map.get(rec.action_type, 3.0),
            fit,
            risk,
        )
        recommendation_evidence = _recommendation_evidence(rec) or [action.summary]
        if experiment and experiment.result != "pending":
            recommendation_evidence.append(
                f"历史实验结果：{experiment.result}"
                + (f"，lift {experiment.lift_pct:+.1f}%" if experiment.lift_pct is not None else "")
            )
        pool.append(
            GrowthOpportunityView(
                key=f"recommendation:{rec.id}",
                source_agent=_recommendation_source(rec.action_type),
                title=action.title,
                problem=action.summary,
                action_type=rec.action_type,
                object_name=action.object_name,
                expected_metric=rec.expected_metric,
                expected_lift_pct_low=rec.expected_lift_pct_low,
                expected_lift_pct_high=rec.expected_lift_pct_high,
                score=score,
                factors=factors,
                evidence=recommendation_evidence,
                recommendation_id=rec.id,
                status=rec.status,
                executable=rec.status in {"proposed", "adopted", "executed"},
            )
        )

    if menu.suggested_patches:
        patch = menu.suggested_patches[0]
        score, factors = _growth_score(3.4, 3.6, 3.3, 4.2, 1.8)
        pool.append(
            GrowthOpportunityView(
                key=f"menu:{patch.patch_type}:{patch.item_name}",
                source_agent="menu",
                title=f"补齐菜单结构：{patch.item_name}",
                problem=patch.reason,
                action_type="menu_patch",
                object_name=patch.item_name,
                expected_metric="orders",
                expected_lift_pct_low=2,
                expected_lift_pct_high=8,
                score=score,
                factors=factors,
                evidence=[patch.reason, patch.expected_outcome],
                executable=True,
            )
        )
    if competition.actions:
        score, factors = _growth_score(
            3.2,
            min(5.0, max(1.0, float(competition.meta.confidence or 0.5) * 5)),
            3.5,
            3.8,
            1.7,
        )
        pool.append(
            GrowthOpportunityView(
                key="competition:response",
                source_agent="competition",
                title="应对商圈竞争变化",
                problem=competition.conclusion,
                action_type="competition_response",
                object_name=ctx.store.name,
                expected_metric="orders",
                expected_lift_pct_low=1,
                expected_lift_pct_high=5,
                score=score,
                factors=factors,
                evidence=competition.evidence[:3],
                executable=True,
            )
        )
    if diagnosis.root_causes:
        root = diagnosis.root_causes[0]
        priority = diagnosis.action_priorities[0] if diagnosis.action_priorities else root.explanation
        score, factors = _growth_score(4.0, root.confidence * 5, 3.8, 5.0, 1.4)
        pool.append(
            GrowthOpportunityView(
                key=f"diagnosis:{root.code}",
                source_agent="diagnosis",
                title=f"先解决：{root.title}",
                problem=priority,
                action_type="diagnosis_priority",
                object_name=ctx.store.name,
                expected_metric=root.affected_metrics[0] if root.affected_metrics else "orders",
                score=score,
                factors=factors,
                evidence=root.evidence,
                executable=root.code != "no_strong_anomaly",
            )
        )

    if review is not None:
        _append_matrix_opportunities(
            pool,
            agent_key="review",
            actions=review.priority_actions,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if service is not None:
        _append_matrix_opportunities(
            pool,
            agent_key="service",
            actions=service.priority_actions,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if crm is not None:
        _append_matrix_opportunities(
            pool,
            agent_key="crm",
            actions=crm.priority_actions,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if promo is not None:
        gated_promo = [
            action
            for action in promo.priority_actions[:2]
            if evaluate_profit_gate(
                ctx.store_state.profit,
                action_type=action.action_type,
                expected_order_lift_pct=float(action.expected_lift_pct_high or 0),
                system_mode=ctx.system_mode,
            ).allowed
        ]
        _append_matrix_opportunities(
            pool,
            agent_key="promo",
            actions=gated_promo,
            unlock_ready=promo.unlock_ready,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if ads is not None:
        gated_ads = [
            action
            for action in ads.priority_actions[:2]
            if evaluate_profit_gate(
                ctx.store_state.profit,
                action_type=action.action_type,
                expected_order_lift_pct=float(action.expected_lift_pct_high or 0),
                system_mode=ctx.system_mode,
            ).allowed
        ]
        _append_matrix_opportunities(
            pool,
            agent_key="ads",
            actions=gated_ads,
            unlock_ready=ads.unlock_ready,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )
    if store_matrix is not None:
        _append_matrix_opportunities(
            pool,
            agent_key="store_matrix",
            actions=store_matrix.priority_actions,
            unlock_ready=store_matrix.unlock_ready,
            store_name=ctx.store.name,
            strategy_memory=strategy_memory,
        )

    unique: dict[tuple[str, str], GrowthOpportunityView] = {}
    for opportunity in sorted(pool, key=lambda row: row.score, reverse=True):
        unique.setdefault((opportunity.action_type, opportunity.object_name), opportunity)
    from app.services.action_ranker import apply_memory_to_growth_pool

    return apply_memory_to_growth_pool(list(unique.values())[:8], strategy_memory)

def _growth_today_priority(
    current_action: AgentWorkflowItem | None,
    top_actions: list[GrowthActionView],
    selected: GrowthOpportunityView | None,
    weekly_plan: list[GrowthPlanStep],
) -> str | None:
    if current_action is not None:
        if current_action.execution_phase == "execute_now" and not _growth_is_discount_action(current_action.action_type):
            return current_action.title
        if current_action.execution_phase in {"observe", "review"}:
            return current_action.next_decision or current_action.phase_reason or current_action.title
    if selected is not None and not _growth_is_discount_action(selected.action_type):
        return selected.title
    if top_actions:
        preferred = next((action for action in top_actions if not _growth_is_discount_action(action.action_type)), None)
        return (preferred or top_actions[0]).title
    return weekly_plan[0].title if weekly_plan else None

def _build_growth_plan(
    ctx: _AgentContext,
    top_actions: list[GrowthActionView],
    current_action: AgentWorkflowItem | None,
    selected: GrowthOpportunityView | None,
    opportunity_pool: list[GrowthOpportunityView],
) -> list[GrowthPlanStep]:
    focus = (
        f"先改善 {selected.expected_metric}"
        if selected
        else "先修点击吸引力"
        if ctx.store_state.primary_problem and ctx.store_state.primary_problem.type == "store_ctr_down"
        else "先修转化承接"
    )
    pending_count = sum(1 for exp in ctx.experiments if exp.result == "pending")
    backup = next((row for row in opportunity_pool if selected and row.key != selected.key), None)
    plan: list[GrowthPlanStep] = []

    if current_action is not None and current_action.execution_phase == "observe":
        plan.append(
            GrowthPlanStep(
                day=1,
                title="先观察当前主动作",
                goal="避免在观察窗里叠加第二个同类动作",
                instruction=current_action.phase_reason or "当前主动作已执行，先盯观察指标。",
                verify=current_action.next_decision or "确认观察窗完成前不追加同类动作。",
                status="active",
                recommendation_id=current_action.recommendation_id,
                source_agent=selected.source_agent if selected else None,
                stop_condition=current_action.rollback_rule,
            )
        )
    elif current_action is not None and current_action.execution_phase == "review":
        plan.append(
            GrowthPlanStep(
                day=1,
                title="先复盘当前主动作",
                goal="根据结果决定放大还是回滚",
                instruction=current_action.phase_reason or "当前动作已经进入复盘阶段。",
                verify=current_action.next_decision or "确认下一步是放大、回滚还是切换策略。",
                status="review",
                recommendation_id=current_action.recommendation_id,
                source_agent=selected.source_agent if selected else None,
            )
        )
    elif selected:
        plan.append(
            GrowthPlanStep(
                day=1,
                title=selected.title,
                goal=focus,
                instruction=f"先推进 {selected.object_name} 的这一条动作，不叠加第二个高风险动作。",
                verify=f"按观察窗检查 {selected.expected_metric} 是否进入正向变化。",
                source_agent=selected.source_agent,
                recommendation_id=selected.recommendation_id,
                stop_condition="指标下降超过 2% 或触发动作回滚规则时立即停止。",
            )
        )
    plan.extend(
        [
            GrowthPlanStep(
                day=2,
                title="保持单变量观察",
                goal="保护实验归因",
                instruction="不改价格、不叠加活动，只记录流量、点击和转化变化。",
                verify=f"确认 {(selected.expected_metric if selected else '核心指标')} 口径稳定。",
                dependency="Day 1 动作已执行",
                stop_condition="数据口径异常时暂停判断并补资料。",
            ),
            GrowthPlanStep(
                day=3,
                title="第一次效果判断",
                goal="决定继续、回滚或等待",
                instruction="正向则保持；负向按回滚规则恢复；变化不足则继续观察。",
                verify="检查 Experiment result、lift 和 attribution quality。",
                dependency="至少完成 24-72 小时观察",
            ),
            GrowthPlanStep(
                day=4,
                title=backup.title if backup else "准备第二顺位动作",
                goal="只准备，不同时执行",
                instruction=(
                    f"准备 {backup.object_name} 的备选方案，但仅在第一动作无效时启用。"
                    if backup
                    else "复核前四个 Agent 是否出现新的高置信度机会。"
                ),
                verify=f"备选机会分 {backup.score:.1f}" if backup else "确认是否出现新机会。",
                source_agent=backup.source_agent if backup else None,
                recommendation_id=backup.recommendation_id if backup else None,
                dependency="Day 3 判断第一动作无效或已完成",
            ),
        GrowthPlanStep(
            day=5,
                title="执行或放弃备选动作",
                goal="避免无效动作堆积",
                instruction="只有第一动作无效且备选证据仍成立时才执行，否则维持有效动作。",
                verify="执行后重新建立独立观察窗。",
                dependency="Day 4 备选方案通过复核",
                stop_condition="第一动作仍在改善时，不切换动作。",
            ),
            GrowthPlanStep(
                day=6,
                title="沉淀本周实验结果",
                goal="形成可复用经验",
                instruction="记录建议、执行、基线、结果和是否有效。",
                verify=f"当前待验证实验 {pending_count} 条。",
            ),
        ]
    )

    plan.append(
        GrowthPlanStep(
            day=7,
            title="形成下周唯一优先级",
            goal="把有效动作变成策略",
            instruction="保留正向动作、回滚负向动作，只把一个最高分机会带到下周。",
            verify="下周计划仍保持一天一条主动作。",
        )
    )
    deduplicated = {step.day: step for step in plan}
    return [deduplicated[day] for day in sorted(deduplicated)[:7]]

def _build_growth_agent(
    ctx: _AgentContext,
    competition: CompetitionAgentResult,
    menu: MenuAgentResult,
    product: ProductAgentResult,
    diagnosis: DiagnosisAgentResult,
    promo: PromoAgentResult | None = None,
    ads: AdsAgentResult | None = None,
    crm: CrmAgentResult | None = None,
    service: ServiceAgentResult | None = None,
    review: ReviewAgentResult | None = None,
    store_matrix: StoreMatrixAgentResult | None = None,
    strategy_memory: StrategyMemorySnapshot | None = None,
) -> GrowthAgentResult:
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    experiment_map = _experiment_map(ctx)
    top_actions = _dedupe_growth_actions([_action_view(rec, item_names) for rec in ctx.recommendations])[:3]
    full_action_queue = _dedupe_workflow_items(sorted(
        [_workflow_item(rec, experiment_map, item_names) for rec in ctx.recommendations],
        key=_workflow_phase_rank,
    ))
    current_action = _current_action(full_action_queue)
    action_queue = full_action_queue[:4]
    hypothesis_reason = ctx.hypothesis.root_cause if ctx.hypothesis else _problem_summary(
        ctx.store_state.primary_problem.type if ctx.store_state.primary_problem else None
    )
    blockers = _document_blockers(ctx)
    readiness = _alignment_readiness(ctx)
    execution_mode = "experiment"
    opportunity_pool = _growth_opportunity_pool(
        ctx,
        competition,
        menu,
        product,
        diagnosis,
        promo=promo,
        ads=ads,
        crm=crm,
        service=service,
        review=review,
        store_matrix=store_matrix,
        strategy_memory=strategy_memory,
    )
    ranked_executable_opportunities = sorted(
        [row for row in opportunity_pool if row.executable],
        key=lambda row: (-(row.score or 0.0), _growth_action_bias(row.action_type)),
    )
    locked_current_opportunity = next(
        (
            row
            for row in opportunity_pool
            if current_action
            and row.recommendation_id == current_action.recommendation_id
            and (
                not _growth_is_discount_action(current_action.action_type)
                or current_action.execution_phase in {"observe", "review"}
            )
        ),
        None,
    )
    selected = (
        locked_current_opportunity
        or (ranked_executable_opportunities[0] if ranked_executable_opportunities else None)
        or (opportunity_pool[0] if opportunity_pool else None)
    )
    action_queue, current_action = _growth_sync_queue_with_selection(ctx, action_queue, selected)
    weekly_plan = _build_growth_plan(ctx, top_actions, current_action, selected, opportunity_pool)
    reason = (
        f"{selected.title} 是当前最高分的可执行机会（{selected.score:.1f}），且最符合经营主问题。"
        if selected
        else hypothesis_reason
    )
    if current_action is not None and current_action.execution_phase == "observe":
        reason = f"{hypothesis_reason} 当前先观察已执行动作，避免连续叠加第二个同类实验。"
    elif current_action is not None and current_action.execution_phase == "review":
        reason = f"{hypothesis_reason} 当前先复盘已有结果，再决定是否继续放大。"
    evidence = [
        ctx.document_alignment.get("summary", ""),
        f"待验证实验 {sum(1 for exp in ctx.experiments if exp.result == 'pending')} 条。",
        *(selected.evidence[:2] if selected else []),
    ]
    if ctx.document_alignment.get("status") in {"conflict", "missing_documents"}:
        execution_mode = "alignment_first"
        reason = "资料还没对齐，先修正事实源，再推进经营动作。"
        weekly_plan = [
            GrowthPlanStep(
                day=1,
                title="统一资料口径",
                goal="让 5 个 agent 说的是同一家店",
                instruction=(ctx.document_alignment.get("recommendations") or ["先补齐原始资料。"])[0],
                verify="对齐状态至少进入 partial，再继续经营动作。",
                stop_condition="对齐状态未达到 partial 时，不得执行经营动作。",
            ),
            GrowthPlanStep(
                day=2,
                title="补齐关键证据",
                goal="补门店、菜单、商圈等关键字段",
                instruction="把截图备注、菜单说明、复盘笔记补进系统。",
                verify="alignment_score 提升，并消除高优先级冲突。",
                dependency="Day 1 已完成事实源检查",
            ),
            GrowthPlanStep(
                day=3,
                title="重新计算机会分",
                goal="用对齐后的事实重排优先级",
                instruction="重新汇总竞争、菜单、商品和诊断 Agent 的候选机会。",
                verify="确认最高分机会具备证据、执行对象与预期指标。",
                dependency="资料状态至少进入 partial",
            ),
            GrowthPlanStep(
                day=4,
                title=selected.title if selected else "执行唯一主动作",
                goal="启动本周单变量实验",
                instruction=(
                    f"资料通过复核后，只推进 {selected.object_name} 这一条动作。"
                    if selected
                    else "只执行重新排序后的第一顺位动作。"
                ),
                verify=f"观察 {selected.expected_metric}" if selected else "建立明确观察指标。",
                source_agent=selected.source_agent if selected else None,
                recommendation_id=selected.recommendation_id if selected else None,
                dependency="Day 3 机会排序完成",
                stop_condition="资料仍有高优先级冲突时继续暂停。",
            ),
            GrowthPlanStep(
                day=5,
                title="保持单变量观察",
                goal="保护实验归因",
                instruction="不叠加第二个动作，记录流量、点击和转化变化。",
                verify="确认数据口径稳定。",
                dependency="Day 4 动作已执行",
            ),
            GrowthPlanStep(
                day=6,
                title="判断继续或回滚",
                goal="让结果决定下一步",
                instruction="正向则保持，负向按回滚规则恢复，证据不足则继续观察。",
                verify="记录 lift、result 与 attribution quality。",
            ),
            GrowthPlanStep(
                day=7,
                title="形成下周唯一优先级",
                goal="把结果沉淀成策略",
                instruction="保留有效动作、回滚负向动作，只带一个机会进入下周。",
                verify="建议、执行、基线和结果均已记录。",
            ),
        ]
        current_action = None
    experiments_summary = {
        "pending": sum(1 for exp in ctx.experiments if exp.result == "pending"),
        "positive": sum(1 for exp in ctx.experiments if exp.result == "positive"),
        "neutral": sum(1 for exp in ctx.experiments if exp.result == "neutral"),
        "negative": sum(1 for exp in ctx.experiments if exp.result == "negative"),
    }
    completed = experiments_summary["positive"] + experiments_summary["neutral"] + experiments_summary["negative"]
    total_experiments = completed + experiments_summary["pending"]
    plan_progress_pct = round(completed / total_experiments * 100) if total_experiments else 0
    if strategy_memory and strategy_memory.positive_patterns:
        learning_summary = f"经验库提示优先复用：{strategy_memory.positive_patterns[0]}"
    elif strategy_memory and strategy_memory.negative_patterns:
        learning_summary = f"经验库提示避免：{strategy_memory.negative_patterns[0]}"
    elif experiments_summary["positive"]:
        learning_summary = f"已有 {experiments_summary['positive']} 条动作验证有效，优先放大同类低风险动作。"
    elif experiments_summary["negative"]:
        learning_summary = f"已有 {experiments_summary['negative']} 条动作效果为负，先回滚并降低同类动作优先级。"
    elif experiments_summary["pending"]:
        learning_summary = f"当前有 {experiments_summary['pending']} 条实验等待观察，暂不叠加新的高风险动作。"
    else:
        learning_summary = "还没有完成实验，请先执行今日唯一主动作建立第一条有效经验。"
    weekly_goal = (
        "提升主推商品点击率"
        if selected and selected.expected_metric == "ctr"
        else "提升下单转化率"
        if selected and selected.expected_metric == "cvr"
        else "稳住订单并改善经营结构"
    )


    growth_narrative = narrate_growth(
        store_name=ctx.store.name,
        selected_title=selected.title if selected else None,
        weekly_goal=weekly_goal,
        experiments_summary=experiments_summary,
        learning_summary=learning_summary,
        do_not_do=[
            "不要在一个观察窗里频繁切换高风险动作。",
            "不要在还没看清 CTR/CVR 之前直接降价。",
            "不要同时执行两个来源不同的 Agent 动作，避免无法归因。",
        ],
        fallback_reason=reason,
    )
    growth_meta = _agent_meta("growth", ctx.generated_at, ctx.hypothesis.confidence if ctx.hypothesis else 0.7)
    if growth_narrative:
        growth_meta.ai_narrative = growth_narrative
        growth_meta.ai_mode = "llm"
    return GrowthAgentResult(
        meta=growth_meta,
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        execution_mode=execution_mode,
        strategy_score=round(selected.score) if selected else 0,
        weekly_goal=weekly_goal,
        today_priority=(
            _growth_today_priority(current_action, top_actions, selected, weekly_plan)
            if execution_mode == "experiment"
            else weekly_plan[0].title
            if weekly_plan
            else None
        ),
        reason=reason,
        evidence=[row for row in list(dict.fromkeys(evidence))[:5] if row],
        opportunity_pool=opportunity_pool,
        selected_opportunity=selected,
        action_queue=action_queue if execution_mode == "experiment" else [],
        current_action=current_action if execution_mode == "experiment" else None,
        experiments_summary=experiments_summary,
        learning_summary=learning_summary,
        plan_progress_pct=plan_progress_pct,
        top_actions=top_actions,
        weekly_plan=weekly_plan,
        do_not_do=[
            "不要在一个观察窗里频繁切换高风险动作。",
            "不要在还没看清 CTR/CVR 之前直接降价。",
            "不要同时执行两个来源不同的 Agent 动作，避免无法归因。",
        ],
    )
