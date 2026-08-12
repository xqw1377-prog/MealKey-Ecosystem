"""
门店线上装修诊断（外卖店页第一眼 → 销售转化）

独立 Agent：评估头图/主图、招牌展示、分类信息架构、套餐表面、评分区，
并把优先改造动作落到 Recommendation（可采纳执行）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ReviewFact, ReviewNLP, Store
from app.models.ohre import Experiment, Recommendation
from app.schemas.agents import (
    AgentMeta,
    AgentWorkflowItem,
    StorefrontActionCreateResponse,
    StorefrontAgentResult,
    StorefrontDimension,
    StorefrontIssue,
    StorefrontPriorityAction,
    StorefrontSalesImpact,
)
from app.services.action_feedback import find_recent_action_feedback


@dataclass
class StorefrontInput:
    store: Store
    menu_items: list[dict[str, Any]]
    item_snapshots: list[Any]
    competition_changes: list[Any]
    kpis: dict[str, Any]
    document_alignment: dict[str, Any]
    primary_problem_type: Optional[str]
    hypothesis_id: Optional[str]
    generated_at: datetime


def _clamp(score: float, low: int = 20, high: int = 98) -> int:
    return int(max(low, min(high, round(score))))


def _kpi_delta(kpis: dict[str, Any], key: str) -> Optional[float]:
    row = kpis.get(key)
    if row is None:
        return None
    return getattr(row, "delta_pct", None) if not isinstance(row, dict) else row.get("delta_pct")


def _alignment_readiness(document_alignment: dict[str, Any]) -> str:
    status = document_alignment.get("status") or "partial"
    if status in {"aligned", "partial", "conflict", "missing_documents"}:
        return "ready" if status == "aligned" else "partial" if status == "partial" else "limited"
    return "partial"


def build_storefront_diagnosis(db: Session, data: StorefrontInput) -> StorefrontAgentResult:
    items = data.menu_items
    snapshots = data.item_snapshots
    total = max(len(items), 1)
    with_image = sum(1 for row in items if row.get("image_url"))
    image_coverage = with_image / total

    categories = {}
    for row in items:
        cat = (row.get("category") or "未分类").strip() or "未分类"
        categories.setdefault(cat, 0)
        categories[cat] += 1
    category_count = len(categories)
    uncategorized = categories.get("未分类", 0)

    set_meal_count = sum(
        1
        for row in items
        if any(token in (row.get("name") or "") for token in ("套餐", "组合", "双人", "单人餐"))
    )
    signature_candidates = sorted(
        snapshots,
        key=lambda row: (row.observe_orders or 0, row.observe_gmv or 0),
        reverse=True,
    )
    top_signature = signature_candidates[0] if signature_candidates else None
    missing_top_image = bool(top_signature and not getattr(top_signature, "image_url", None))

    ctr_delta = _kpi_delta(data.kpis, "ctr")
    cvr_delta = _kpi_delta(data.kpis, "cvr")
    image_changed = [c for c in data.competition_changes if getattr(c, "type", None) == "image_changed"]
    rating_up = [c for c in data.competition_changes if getattr(c, "type", None) == "rating_up"]

    review_rows = db.execute(
        select(ReviewFact, ReviewNLP)
        .outerjoin(ReviewNLP, ReviewNLP.review_id == ReviewFact.id)
        .where(ReviewFact.store_id == data.store.id)
        .order_by(ReviewFact.reviewed_at.desc())
        .limit(40)
    ).all()
    package_hits = 0
    appearance_hits = 0
    rating_sum = 0.0
    rating_n = 0
    for review, nlp in review_rows:
        if review.rating is not None:
            rating_sum += float(review.rating)
            rating_n += 1
        text = (review.content or "").lower()
        package_score = getattr(nlp, "package", None) if nlp else None
        if package_score is not None and package_score < 0.4:
            package_hits += 1
        if any(token in text for token in ("图", "照片", "和实物", "不像", "色差", "包装丑", "难看")):
            appearance_hits += 1
    avg_rating = (rating_sum / rating_n) if rating_n else None

    # ---- 五维打分（代理存在时打分；无数据也能给有限分）----
    hero_score = 55 + image_coverage * 35
    if missing_top_image:
        hero_score -= 18
    if ctr_delta is not None and ctr_delta < -8:
        hero_score -= min(20, abs(ctr_delta) * 0.7)
    if image_changed:
        hero_score -= 8
    if appearance_hits >= 2:
        hero_score -= 10

    signature_score = 70
    if top_signature is None:
        signature_score = 40
    else:
        if missing_top_image:
            signature_score -= 22
        if (top_signature.observe_ctr or 0) and top_signature.baseline_ctr:
            if (top_signature.ctr_delta_pct or 0) < -10:
                signature_score -= 15
        if not any(token in (top_signature.name or "") for token in ("招牌", "必点", "人气", "爆款")):
            # 名称未必含招牌词，轻微扣分
            signature_score -= 4

    category_score = 78
    if category_count <= 1:
        category_score -= 18
    elif category_count > 10:
        category_score -= 12
    if uncategorized / total > 0.35:
        category_score -= 16
    if total >= 18 and category_count < 3:
        category_score -= 10

    set_meal_score = 62 + min(28, set_meal_count * 8)
    if set_meal_count == 0:
        set_meal_score = 42
    if cvr_delta is not None and cvr_delta < -8 and set_meal_count == 0:
        set_meal_score -= 12

    rating_score = 68
    if avg_rating is not None:
        rating_score = 40 + avg_rating * 12
    if package_hits >= 2:
        rating_score -= 12
    if rating_up:
        rating_score -= 8
    if appearance_hits >= 2:
        rating_score -= 10

    dimensions = [
        StorefrontDimension(
            key="hero_image",
            label="头图 / 主推主图",
            score=_clamp(hero_score),
            status="weak" if hero_score < 60 else "watch" if hero_score < 75 else "strong",
            summary=f"菜单图覆盖率 {image_coverage:.0%}，主推{'缺主图' if missing_top_image else '有主图'}。",
            evidence=[
                f"{with_image}/{len(items)} 个商品有主图",
                f"店铺 CTR 变化 {ctr_delta:+.1f}%" if ctr_delta is not None else "CTR 数据不足",
                f"竞品近期换图 {len(image_changed)} 次" if image_changed else "竞品暂无换图信号",
            ],
            sales_lever="ctr",
        ),
        StorefrontDimension(
            key="signature_display",
            label="招牌 / 主推展示",
            score=_clamp(signature_score),
            status="weak" if signature_score < 60 else "watch" if signature_score < 75 else "strong",
            summary=(
                f"当前主推候选：{top_signature.name}"
                if top_signature
                else "尚未形成清晰招牌展示。"
            ),
            evidence=[
                f"主推订单占比观察值：{getattr(top_signature, 'order_share_pct', None) or '--'}",
                "主推缺主图会直接损失第一眼点击" if missing_top_image else "主推具备基础图片",
            ],
            sales_lever="ctr",
        ),
        StorefrontDimension(
            key="category_ia",
            label="分类信息架构",
            score=_clamp(category_score),
            status="weak" if category_score < 60 else "watch" if category_score < 75 else "strong",
            summary=f"{category_count} 个分类，未分类 {uncategorized} 个。",
            evidence=[
                f"分类数 {category_count}",
                f"未分类占比 {uncategorized / total:.0%}",
                "分类过多或过少都会抬高阅读成本",
            ],
            sales_lever="cvr",
        ),
        StorefrontDimension(
            key="set_meal_surface",
            label="套餐展示面",
            score=_clamp(set_meal_score),
            status="weak" if set_meal_score < 60 else "watch" if set_meal_score < 75 else "strong",
            summary=f"当前识别套餐 {set_meal_count} 个。",
            evidence=[
                f"套餐商品数 {set_meal_count}",
                f"店铺 CVR 变化 {cvr_delta:+.1f}%" if cvr_delta is not None else "CVR 数据不足",
            ],
            sales_lever="cvr",
        ),
        StorefrontDimension(
            key="rating_zone",
            label="评分与信任区",
            score=_clamp(rating_score),
            status="weak" if rating_score < 60 else "watch" if rating_score < 75 else "strong",
            summary=(
                f"近评均分 {avg_rating:.2f}" if avg_rating is not None else "评分样本不足，先按代理信号判断。"
            ),
            evidence=[
                f"评价样本 {rating_n} 条",
                f"包装/外观负向提及 {package_hits + appearance_hits} 次",
                f"竞品评分上升信号 {len(rating_up)} 条" if rating_up else "竞品评分暂无上升",
            ],
            sales_lever="cvr",
        ),
    ]

    weights = {
        "hero_image": 0.30,
        "signature_display": 0.22,
        "category_ia": 0.14,
        "set_meal_surface": 0.16,
        "rating_zone": 0.18,
    }
    health = sum(dim.score * weights[dim.key] for dim in dimensions)
    # 第一眼问题对销售权重更高
    if data.primary_problem_type == "store_ctr_down":
        health = health * 0.92
    health_score = _clamp(health)

    issues: list[StorefrontIssue] = []
    if image_coverage < 0.7 or missing_top_image or (ctr_delta is not None and ctr_delta < -8):
        issues.append(
            StorefrontIssue(
                code="weak_hero_visual",
                severity="high" if (missing_top_image or (ctr_delta or 0) < -12) else "medium",
                title="第一眼主图竞争力不足",
                detail="头图/主推主图覆盖或质量代理偏弱，会直接损失曝光后的进店点击。",
                evidence=[d.summary for d in dimensions if d.key in {"hero_image", "signature_display"}],
                sales_impact_est="预计影响 CTR 8%-18%，是线上装修对销售最敏感的杠杆之一。",
                suggested_action_type="refresh_hero_image",
                dimension_key="hero_image",
            )
        )
    if category_count <= 1 or uncategorized / total > 0.35 or category_count > 10:
        issues.append(
            StorefrontIssue(
                code="category_friction",
                severity="medium",
                title="分类信息架构增加决策成本",
                detail="分类过少、过多或未分类过多，会让用户在店页停留更久却更难下单。",
                evidence=[dimensions[2].summary],
                sales_impact_est="预计影响 CVR 4%-10%，尤其在菜单较长时。",
                suggested_action_type="optimize_category_ia",
                dimension_key="category_ia",
            )
        )
    if set_meal_count == 0 or (cvr_delta is not None and cvr_delta < -8 and set_meal_count < 2):
        issues.append(
            StorefrontIssue(
                code="weak_set_meal_surface",
                severity="high" if set_meal_count == 0 else "medium",
                title="套餐展示面不足",
                detail="店页缺少低决策成本套餐入口，转化承接偏弱。",
                evidence=[dimensions[3].summary],
                sales_impact_est="预计影响 CVR 6%-14%，并抬升客单价。",
                suggested_action_type="surface_set_meal",
                dimension_key="set_meal_surface",
            )
        )
    if (avg_rating is not None and avg_rating < 4.5) or package_hits + appearance_hits >= 2 or rating_up:
        issues.append(
            StorefrontIssue(
                code="trust_zone_pressure",
                severity="medium",
                title="评分区信任感承压",
                detail="评分或包装/图实相关负向反馈上升，或竞品口碑在回升，会削弱下单信心。",
                evidence=[dimensions[4].summary],
                sales_impact_est="预计影响 CVR 3%-9%，并拖累复购。",
                suggested_action_type="reinforce_rating_zone",
                dimension_key="rating_zone",
            )
        )
    if top_signature and (top_signature.ctr_delta_pct or 0) < -10:
        issues.append(
            StorefrontIssue(
                code="signature_ctr_slide",
                severity="high",
                title="招牌款点击下滑",
                detail=f"{top_signature.name} 的 CTR 下滑，招牌位展示需要立刻重做。",
                evidence=[f"CTR 变化 {top_signature.ctr_delta_pct:+.1f}%"],
                sales_impact_est="招牌款 CTR 修复通常能拉动整店订单 5%-12%。",
                suggested_action_type="refresh_signature_card",
                dimension_key="signature_display",
                object_ref=f"item:{top_signature.item_id}",
                object_name=top_signature.name,
            )
        )

    issues.sort(key=lambda row: {"high": 0, "medium": 1, "low": 2}.get(row.severity, 3))

    # 销售影响预估
    primary_metric = "ctr"
    lift_low, lift_high = 6.0, 14.0
    if any(i.code in {"weak_set_meal_surface", "category_friction", "trust_zone_pressure"} for i in issues) and (
        data.primary_problem_type == "store_cvr_down" or (cvr_delta is not None and cvr_delta < -5)
    ):
        primary_metric = "cvr"
        lift_low, lift_high = 5.0, 12.0
    if health_score >= 80:
        lift_low, lift_high = 2.0, 6.0
    elif health_score < 55:
        lift_low, lift_high = max(lift_low, 8.0), max(lift_high, 18.0)

    sales_impact = StorefrontSalesImpact(
        primary_metric=primary_metric,
        lift_pct_low=lift_low,
        lift_pct_high=lift_high,
        narrative=(
            f"线上装修健康分 {health_score}。优先修{'第一眼主图/招牌' if primary_metric == 'ctr' else '套餐与信任承接'}，"
            f"预计 {primary_metric.upper()} 可提升 {lift_low:.0f}%-{lift_high:.0f}%，对订单弹性最大。"
        ),
        confidence=0.72 if issues else 0.55,
    )

    priority_actions: list[StorefrontPriorityAction] = []
    action_specs = {
        "refresh_hero_image": (
            "重做店页第一眼主图",
            "ctr",
            24,
            "low",
            "更换主推近景实拍主图，突出分量与热气，去掉贴纸文案。",
            {"visual_brief": "45°近景，主菜占画面70%，真实蒸汽/酱汁，无促销贴纸。"},
        ),
        "refresh_signature_card": (
            "刷新招牌款展示卡",
            "ctr",
            24,
            "low",
            "把招牌款推到分类前排，并同步更新主图与短标题。",
            {"visual_brief": "招牌款独立主图 + 6字内利益点标题。"},
        ),
        "optimize_category_ia": (
            "收敛店页分类结构",
            "cvr",
            48,
            "low",
            "保留 4-7 个清晰分类，把未分类商品归位，招牌/套餐置顶。",
            {"ia_brief": "推荐顺序：招牌必点 → 超值套餐 → 主食 → 小食饮品。"},
        ),
        "surface_set_meal": (
            "补强套餐展示入口",
            "cvr",
            48,
            "medium",
            "在店页前两屏放 1-2 个低决策成本套餐，降低选择负担。",
            {"bundle_brief": "单人餐 + 双人餐各 1，价格锚点清晰。"},
        ),
        "reinforce_rating_zone": (
            "强化评分区信任素材",
            "cvr",
            72,
            "low",
            "置顶真实好评主题（分量/包装），并回复近期外观/包装负评。",
            {"trust_brief": "前 3 条置顶评突出分量与包装一致性。"},
        ),
    }
    for issue in issues[:4]:
        spec = action_specs.get(issue.suggested_action_type)
        if not spec:
            continue
        title, metric, window, risk, detail, content = spec
        priority_actions.append(
            StorefrontPriorityAction(
                action_type=issue.suggested_action_type,
                title=title,
                detail=detail,
                expected_metric=metric,
                expected_lift_pct_low=sales_impact.lift_pct_low * (1.1 if issue.severity == "high" else 0.8),
                expected_lift_pct_high=sales_impact.lift_pct_high * (1.1 if issue.severity == "high" else 0.9),
                window_hours=window,
                risk_level=risk,
                severity=issue.severity,
                object_ref=issue.object_ref or f"store:{data.store.id}",
                object_name=issue.object_name or data.store.name,
                generated_content=content,
                evidence=issue.evidence,
            )
        )

    blockers = []
    if len(items) < 3:
        blockers.append("菜单商品过少，装修诊断样本不足。")
    if image_coverage < 0.2:
        blockers.append("几乎没有商品主图，先补图再谈精细装修。")
    readiness = "ready" if not blockers and issues else "partial" if items else "limited"
    if _alignment_readiness(data.document_alignment) == "limited":
        readiness = "limited"

    conclusion = (
        f"线上装修健康分 {health_score}。"
        + (
            f"当前最大销售漏点是：{issues[0].title}。"
            if issues
            else "店页基础结构尚可，维持观察并持续优化主图与套餐。"
        )
    )

    return StorefrontAgentResult(
        meta=AgentMeta(
            key="storefront",
            label="线上装修诊断 Agent",
            confidence=sales_impact.confidence,
            generated_at=data.generated_at,
        ),
        readiness=readiness,
        blockers=blockers[:3],
        health_score=health_score,
        dimensions=dimensions,
        issues=issues[:6],
        sales_impact=sales_impact,
        priority_actions=priority_actions[:4],
        conclusion=conclusion,
        reasons=[issue.title for issue in issues[:3]]
        or ["店页主图、分类、套餐与评分区暂无高优先级漏洞。"],
        evidence=[e for dim in dimensions for e in dim.evidence[:1]][:5],
        expected_impact=sales_impact.narrative,
    )


def prioritize_storefront_actions(
    diagnosis: StorefrontAgentResult,
    recommendations: list[Recommendation],
    experiments: list[Experiment],
) -> StorefrontAgentResult:
    actions = list(diagnosis.priority_actions or [])
    if not actions:
        return diagnosis

    ranked: list[tuple[float, int, StorefrontPriorityAction]] = []
    total = len(actions)
    for index, action in enumerate(actions):
        feedback = find_recent_action_feedback(
            recommendations,
            experiments,
            action_type=action.action_type,
            object_ref=action.object_ref,
            source_tag="storefront_agent",
        )
        generated_content = dict(action.generated_content)
        evidence = list(action.evidence)
        if feedback is not None:
            generated_content.update(
                {
                    "feedback_result": feedback.result,
                    "feedback_note": feedback.note,
                    "feedback_lift_pct": feedback.lift_pct,
                }
            )
            evidence = list(dict.fromkeys([feedback.note, *evidence]))[:5]
        ranked.append(
            (
                (total - index) + (feedback.score_delta if feedback is not None else 0.0),
                index,
                action.model_copy(update={"generated_content": generated_content, "evidence": evidence}),
            )
        )

    ordered = [row[2] for row in sorted(ranked, key=lambda row: (-row[0], row[1]))]
    return diagnosis.model_copy(update={"priority_actions": ordered})


def create_storefront_action(
    db: Session,
    *,
    store_id: str,
    action_index: int,
    diagnosis: StorefrontAgentResult,
    hypothesis_id: Optional[str] = None,
    action_override: StorefrontPriorityAction | None = None,
) -> StorefrontActionCreateResponse:
    if action_override is None and (action_index < 0 or action_index >= len(diagnosis.priority_actions)):
        raise IndexError("storefront action not found")
    action = action_override or diagnosis.priority_actions[action_index]
    metric_label = {
        "ctr": "点击率",
        "cvr": "转化率",
        "orders": "订单",
    }.get(action.expected_metric, action.expected_metric)
    review_note = f"这次先围绕{metric_label}做单变量装修验证，观察窗结束后再决定保留还是回退。"
    observe_focus = [
        f"观察 {action.object_name} 带来的{metric_label}变化。",
        "观察窗内不要叠加第二个装修动作。",
    ]
    next_decision = observe_focus[0]

    existing_candidates = db.execute(
        select(Recommendation).where(
            Recommendation.store_id == store_id,
            Recommendation.action_type == action.action_type,
            Recommendation.object_ref == action.object_ref,
            Recommendation.status.in_(("proposed", "adopted", "executed")),
        )
    ).scalars().all()
    existing = None
    existing_experiment = None
    for candidate in existing_candidates:
        candidate_experiment = db.execute(
            select(Experiment)
            .where(Experiment.recommendation_id == candidate.id)
            .order_by(Experiment.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        in_observation = (
            candidate.status == "executed"
            and (
                candidate_experiment is None
                or candidate_experiment.result in {None, "pending"}
            )
        )
        if candidate.status in {"proposed", "adopted"} or in_observation:
            existing = candidate
            existing_experiment = candidate_experiment
            break
    if existing is not None:
        existing_payload = json.loads(existing.content_json or "{}")
        existing_payload.update(
            {
                "storefront_health_score": diagnosis.health_score,
                "review_note": review_note,
                "observe_focus": observe_focus,
                "next_decision": next_decision,
                "generated_content": action.generated_content,
                "evidence": action.evidence,
            }
        )
        existing.content_json = json.dumps(existing_payload, ensure_ascii=False)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return StorefrontActionCreateResponse(
            store_id=store_id,
            action_index=action_index,
            recommendation_id=existing.id,
            experiment_id=existing_experiment.id if existing_experiment else None,
            status=existing.status,
            message="该装修动作已在队列中，无需重复创建。",
            review_note=review_note,
            observe_focus=observe_focus,
            next_decision=next_decision,
            action=action,
        )

    recommendation = Recommendation(
        store_id=store_id,
        hypothesis_id=hypothesis_id,
        scope="store" if action.object_ref.startswith("store:") else "item",
        object_ref=action.object_ref,
        action_type=action.action_type,
        expected_metric=action.expected_metric,
        expected_lift_pct_low=action.expected_lift_pct_low,
        expected_lift_pct_high=action.expected_lift_pct_high,
        window_hours=action.window_hours,
        confidence=0.74 if action.severity == "high" else 0.66,
        rollback_rule="若 24-72 小时 CTR/CVR 无改善，回退到上一版主图/分类/套餐展示。",
        status="proposed",
        content_json=json.dumps(
            {
                "source": "storefront_agent",
                "title": action.title,
                "detail": action.detail,
                "risk_level": action.risk_level,
                "storefront_health_score": diagnosis.health_score,
                "review_note": review_note,
                "observe_focus": observe_focus,
                "next_decision": next_decision,
                "generated_content": action.generated_content,
                "evidence": action.evidence,
                "feedback_history": [
                    {
                        "status": "proposed",
                        "at": datetime.now(timezone.utc).isoformat(),
                        "message": "线上装修 Agent 已生成可执行动作",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        evidence_json=json.dumps(action.evidence, ensure_ascii=False),
    )
    db.add(recommendation)
    db.commit()
    db.refresh(recommendation)
    return StorefrontActionCreateResponse(
        store_id=store_id,
        action_index=action_index,
        recommendation_id=recommendation.id,
        experiment_id=None,
        status=recommendation.status,
        message=f"已生成装修动作「{action.title}」，等待采纳执行。",
        review_note=review_note,
        observe_focus=observe_focus,
        next_decision=next_decision,
        action=action,
    )


STOREFRONT_ACTION_TYPES = {
    "refresh_hero_image",
    "refresh_signature_card",
    "optimize_category_ia",
    "surface_set_meal",
    "reinforce_rating_zone",
}


def attach_storefront_queue(
    diagnosis: StorefrontAgentResult,
    recommendations: list[Recommendation],
    experiments: list[Experiment] | None = None,
) -> StorefrontAgentResult:
    experiment_map = {exp.recommendation_id: exp for exp in (experiments or []) if getattr(exp, "recommendation_id", None)}
    queue: list[AgentWorkflowItem] = []
    for rec in recommendations:
        content = {}
        try:
            content = json.loads(rec.content_json or "{}")
        except json.JSONDecodeError:
            content = {}
        if rec.action_type not in STOREFRONT_ACTION_TYPES and content.get("source") != "storefront_agent":
            continue
        experiment = experiment_map.get(rec.id)
        if rec.status in {"proposed", "adopted"}:
            execution_phase = "execute_now"
            phase_reason = "建议先确认并上线当前装修动作。"
        elif rec.status == "archived":
            execution_phase = "archived"
            phase_reason = "这条装修动作已归档，当前不再推进。"
        elif experiment is None or experiment.result in {None, "pending"}:
            execution_phase = "observe"
            phase_reason = "动作已执行，当前先盯 CTR/CVR 观察窗。"
        else:
            execution_phase = "review"
            phase_reason = "动作已有结果，先复盘再决定是否放大。"
        queue.append(
            AgentWorkflowItem(
                recommendation_id=rec.id,
                title=content.get("title") or rec.action_type,
                action_type=rec.action_type,
                object_ref=rec.object_ref,
                object_name=content.get("object_name") or rec.object_ref,
                status=rec.status,
                execution_phase=execution_phase,
                phase_reason=phase_reason,
                expected_metric=rec.expected_metric or "ctr",
                window_hours=rec.window_hours or 24,
                confidence=float(rec.confidence or 0.6),
                rollback_rule=rec.rollback_rule,
                evidence=list(content.get("evidence") or []),
                generated_content=dict(content.get("generated_content") or {}),
                experiment_id=getattr(experiment, "id", None) if experiment else None,
                experiment_result=getattr(experiment, "result", None) if experiment else None,
                experiment_lift_pct=getattr(experiment, "lift_pct", None) if experiment else None,
                experiment_notes=getattr(experiment, "notes", None) if experiment else None,
                next_decision=content.get("next_decision") or "先采纳并上线，再看 CTR/CVR",
            )
        )
    phase_rank = {"execute_now": 0, "review": 1, "observe": 2, "deferred": 3, "archived": 4}
    queue = sorted(queue, key=lambda item: (phase_rank.get(item.execution_phase, 2), -float(item.confidence)))
    diagnosis.action_queue = queue[:5]
    diagnosis.current_action = queue[0] if queue else None
    return diagnosis
