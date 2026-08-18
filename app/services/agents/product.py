from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import MenuItem, MenuItemVersion
from app.models.ohre import Experiment, Recommendation
from app.schemas.agents import (
    AgentWorkflowItem,
    ProductActionCreateResponse,
    ProductAgentResult,
    ProductCandidate,
    ProductHealthDimension,
    ProductRootCause,
    ProductSuggestion,
)
from app.services.action_feedback import find_recent_action_feedback

from .types import _AgentContext, _ItemSnapshot
from .helpers import (
    _agent_meta,
    _dedupe_strings,
    _json_loads_dict,
    _metric_label,
    _normalize_text,
    _recommendation_evidence,
    _recommendation_in_observation,
    _recommendation_title,
)
from .workflow import (
    _current_action,
    _dedupe_workflow_items,
    _experiment_map,
    _workflow_item,
)
from .menu import _alignment_readiness, _document_blockers, _ensure_active_menu

def _product_synthetic_current_action(
    item: _ItemSnapshot | None,
    suggestion: ProductSuggestion,
) -> AgentWorkflowItem:
    item_name = item.name if item else "当前主推商品"
    phase_reason = (
        f"当前先推进 {item_name} 的{suggestion.title}，先用低风险单变量动作验证。"
    )
    return AgentWorkflowItem(
        recommendation_id=f"synthetic:product:{suggestion.action_type}:{_normalize_text(item_name)}",
        title=_recommendation_title(suggestion.action_type),
        action_type=suggestion.action_type,
        object_ref=f"synthetic:item:{item.item_id}" if item else "synthetic:item:focus",
        object_name=item_name,
        status="proposed",
        execution_phase="execute_now",
        phase_reason=phase_reason,
        expected_metric=suggestion.expected_metric,
        window_hours=suggestion.window_hours,
        confidence=0.76 if suggestion.risk_level == "low" else 0.68,
        rollback_rule=suggestion.rollback_rule,
        evidence=[suggestion.detail],
        generated_content={
            **suggestion.generated_content,
            "synthetic": True,
            "source_agent": "product",
            "suggestion_title": suggestion.title,
            "selection_reason": phase_reason,
        },
        next_decision=f"{suggestion.window_hours}h 看 {suggestion.expected_metric} 是否改善，再决定是否切到后备动作。",
    )

def _product_sync_queue_with_suggestions(
    item: _ItemSnapshot | None,
    queue: list[AgentWorkflowItem],
    suggestions: list[ProductSuggestion],
) -> tuple[list[AgentWorkflowItem], AgentWorkflowItem | None]:
    from .growth import _growth_is_discount_action
    deduped_queue = _dedupe_workflow_items(queue)
    current_action = _current_action(deduped_queue)
    top_suggestion = suggestions[0] if suggestions else None
    if top_suggestion is None:
        return deduped_queue, current_action
    if (
        current_action is not None
        and not _growth_is_discount_action(current_action.action_type)
    ):
        return deduped_queue, current_action

    synthetic_current = _product_synthetic_current_action(item, top_suggestion)
    if current_action is None:
        return deduped_queue, synthetic_current

    deferred_reason = (
        f"这条{current_action.title}先保留作后备，但当前先推进 {synthetic_current.object_name} 的{top_suggestion.title}。"
        " 只有低风险商品动作无效时，再考虑启用它。"
    )
    synced_queue: list[AgentWorkflowItem] = []
    for queued in deduped_queue:
        if queued.recommendation_id == current_action.recommendation_id:
            synced_queue.append(
                queued.model_copy(
                    update={
                        "execution_phase": "deferred",
                        "phase_reason": deferred_reason,
                        "next_decision": synthetic_current.next_decision,
                        "generated_content": {
                            **queued.generated_content,
                            "deferred_reason": deferred_reason,
                            "is_backup": True,
                        },
                    }
                )
            )
        else:
            synced_queue.append(queued)
    return synced_queue, synthetic_current

def _bounded_score(value: float) -> int:
    return max(20, min(98, int(round(value))))

def _product_health_dimensions(item: _ItemSnapshot) -> tuple[int, list[ProductHealthDimension]]:
    sales_score = _bounded_score(
        68
        + min(18, max(-18, (item.order_share_pct or 0) - 20) * 0.6)
        + min(12, max(-18, item.orders_delta_pct or 0) * 0.45)
    )
    exposure_score = _bounded_score(72 + min(20, max(-30, item.impressions_delta_pct or 0) * 0.7))
    click_score = _bounded_score(74 + min(20, max(-30, item.ctr_delta_pct or 0) * 0.8))
    conversion_score = _bounded_score(74 + min(20, max(-30, item.cvr_delta_pct or 0) * 0.8))

    def dimension(
        key: str,
        label: str,
        score: int,
        observed: Optional[float],
        baseline: Optional[float],
        delta: Optional[float],
    ) -> ProductHealthDimension:
        status = "strong" if score >= 80 else "watch" if score >= 65 else "weak"
        return ProductHealthDimension(
            key=key,
            label=label,
            score=score,
            observed_value=observed,
            baseline_value=baseline,
            delta_pct=delta,
            status=status,
        )

    dimensions = [
        dimension(
            "sales",
            "销量贡献",
            sales_score,
            item.observe_orders,
            item.baseline_orders,
            item.orders_delta_pct,
        ),
        dimension(
            "exposure",
            "曝光",
            exposure_score,
            item.observe_impressions,
            item.baseline_impressions,
            item.impressions_delta_pct,
        ),
        dimension("ctr", "点击", click_score, item.observe_ctr, item.baseline_ctr, item.ctr_delta_pct),
        dimension("cvr", "转化", conversion_score, item.observe_cvr, item.baseline_cvr, item.cvr_delta_pct),
    ]
    health_score = _bounded_score(
        sales_score * 0.30 + exposure_score * 0.20 + click_score * 0.25 + conversion_score * 0.25
    )
    return health_score, dimensions

def _product_diagnosis(
    item: _ItemSnapshot,
    average_price: Optional[float],
) -> tuple[str, str, str, list[str], list[ProductRootCause]]:
    if item.impressions_delta_pct is not None and item.impressions_delta_pct <= -8:
        stage = "impressions"
        issue = "商品曝光下降"
        diagnosis = "商品首先输在被看见的机会，暂时不是价格或转化问题。"
        decision_path = ["销量变化", "曝光下降", "优先检查排序、流量入口和商品表达完整度"]
        root_causes = [
            ProductRootCause(
                code="traffic_or_ranking",
                stage=stage,
                title="流量入口或排序走弱",
                explanation="曝光先于点击下降，应先恢复商品被看到的机会。",
                confidence=0.82,
                evidence=[f"曝光较基线变化 {item.impressions_delta_pct:.1f}%"],
            )
        ]
    elif item.ctr_delta_pct is not None and item.ctr_delta_pct <= -5:
        stage = "ctr"
        issue = "点击吸引力下降"
        diagnosis = "用户已经看见商品，但主图、标题或第一眼价格感知没有赢下点击。"
        decision_path = ["销量变化", "曝光基本可用", "CTR 下降", "检查主图、标题和价格感知"]
        root_causes = []
        if not item.image_url:
            root_causes.append(
                ProductRootCause(
                    code="missing_image_evidence",
                    stage=stage,
                    title="主图证据缺失或表达不足",
                    explanation="系统没有拿到可验证的商品主图，第一眼竞争力无法被证明。",
                    confidence=0.78,
                    evidence=["商品当前缺少结构化主图地址", f"CTR 变化 {item.ctr_delta_pct:.1f}%"],
                )
            )
        if len(_normalize_text(item.name)) <= 6:
            root_causes.append(
                ProductRootCause(
                    code="generic_title",
                    stage=stage,
                    title="标题卖点不够具体",
                    explanation="标题只有品类名，缺少口味、份量或场景信息，点击理由不充分。",
                    confidence=0.74,
                    evidence=[f"当前标题：{item.name}"],
                )
            )
        if average_price and item.price and item.price >= average_price * 1.12:
            root_causes.append(
                ProductRootCause(
                    code="price_perception",
                    stage=stage,
                    title="第一眼价格感知偏高",
                    explanation="价格高于菜单均价，但标题和主图没有同步证明价值。",
                    confidence=0.69,
                    evidence=[f"商品价 ¥{item.price:.0f}，菜单均价约 ¥{average_price:.0f}"],
                )
            )
        if not root_causes:
            root_causes.append(
                ProductRootCause(
                    code="creative_fatigue",
                    stage=stage,
                    title="第一眼素材竞争力走弱",
                    explanation="曝光没有先下滑而 CTR 明显下降，更符合图文吸引力问题。",
                    confidence=0.71,
                    evidence=[f"CTR 变化 {item.ctr_delta_pct:.1f}%"],
                )
            )
    elif (
        item.cvr_delta_pct is not None
        and item.cvr_delta_pct <= -5
        or item.observe_cvr is not None
        and item.observe_cvr < 0.16
    ):
        stage = "cvr"
        issue = "下单承接偏弱"
        diagnosis = "用户愿意点进来，但价格价值感、套餐结构或信任证据不足。"
        decision_path = ["销量变化", "曝光正常", "CTR 基本正常", "CVR 下降", "检查价格、套餐和评价承接"]
        evidence = [f"当前 CVR {item.observe_cvr * 100:.1f}%"] if item.observe_cvr is not None else []
        if item.cvr_delta_pct is not None:
            evidence.append(f"CVR 较基线变化 {item.cvr_delta_pct:.1f}%")
        root_causes = [
            ProductRootCause(
                code="value_and_bundle",
                stage=stage,
                title="价格价值感与套餐承接不足",
                explanation="点击后没有形成下单，需要先强化份量、搭配和价格锚点，而不是直接全店降价。",
                confidence=0.79,
                evidence=evidence,
            )
        ]
    elif item.orders_delta_pct is not None and item.orders_delta_pct <= -5:
        stage = "orders"
        issue = "销量走弱但漏斗暂未定位"
        diagnosis = "点击与转化没有单点异常，需要继续排查客单、复购、时段和竞争分流。"
        decision_path = ["销量下降", "曝光/CTR/CVR 无显著单点异常", "继续检查客单、复购与竞争"]
        root_causes = [
            ProductRootCause(
                code="demand_or_repurchase",
                stage=stage,
                title="需求或复购变化",
                explanation="当前漏斗证据不足以归因到图、标题或价格，先补时段和复购证据。",
                confidence=0.58,
                evidence=[f"订单较基线变化 {item.orders_delta_pct:.1f}%"],
            )
        ]
    else:
        stage = "stable"
        issue = "商品表现基本稳定"
        diagnosis = "当前没有强异常，适合用单变量低风险实验寻找增量。"
        decision_path = ["销量稳定", "曝光/CTR/CVR 未见强异常", "进入低风险增量实验"]
        root_causes = [
            ProductRootCause(
                code="incremental_opportunity",
                stage=stage,
                title="暂无强根因，存在增量优化空间",
                explanation="不建议同时改多个变量，先做一条可逆实验。",
                confidence=0.61,
                evidence=[item.rationale or "当前商品处于稳定观察位"],
            )
        ]
    return stage, issue, diagnosis, decision_path, root_causes

def _suggested_product_title(item: _ItemSnapshot) -> str:
    name = item.name.strip()
    if any(token in name for token in ("牛肉", "牛腩", "肥牛")) and not any(
        token in name for token in ("厚切", "黑椒", "招牌")
    ):
        return f"黑椒厚切{name}"
    return f"{name}｜现制热卖·分量看得见"

def _product_suggestions(item: _ItemSnapshot, stage: str) -> list[ProductSuggestion]:
    suggestions: list[ProductSuggestion] = []
    if stage in {"impressions", "ctr", "stable"}:
        suggestions.extend(
            [
                ProductSuggestion(
                    type="image",
                    action_type="change_main_image",
                    title="主图优化",
                    detail="放大主菜主体，突出真实份量和热气，背景降噪，不叠加营销贴纸。",
                    priority=1,
                    expected_metric="ctr",
                    expected_lift_pct_low=3,
                    expected_lift_pct_high=10,
                    window_hours=24,
                    rollback_rule="24 小时 CTR 无改善或下降超过 2%，恢复原主图。",
                    generated_content={
                        "visual_brief": f"{item.name} 使用 45° 近景，主菜占画面 70%，突出肉量、酱汁和热气。",
                        "negative_constraints": ["不拼图", "不堆字", "不使用虚假份量"],
                    },
                ),
                ProductSuggestion(
                    type="title",
                    action_type="change_title",
                    title="标题重写",
                    detail="把口味、份量或场景卖点写进标题，避免只有品类名。",
                    priority=2,
                    expected_metric="ctr",
                    expected_lift_pct_low=2,
                    expected_lift_pct_high=8,
                    window_hours=24,
                    rollback_rule="24 小时 CTR 无改善，恢复原标题。",
                    generated_content={
                        "original_title": item.name,
                        "suggested_title": _suggested_product_title(item),
                    },
                ),
            ]
        )
    if stage in {"cvr", "orders"}:
        bundle_price = round(float(item.price or 30) + 6, 0)
        suggestions.extend(
            [
                ProductSuggestion(
                    type="bundle",
                    action_type="add_set_meal",
                    title="补低决策套餐",
                    detail="用主商品加饮品/小食形成清晰价格锚点，优先承接犹豫用户。",
                    priority=1,
                    expected_metric="cvr",
                    expected_lift_pct_low=2,
                    expected_lift_pct_high=9,
                    window_hours=72,
                    risk_level="medium",
                    rollback_rule="72 小时套餐 CVR 或连带单无改善，撤回套餐入口。",
                    generated_content={
                        "bundle_name": f"{item.name}+饮品套餐",
                        "suggested_price": bundle_price,
                        "bundle_logic": "主商品 + 低成本饮品，套餐价比单点合计低约 5%-8%。",
                    },
                ),
                ProductSuggestion(
                    type="price",
                    action_type="adjust_price_value",
                    title="价格价值感校准",
                    detail="先补份量、原料和套餐锚点表达，不直接降低商品基础价。",
                    priority=2,
                    expected_metric="cvr",
                    expected_lift_pct_low=1,
                    expected_lift_pct_high=6,
                    window_hours=72,
                    risk_level="medium",
                    rollback_rule="72 小时 CVR 无改善，撤回价格锚点表达。",
                    generated_content={
                        "current_price": item.price,
                        "value_points": ["真实份量", "现制口感", "套餐比单点更划算"],
                    },
                ),
            ]
        )
    return suggestions[:3]

def _rank_product_suggestions(
    item: _ItemSnapshot | None,
    suggestions: list[ProductSuggestion],
    recommendations: list[Recommendation],
    experiments: list[Experiment],
) -> list[ProductSuggestion]:
    if item is None or not suggestions:
        return suggestions

    ranked: list[tuple[float, int, ProductSuggestion]] = []
    total = len(suggestions)
    object_ref = f"item:{item.item_id}"
    for index, suggestion in enumerate(suggestions):
        action_type = suggestion.action_type or suggestion.type
        feedback = find_recent_action_feedback(
            recommendations,
            experiments,
            action_type=action_type,
            object_ref=object_ref,
        )
        generated_content = dict(suggestion.generated_content)
        if feedback is not None:
            generated_content.update(
                {
                    "feedback_result": feedback.result,
                    "feedback_note": feedback.note,
                    "feedback_lift_pct": feedback.lift_pct,
                }
            )
        ranked.append(
            (
                (total - index) + (feedback.score_delta if feedback is not None else 0.0),
                index,
                suggestion.model_copy(update={"generated_content": generated_content}),
            )
        )
    return [row[2] for row in sorted(ranked, key=lambda row: (-row[0], row[1]))]

def _product_candidates(ctx: _AgentContext) -> list[ProductCandidate]:
    average_price_values = [float(row.price) for row in ctx.item_snapshots if row.price is not None]
    average_price = sum(average_price_values) / len(average_price_values) if average_price_values else None
    candidates: list[ProductCandidate] = []
    for item in ctx.item_snapshots:
        health_score, _ = _product_health_dimensions(item)
        stage, issue, _, _, _ = _product_diagnosis(item, average_price)
        suggestions = _rank_product_suggestions(
            item,
            _product_suggestions(item, stage),
            ctx.recommendations,
            ctx.experiments,
        )
        importance = min(20, max(0, (item.order_share_pct or 0) * 0.35))
        opportunity_score = _bounded_score((100 - health_score) * 0.78 + importance + 25)
        candidates.append(
            ProductCandidate(
                item_id=item.item_id,
                name=item.name,
                role=item.role,
                health_score=health_score,
                opportunity_score=opportunity_score,
                diagnosis_stage=stage,
                issue=issue,
                recommended_action=suggestions[0].title if suggestions else "继续观察",
                order_share_pct=item.order_share_pct,
                ctr_delta_pct=item.ctr_delta_pct,
                cvr_delta_pct=item.cvr_delta_pct,
            )
        )
    candidates.sort(key=lambda row: (row.opportunity_score, row.order_share_pct or 0), reverse=True)
    return candidates[:6]

def _focus_item(ctx: _AgentContext, focus_item_id: str | None = None) -> _ItemSnapshot | None:
    if focus_item_id:
        return next((row for row in ctx.item_snapshots if row.item_id == focus_item_id), None)
    candidates = _product_candidates(ctx)
    if candidates:
        candidate_id = candidates[0].item_id
        return next((row for row in ctx.item_snapshots if row.item_id == candidate_id), None)
    return ctx.item_snapshots[0] if ctx.item_snapshots else None

def _build_product_agent(ctx: _AgentContext, focus_item_id: str | None = None) -> ProductAgentResult:
    item = _focus_item(ctx, focus_item_id=focus_item_id)
    experiment_map = _experiment_map(ctx)
    item_names = {row["item_id"]: row["name"] for row in ctx.menu_items}
    stage = "unknown"
    issue = "主推商品需要先建立足够证据。"
    diagnosis = "先从一个低风险动作开始验证。"
    health_score = 0
    health_dimensions: list[ProductHealthDimension] = []
    decision_path: list[str] = []
    root_causes: list[ProductRootCause] = []
    average_price_values = [float(row.price) for row in ctx.item_snapshots if row.price is not None]
    average_price = sum(average_price_values) / len(average_price_values) if average_price_values else None
    if item:
        health_score, health_dimensions = _product_health_dimensions(item)
        stage, issue, diagnosis, decision_path, root_causes = _product_diagnosis(item, average_price)
    recommendations: list[ProductSuggestion] = []
    if item:
        recommendations = _rank_product_suggestions(
            item,
            _product_suggestions(item, stage),
            ctx.recommendations,
            ctx.experiments,
        )

    related_actions = _dedupe_strings([
        _recommendation_title(rec.action_type)
        for rec in ctx.recommendations
        if not item or rec.object_ref.endswith(item.item_id) or rec.object_ref.startswith("store:")
    ])[:3]
    action_queue = [
        _workflow_item(rec, experiment_map, item_names)
        for rec in ctx.recommendations
        if not item or rec.object_ref.endswith(item.item_id) or rec.object_ref.startswith("store:")
    ][:3]
    action_queue, current_action = _product_sync_queue_with_suggestions(item, action_queue, recommendations)
    blockers = _document_blockers(ctx)
    readiness = _alignment_readiness(ctx)
    if not item:
        blockers.append("当前还没有明确主推商品，商品优化无法精准落点。")
        readiness = "blocked"
    why_now = None
    if item:
        weakest = min(health_dimensions, key=lambda row: row.score) if health_dimensions else None
        why_now = (
            f"{item.name} 健康度 {health_score} 分，当前最弱环节是{weakest.label}（{weakest.score} 分）。"
            if weakest
            else f"{item.name} 已进入商品优化优先队列。"
        )
    evidence = []
    if item:
        evidence.extend(
            [
                f"主推商品：{item.name}，订单占比 {item.order_share_pct:.1f}%。" if item.order_share_pct is not None else f"主推商品：{item.name}。",
                f"CTR 变化 {item.ctr_delta_pct:.1f}%。" if item.ctr_delta_pct is not None else "CTR 变化证据不足。",
                item.rationale,
            ]
        )
    for rec in ctx.recommendations[:2]:
        evidence.extend(_recommendation_evidence(rec))

    return ProductAgentResult(
        meta=_agent_meta("product", ctx.generated_at, ctx.hypothesis.confidence if ctx.hypothesis else 0.7),
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        focus_item_id=item.item_id if item else None,
        focus_item_name=item.name if item else "当前主推商品",
        health_score=health_score,
        health_dimensions=health_dimensions,
        diagnosis_stage=stage,
        issue=issue,
        diagnosis=diagnosis,
        why_now=why_now,
        metrics={
            "order_share_pct": item.order_share_pct if item else None,
            "orders": item.observe_orders if item else None,
            "orders_delta_pct": item.orders_delta_pct if item else None,
            "impressions": item.observe_impressions if item else None,
            "impressions_delta_pct": item.impressions_delta_pct if item else None,
            "ctr": item.observe_ctr if item else None,
            "ctr_delta_pct": item.ctr_delta_pct if item else None,
            "cvr": item.observe_cvr if item else None,
            "cvr_delta_pct": item.cvr_delta_pct if item else None,
            "price": item.price if item else None,
        },
        root_causes=root_causes,
        decision_path=decision_path,
        item_candidates=_product_candidates(ctx),
        evidence=list(dict.fromkeys(evidence))[:5],
        recommendations=recommendations,
        related_actions=related_actions,
        experiment_guardrail="一次只改一个变量；CTR 动作观察 24 小时，CVR/套餐动作观察 72 小时，再决定保留或回滚。",
        action_queue=action_queue,
        current_action=current_action,
    )

def create_product_action(
    db: Session,
    store_id: str,
    suggestion_index: int,
    days: int = 7,
    item_id: str | None = None,
) -> ProductActionCreateResponse | None:
    from .context import _build_context, _invalidate_context_cache
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None
    product = _build_product_agent(ctx, focus_item_id=item_id)
    if product.focus_item_id is None:
        raise ValueError("product focus item not found")
    if suggestion_index < 0 or suggestion_index >= len(product.recommendations):
        raise IndexError("product suggestion not found")

    suggestion = product.recommendations[suggestion_index]
    action_type = suggestion.action_type or suggestion.type
    object_ref = f"item:{product.focus_item_id}"
    metric_label = _metric_label(suggestion.expected_metric or ("cvr" if suggestion.type in {"bundle", "price"} else "ctr"))
    review_note = f"这次先围绕{metric_label}做单变量验证，观察窗结束后再决定放大还是回退。"
    observe_focus = [
        f"观察 {product.focus_item_name} 的{metric_label}是否进入正向变化。",
        "观察窗内不要叠加第二个同类商品动作。",
    ]
    next_decision = observe_focus[0]
    duplicate_candidates = db.execute(
        select(Recommendation)
        .where(
            Recommendation.store_id == store_id,
            Recommendation.object_ref == object_ref,
            Recommendation.action_type == action_type,
            Recommendation.status.in_(("proposed", "adopted", "executed")),
        )
        .order_by(Recommendation.created_at.desc())
    ).scalars().all()
    duplicate = None
    duplicate_experiment = None
    for candidate in duplicate_candidates:
        candidate_experiment = db.execute(
            select(Experiment)
            .where(Experiment.recommendation_id == candidate.id)
            .order_by(Experiment.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        duplicate_in_observation, _ = _recommendation_in_observation(candidate, candidate_experiment, ctx.generated_at)
        duplicate_is_active = candidate.status in {"proposed", "adopted"} or duplicate_in_observation
        if duplicate_is_active:
            duplicate = candidate
            duplicate_experiment = candidate_experiment
            break
    if duplicate is not None:
        duplicate_payload = _json_loads_dict(duplicate.content_json)
        duplicate_payload.update(
            {
                "source": "product_agent",
                "product_suggestion": suggestion.model_dump(mode="json"),
                "product_health_score": product.health_score,
                "diagnosis_stage": product.diagnosis_stage,
                "root_causes": [row.model_dump(mode="json") for row in product.root_causes],
                "review_note": review_note,
                "observe_focus": observe_focus,
                "next_decision": next_decision,
            }
        )
        duplicate.content_json = json.dumps(duplicate_payload, ensure_ascii=False)
        db.add(duplicate)
        db.commit()
        _invalidate_context_cache(store_id)
        db.refresh(duplicate)
        return ProductActionCreateResponse(
            store_id=store_id,
            item_id=product.focus_item_id,
            item_name=product.focus_item_name,
            suggestion_index=suggestion_index,
            recommendation_id=duplicate.id,
            experiment_id=duplicate_experiment.id if duplicate_experiment else None,
            status=duplicate.status,
            message=f"{product.focus_item_name} 已有同类动作，已返回现有任务，避免重复实验。",
            review_note=review_note,
            observe_focus=observe_focus,
            next_decision=next_decision,
            suggestion=suggestion,
        )

    confidence_values = [row.confidence for row in product.root_causes]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.65
    evidence = [
        product.why_now or product.diagnosis,
        *[evidence for cause in product.root_causes for evidence in cause.evidence[:2]],
    ]
    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        scope="item",
        object_ref=object_ref,
        action_type=action_type,
        expected_metric=suggestion.expected_metric or ("cvr" if suggestion.type in {"bundle", "price"} else "ctr"),
        expected_lift_pct_low=suggestion.expected_lift_pct_low,
        expected_lift_pct_high=suggestion.expected_lift_pct_high,
        window_hours=suggestion.window_hours,
        rollback_rule=suggestion.rollback_rule,
        confidence=round(confidence, 2),
        evidence_json=json.dumps(list(dict.fromkeys(evidence))[:5], ensure_ascii=False),
        content_json=json.dumps(
            {
                "source": "product_agent",
                "product_suggestion": suggestion.model_dump(mode="json"),
                "product_health_score": product.health_score,
                "diagnosis_stage": product.diagnosis_stage,
                "root_causes": [row.model_dump(mode="json") for row in product.root_causes],
                "review_note": review_note,
                "observe_focus": observe_focus,
                "next_decision": next_decision,
                "feedback_history": [
                    {
                        "status": "proposed",
                        "at": datetime.now(timezone.utc).isoformat(),
                        "message": "商品 Agent 已生成可执行动作",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        status="proposed",
    )
    db.add(recommendation)
    db.commit()
    _invalidate_context_cache(store_id)
    db.refresh(recommendation)
    return ProductActionCreateResponse(
        store_id=store_id,
        item_id=product.focus_item_id,
        item_name=product.focus_item_name,
        suggestion_index=suggestion_index,
        recommendation_id=recommendation.id,
        experiment_id=None,
        status=recommendation.status,
        message=f"已为 {product.focus_item_name} 生成「{suggestion.title}」动作，等待商家采纳。",
        review_note=review_note,
        observe_focus=observe_focus,
        next_decision=next_decision,
        suggestion=suggestion,
    )

def apply_product_action(
    db: Session,
    store_id: str,
    suggestion_index: int,
    days: int = 7,
    item_id: str | None = None,
) -> ProductActionCreateResponse | None:
    """执行商品优化动作——在系统内真正修改 MenuItemVersion。

    支持：
    - change_title：重写商品标题（写新 MenuItemVersion）
    - change_main_image：写入优化主图（系统内 Version；平台同步另需授权）
    - add_set_meal：创建套餐商品（新建 MenuItem + Version）
    - adjust_price_value：调整价格（写新 Version 改 price）

    和 menu agent 的 apply 一样，执行后自动建 Recommendation(executed) + Experiment(pending)。
    """
    from .context import _build_context, _invalidate_context_cache
    ctx = _build_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None
    product = _build_product_agent(ctx, focus_item_id=item_id)
    if product.focus_item_id is None:
        raise ValueError("product focus item not found")
    if suggestion_index < 0 or suggestion_index >= len(product.recommendations):
        raise IndexError("product suggestion not found")

    suggestion = product.recommendations[suggestion_index]
    action_type = suggestion.action_type or suggestion.type
    now = datetime.now(timezone.utc)
    focus_item = next((it for it in ctx.store.items if it.id == product.focus_item_id), None)

    # 根据 action_type 执行不同的系统内修改
    new_item_id = product.focus_item_id
    new_item_name = product.focus_item_name

    if action_type == "add_set_meal":
        # 套餐：新建 MenuItem + Version（类似 menu bundle）
        menu = _ensure_active_menu(db=db, store_id=store_id)
        new_item = MenuItem(store_id=store_id, menu_id=menu.id, is_active=True)
        db.add(new_item)
        db.flush()
        bundle_name = suggestion.generated_content.get("bundle_name") or f"{product.focus_item_name} 套餐"
        price = suggestion.generated_content.get("suggested_price")
        version = MenuItemVersion(
            item_id=new_item.id,
            name=bundle_name,
            category="套餐",
            price=price,
            description=suggestion.detail,
            source="product_agent_set_meal",
        )
        db.add(version)
        db.flush()
        new_item.current_version_id = version.id
        db.add(new_item)
        new_item_id = new_item.id
        new_item_name = bundle_name
        _invalidate_context_cache(store_id)

    elif action_type == "change_title" and focus_item is not None:
        # 改标题：新建一个 Version（保留旧版本做回滚）
        current = focus_item.current_version
        new_title = (
            suggestion.generated_content.get("suggested_title")
            or suggestion.generated_content.get("title_candidate")
            or suggestion.title
        )
        version = MenuItemVersion(
            item_id=focus_item.id,
            name=new_title,
            category=current.category if current else None,
            price=current.price if current else None,
            description=current.description if current else None,
            image_url=current.image_url if current else None,
            source="product_agent_title",
        )
        db.add(version)
        db.flush()
        focus_item.current_version_id = version.id
        db.add(focus_item)
        new_item_name = new_title
        _invalidate_context_cache(store_id)

    elif action_type == "change_main_image" and focus_item is not None:
        current = focus_item.current_version
        image_url = (
            suggestion.generated_content.get("image_url")
            or suggestion.generated_content.get("optimized_image_url")
            or f"mealkey://optimized-main-image/{focus_item.id}"
        )
        version = MenuItemVersion(
            item_id=focus_item.id,
            name=current.name if current else product.focus_item_name,
            category=current.category if current else None,
            price=current.price if current else None,
            description=suggestion.generated_content.get("visual_brief")
            or (current.description if current else suggestion.detail),
            image_url=image_url,
            source="product_agent_main_image",
        )
        db.add(version)
        db.flush()
        focus_item.current_version_id = version.id
        db.add(focus_item)
        _invalidate_context_cache(store_id)

    elif action_type == "adjust_price_value" and focus_item is not None:
        # 调价：新建 Version 改 price
        current = focus_item.current_version
        new_price = suggestion.generated_content.get("suggested_price")
        if new_price is None and current and current.price:
            # 如果没给明确价格，按 suggestion 的方向微调（V1 简化）
            new_price = current.price
        version = MenuItemVersion(
            item_id=focus_item.id,
            name=current.name if current else product.focus_item_name,
            category=current.category if current else None,
            price=new_price,
            description=current.description if current else None,
            image_url=current.image_url if current else None,
            source="product_agent_price",
        )
        db.add(version)
        db.flush()
        focus_item.current_version_id = version.id
        db.add(focus_item)
        _invalidate_context_cache(store_id)

    # 写 Recommendation（executed）+ Experiment（pending）
    object_ref = f"item:{new_item_id}"
    expected_metric = suggestion.expected_metric or ("cvr" if suggestion.type in {"bundle", "price"} else "ctr")
    confidence = round(sum(r.confidence for r in product.root_causes) / len(product.root_causes), 2) if product.root_causes else 0.65
    evidence = [
        product.why_now or product.diagnosis,
        *[ev for cause in product.root_causes for ev in cause.evidence[:2]],
    ]
    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=ctx.hypothesis.id if ctx.hypothesis else None,
        scope="item",
        object_ref=object_ref,
        action_type=action_type,
        expected_metric=expected_metric,
        expected_lift_pct_low=suggestion.expected_lift_pct_low,
        expected_lift_pct_high=suggestion.expected_lift_pct_high,
        window_hours=suggestion.window_hours,
        rollback_rule=suggestion.rollback_rule,
        confidence=confidence,
        evidence_json=json.dumps(list(dict.fromkeys(evidence))[:5], ensure_ascii=False),
        content_json=json.dumps(
            {
                "product_suggestion": suggestion.model_dump(mode="json"),
                "product_health_score": product.health_score,
                "diagnosis_stage": product.diagnosis_stage,
                "executed_in_system": True,
                "new_item_name": new_item_name,
                "feedback_history": [
                    {"status": "executed", "at": now.isoformat(), "message": f"商品 Agent 已在系统内执行{new_item_name}的{action_type}"}
                ],
            },
            ensure_ascii=False,
        ),
        status="adopted",
        adopted_at=now,
    )
    db.add(recommendation)
    db.flush()
    from app.services.action_pipeline import commit_recommendation_executed

    commit_recommendation_executed(
        recommendation,
        now=now,
        actor="product_agent",
        domain={"applied": True, "mode": "in_system", "action": action_type},
    )

    from app.services.thread_engine import ensure_thread_for_action
    thread = ensure_thread_for_action(db, store_id, f"商品优化：{action_type}")
    recommendation.work_thread_id = thread.id
    db.flush()

    metric = ctx.store_state.kpis.get(expected_metric)
    experiment = Experiment(
        recommendation_id=recommendation.id,
        store_id=store_id,
        work_thread_id=thread.id,
        item_id=new_item_id,
        baseline_value=metric.observed_value if metric else None,
        observed_value=None,
        lift_pct=None,
        baseline_from=ctx.store_state.window.from_day,
        baseline_to=ctx.store_state.window.to_day,
        observe_from=None,
        observe_to=None,
        control_desc=f"商品{action_type}后观察{expected_metric}变化",
        attribution_quality="high",
        result="pending",
        notes=f"{new_item_name}已执行{action_type}，等待观察窗。",
    )
    db.add(experiment)
    db.commit()
    _invalidate_context_cache(store_id)
    db.refresh(recommendation)
    db.refresh(experiment)

    observe_focus = [f"看 {new_item_name} 的 {expected_metric}", f"{suggestion.window_hours}h 后判断是否有效"]
    return ProductActionCreateResponse(
        store_id=store_id,
        item_id=new_item_id,
        item_name=new_item_name,
        suggestion_index=suggestion_index,
        recommendation_id=recommendation.id,
        experiment_id=experiment.id,
        status="executed",
        message=f"已在系统内执行{new_item_name}的{action_type}，并写入 recommendation/experiment 审计。",
        observe_focus=observe_focus,
        next_decision=observe_focus[0],
        suggestion=suggestion,
    )
