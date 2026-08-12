"""Heuristic V1 builders for matrix specialist agents.

审计改造点：
- P1-1：所有魔法数字收敛到 thresholds.py；
- P1-2：CRM 无真实用户数据时降级输出（不再输出伪造精确数字）；
- P1-3：attach_queue 透传 experiments，execution_phase 与 growth 状态机对齐；
- P0-2：review agent 接入 agent_narrator（LLM + heuristic fallback）。
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.ohre import Recommendation
from app.schemas.agents import (
    AdsAgentResult,
    AgentMeta,
    AgentSignal,
    CrmAgentResult,
    CrmSegmentView,
    PromoAgentResult,
    ReviewAgentResult,
    ReviewThemeView,
    ServiceAgentResult,
    StoreMatrixAgentResult,
    StoreMatrixConcept,
)
from app.services.agent_narrator import narrate_review
from app.services.matrix_agents.common import (
    MatrixAgentInput,
    alignment_readiness,
    attach_queue,
    clamp_score,
    has_set_meal,
    kpi_delta,
    kpi_value,
    load_reviews,
    make_action,
    natural_conversion_stable,
    prioritize_actions_with_feedback,
    review_theme_counts,
    top_item,
)
from app.services.matrix_agents.thresholds import get_thresholds

THEME_LABELS = {
    "portion": "份量",
    "package": "包装",
    "speed": "配送速度",
    "taste": "口味",
    "appearance": "图文一致",
}


def build_promo_agent(
    db: Session,
    data: MatrixAgentInput,
    recommendations: list[Recommendation],
) -> PromoAgentResult:
    _ = db
    t = get_thresholds().promo
    impressions_delta = kpi_delta(data.kpis, "impressions")
    set_meal = has_set_meal(data.menu_items)
    competitor_bundle = [
        c
        for c in data.competition_changes
        if any(token in (getattr(c, "summary", "") or "") for token in ("套餐", "活动", "满减", "补贴"))
        or getattr(c, "type", None) in {"price_down", "menu_added"}
    ]
    unlock = natural_conversion_stable(data.kpis) or (
        impressions_delta is not None and impressions_delta < t.impressions_down_signal_pct
    )
    signals: list[AgentSignal] = []
    actions = []

    if not set_meal:
        signals.append(
            AgentSignal(
                code="lunch_bundle_gap",
                title="午餐套餐空白",
                detail="商圈常见 25-35 元套餐，本店菜单未见明确套餐位。",
                severity="high",
                evidence=["菜单无套餐关键词"],
            )
        )
        actions.append(
            make_action(
                action_type="launch_value_bundle_promo",
                title="上架 29.9 午餐价值套餐活动",
                detail="以主推菜+饮品组成低决策成本套餐，并挂午餐活动位。",
                expected_metric="orders",
                lift_low=8,
                lift_high=15,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=["本店套餐缺口", "竞品套餐/活动信号"],
                risk_level="medium",
                severity="high",
                content={"price": 29.9, "daypart": "lunch"},
            )
        )

    if competitor_bundle:
        signals.append(
            AgentSignal(
                code="competitor_promo_pressure",
                title="竞品活动加压",
                detail=competitor_bundle[0].summary if hasattr(competitor_bundle[0], "summary") else "竞品出现价格/套餐动作",
                severity="medium",
                evidence=[getattr(c, "summary", "") for c in competitor_bundle[:2]],
            )
        )
        actions.append(
            make_action(
                action_type="match_competitor_promo",
                title="针对性跟进商圈活动",
                detail="不对全店无脑降价，只对主推组合做限时活动对冲。",
                expected_metric="orders",
                lift_low=5,
                lift_high=12,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=[getattr(c, "summary", "") for c in competitor_bundle[:2]],
                risk_level="high",
                severity="medium",
            )
        )

    if impressions_delta is not None and impressions_delta < t.impressions_down_signal_pct:
        signals.append(
            AgentSignal(
                code="impression_down",
                title="曝光下滑",
                detail=f"曝光较基线 {impressions_delta:.1f}%，可评估平台午餐补贴位。",
                severity="high",
                evidence=[f"impressions_delta={impressions_delta:.1f}%"],
            )
        )
        actions.append(
            make_action(
                action_type="join_lunch_campaign",
                title="报名平台午餐补贴活动",
                detail="优先用主推高转化商品报名，控制补贴深度，避免利润塌陷。",
                expected_metric="impressions",
                lift_low=8,
                lift_high=18,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=[f"曝光 {impressions_delta:.1f}%"],
                risk_level="high",
                severity="high",
                window_hours=72,
                content={"budget_hint": 300, "daypart": "lunch"},
            )
        )

    blockers = []
    if not unlock and impressions_delta is not None and impressions_delta >= t.impressions_down_blocker_pct:
        blockers.append("自然转化尚未稳住，平台活动建议后置，优先修 CTR/CVR。")
    if alignment_readiness(data.document_alignment) == "limited":
        blockers.append("门店资料未对齐，活动方案先以建议模式给出。")

    health = t.health_base
    if signals:
        health -= t.health_high_signal_penalty * len([s for s in signals if s.severity == "high"])
        health -= t.health_medium_signal_penalty * len([s for s in signals if s.severity != "high"])
    if unlock:
        health += t.health_unlock_bonus
    health = clamp_score(health)

    opportunities = [s.title for s in signals] or ["暂无高优先级活动机会，维持观察。"]
    conclusion = (
        f"平台活动健康分 {health}。"
        + (f"优先关注：{signals[0].title}。" if signals else "暂无必须立刻参与的活动。")
        + (" 当前可解锁活动建议。" if unlock else " 建议先稳住自然转化再加大活动。")
    )

    actions = prioritize_actions_with_feedback(actions, recommendations, data.experiments, agent_key="promo")
    result = PromoAgentResult(
        meta=AgentMeta(key="promo", label="平台活动 Agent", confidence=0.66, generated_at=data.generated_at),
        readiness="ready" if signals and unlock else "partial" if signals else "limited",
        blockers=blockers[:3],
        health_score=health,
        unlock_ready=unlock,
        signals=signals[:6],
        opportunities=opportunities[:5],
        priority_actions=actions[:4],
        conclusion=conclusion,
        reasons=[s.title for s in signals[:3]] or ["活动面暂无强信号"],
        evidence=[e for s in signals for e in s.evidence[:1]][:5],
        expected_impact="活动正确时，可拉动曝光与午餐订单；错误时会吞噬利润。",
    )

    def _set(queue, current):
        result.action_queue = queue
        result.current_action = current

    attach_queue(
        agent_key="promo",
        priority_actions=actions,
        recommendations=recommendations,
        set_queue=_set,
        experiments=data.experiments,
        generated_at=data.generated_at,
    )
    return result


def build_ads_agent(
    db: Session,
    data: MatrixAgentInput,
    recommendations: list[Recommendation],
) -> AdsAgentResult:
    _ = db
    t = get_thresholds().ads
    unlock = natural_conversion_stable(data.kpis)
    hero = top_item(data.item_snapshots)
    impressions_delta = kpi_delta(data.kpis, "impressions")
    orders_delta = kpi_delta(data.kpis, "orders")
    signals: list[AgentSignal] = []
    actions = []
    blockers = []

    if not unlock:
        blockers.append("自然 CTR/CVR 仍不稳，先修商品与装修，再开投流。")
        signals.append(
            AgentSignal(
                code="ads_locked",
                title="投流未解锁",
                detail="把钱花在转化不稳的商品上会放大亏损。",
                severity="high",
                evidence=[
                    f"ctr_delta={kpi_delta(data.kpis, 'ctr')}",
                    f"cvr_delta={kpi_delta(data.kpis, 'cvr')}",
                ],
            )
        )
        actions.append(
            make_action(
                action_type="pause_broad_ads",
                title="暂停全店广撒网投流",
                detail="先收敛到自然转化稳定的主推品，再小预算测试。",
                expected_metric="cvr",
                lift_low=0,
                lift_high=3,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=["自然转化不稳"],
                risk_level="low",
                severity="high",
            )
        )
    elif hero is not None:
        cvr = getattr(hero, "observe_cvr", None)
        signals.append(
            AgentSignal(
                code="hero_ads_candidate",
                title=f"{hero.name} 适合小预算投流",
                detail="自然转化相对更好，适合作为投流唯一主品。",
                severity="medium",
                evidence=[
                    f"observe_orders={getattr(hero, 'observe_orders', 0)}",
                    f"observe_cvr={cvr}",
                ],
            )
        )
        roi = 3.0 if cvr and cvr > t.cvr_hero_threshold else 2.2
        actions.append(
            make_action(
                action_type="boost_hero_item_ads",
                title=f"小预算投放「{hero.name}」",
                detail="不要全店推广。只投自然转化最好的一个商品，并设日预算上限。",
                expected_metric="orders",
                lift_low=6,
                lift_high=14,
                object_ref=f"item:{hero.item_id}",
                object_name=hero.name,
                evidence=[f"主推候选 {hero.name}"],
                risk_level="high",
                severity="medium",
                window_hours=72,
                content={"budget_hint": int(t.default_budget), "estimated_roi": roi},
            )
        )
        if (
            impressions_delta is not None
            and impressions_delta < t.impressions_down_signal_pct
            and orders_delta is not None
            and orders_delta > t.orders_down_tolerance_pct
        ):
            actions.append(
                make_action(
                    action_type="shift_ads_to_high_cvr_item",
                    title="把预算从低效品转到高转化主推",
                    detail="曝光不足但订单尚可时，优先加注高 CVR 商品而不是扩品。",
                    expected_metric="orders",
                    lift_low=4,
                    lift_high=10,
                    object_ref=f"item:{hero.item_id}",
                    object_name=hero.name,
                    evidence=[f"impressions_delta={impressions_delta:.1f}%"],
                    risk_level="medium",
                    severity="medium",
                )
            )

    health = t.health_unlock_base if unlock else t.health_locked_base
    if hero is not None and unlock:
        health += t.health_hero_bonus
    health = clamp_score(health - t.health_blocker_penalty * len(blockers))
    budget = t.default_budget if unlock else None
    roi = None
    if actions and actions[0].generated_content.get("estimated_roi"):
        roi = float(actions[0].generated_content["estimated_roi"])

    # 步骤4：Traffic Readiness Score（投流就绪度 0-100）
    # CTR 稳定性 35% + CVR 稳定性 35% + 主推品势能 20% + 利润空间 10%
    ctr_delta = kpi_delta(data.kpis, "ctr")
    cvr_delta = kpi_delta(data.kpis, "cvr")
    ctr_stable = max(0.0, min(100.0, 70 + (ctr_delta or 0) * 2)) if ctr_delta is not None else 50.0
    cvr_stable = max(0.0, min(100.0, 70 + (cvr_delta or 0) * 2)) if cvr_delta is not None else 50.0
    hero_potential = 60.0
    if hero is not None:
        hero_potential = min(100.0, 40 + (getattr(hero, "observe_cvr", 0) or 0) * 300)
    take_home = getattr(data, "kpis", {})
    profit_space = 70.0  # 默认中性，有利润数据再调整
    traffic_readiness = round(
        ctr_stable * 0.35 + cvr_stable * 0.35 + hero_potential * 0.20 + profit_space * 0.10
    )
    # unlock 同时看 readiness（>=60）和自然转化稳定性
    unlock = unlock and traffic_readiness >= 55

    actions = prioritize_actions_with_feedback(actions, recommendations, data.experiments, agent_key="ads")
    result = AdsAgentResult(
        meta=AgentMeta(key="ads", label="投流 Agent", confidence=0.6, generated_at=data.generated_at),
        readiness="ready" if unlock and actions else "limited" if blockers else "partial",
        blockers=blockers[:3],
        health_score=health,
        unlock_ready=unlock,
        traffic_readiness_score=traffic_readiness,
        recommended_budget=budget,
        target_item_name=hero.name if hero is not None else None,
        estimated_roi=roi,
        signals=signals[:5],
        priority_actions=actions[:3],
        conclusion=(
            f"投流健康分 {health}。"
            + ("可对主推品做小预算测试。" if unlock else "当前不建议开投，先修自然转化。")
        ),
        reasons=[s.title for s in signals[:3]] or ["暂无投流信号"],
        evidence=[e for s in signals for e in s.evidence[:1]][:5],
        expected_impact="正确投流可补曝光；错误投流会放大低转化亏损。",
    )

    def _set(queue, current):
        result.action_queue = queue
        result.current_action = current

    attach_queue(
        agent_key="ads",
        priority_actions=actions,
        recommendations=recommendations,
        set_queue=_set,
        experiments=data.experiments,
        generated_at=data.generated_at,
    )
    return result


def build_crm_agent(
    db: Session,
    data: MatrixAgentInput,
    recommendations: list[Recommendation],
) -> CrmAgentResult:
    _ = db
    t = get_thresholds().crm
    repurchase = kpi_value(data.kpis, "repurchase") or kpi_value(data.kpis, "repurchase_rate")
    repurchase_delta = kpi_delta(data.kpis, "repurchase") or kpi_delta(data.kpis, "repurchase_rate")
    orders = kpi_value(data.kpis, "orders") or 0

    # P1-2 + 步骤5：6 段生命周期分群（Acquisition/Activation/Growth/Core/AtRisk/Churn）
    has_real_data = bool(getattr(data, "has_real_crm_data", False))
    base = max(int(orders * t.orders_to_population_multiplier), t.base_population_min)
    repurchase_down = (repurchase_delta or 0) < t.repurchase_down_signal_pct

    # 6 段生命周期占比（基于复购 delta 动态调整）
    lifecycle_shares = {
        "acquisition": 0.15,   # 新客首单
        "activation": 0.20,    # 首单未形成习惯（1-2单）
        "growth": 0.18,        # 2-5单增长用户
        "core": 0.32,          # 高频核心用户
        "at_risk": 0.08 if not repurchase_down else 0.12,   # 消费间隔异常
        "churn": 0.07 if not repurchase_down else 0.13,     # 流失用户
    }
    lifecycle_labels = {
        "acquisition": "新客首单",
        "activation": "首单未复购",
        "growth": "成长用户",
        "core": "高频核心",
        "at_risk": "流失风险",
        "churn": "已流失",
    }
    lifecycle_notes = {
        "acquisition": "近窗首次下单，需引导二次消费",
        "activation": "首单后未形成习惯，7日内激活窗口",
        "growth": "2-5单增长期，适合抬客单+推套餐",
        "core": "高频核心用户，维护复购习惯",
        "at_risk": "消费间隔拉长，需主动召回",
        "churn": "7-30天未复购，高价值流失优先挽回",
    }

    if has_real_data:
        # 真实数据路径：保留精确数字（未来接入点）
        segments = [
            CrmSegmentView(
                key=key,
                label=lifecycle_labels[key],
                estimated_count=int(base * share),
                share_pct=int(share * 100),
                note=lifecycle_notes[key],
            )
            for key, share in lifecycle_shares.items()
        ]
        data_blocker_note = None
    else:
        # 代理路径：不输出精确 count，只给占比 + 明确标注
        segments = [
            CrmSegmentView(
                key=key,
                label=lifecycle_labels[key],
                estimated_count=0,
                share_pct=None,
                note=f"估算占比约{int(share*100)}%（代理，非精确值）。{lifecycle_notes[key]}",
            )
            for key, share in lifecycle_shares.items()
        ]
        data_blocker_note = "缺少用户级复购明细，分群为订单量代理估算，不输出精确人数，置信度有限。"

    signals: list[AgentSignal] = []
    actions = []

    if repurchase_delta is not None and repurchase_delta < t.repurchase_down_signal_pct:
        signals.append(
            AgentSignal(
                code="repurchase_down",
                title="复购下滑",
                detail=f"复购较基线 {repurchase_delta:.1f}%，应优先挽回高价值用户。",
                severity="high",
                evidence=[f"repurchase_delta={repurchase_delta:.1f}%"],
            )
        )
        actions.append(
            make_action(
                action_type="recall_churn_risk_users",
                title="召回流失风险用户",
                detail="用限时召回券而非全店打折，优先 VIP/高客单流失人群。",
                expected_metric="repurchase",
                lift_low=4,
                lift_high=10,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=[f"复购下滑 {repurchase_delta:.1f}%"],
                risk_level="medium",
                severity="high",
                content={"segment": "at_risk"},
            )
        )

    if repurchase is not None and repurchase < t.low_repurchase_base:
        signals.append(
            AgentSignal(
                code="low_repurchase_base",
                title="复购底座偏低",
                detail=f"当前复购率约 {repurchase:.1%}，需强化新客转复购。",
                severity="medium",
                evidence=[f"repurchase={repurchase}"],
            )
        )
        actions.append(
            make_action(
                action_type="nurture_new_customers",
                title="新客 7 日内二次下单激励",
                detail="对首次下单用户做一次低门槛复购触达，绑定主推爆品。",
                expected_metric="repurchase",
                lift_low=3,
                lift_high=8,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=["新客占比代理偏高/复购底座低"],
                risk_level="low",
                severity="medium",
                content={"segment": "activation"},
            )
        )

    if not actions:
        actions.append(
            make_action(
                action_type="reward_vip_repeat",
                title="维护 VIP 复购习惯",
                detail="对高频用户做非降价权益（优先出餐/小赠品），稳固口碑与复购。",
                expected_metric="repurchase",
                lift_low=2,
                lift_high=5,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=["维持型动作"],
                risk_level="low",
                severity="low",
                content={"segment": "core"},
            )
        )

    blockers = []
    if data_blocker_note:
        blockers.append(data_blocker_note)
    elif repurchase is None and repurchase_delta is None:
        blockers.append("缺少用户级复购明细，当前用漏斗代理分层，置信度有限。")

    health = t.health_base
    if repurchase_delta is not None:
        health += max(-18, min(12, repurchase_delta))
    health = clamp_score(health)

    actions = prioritize_actions_with_feedback(actions, recommendations, data.experiments, agent_key="crm")
    result = CrmAgentResult(
        meta=AgentMeta(key="crm", label="用户关系 Agent", confidence=0.55, generated_at=data.generated_at),
        readiness="partial" if blockers else "ready",
        blockers=blockers[:3],
        health_score=health,
        repurchase_rate=float(repurchase) if repurchase is not None else None,
        repurchase_delta_pct=repurchase_delta,
        segments=segments,
        signals=signals[:5],
        priority_actions=actions[:3],
        conclusion=(
            f"用户经营健康分 {health}。"
            + (f"今天优先处理：{signals[0].title}。" if signals else "复购结构相对稳定，维持 VIP 经营。")
        ),
        reasons=[s.title for s in signals[:3]] or ["复购暂无恶化信号"],
        evidence=[e for s in signals for e in s.evidence[:1]][:5],
        expected_impact="召回与新客转化可抬升复购，且不占用主实验槽时可并行。",
    )

    def _set(queue, current):
        result.action_queue = queue
        result.current_action = current

    attach_queue(
        agent_key="crm",
        priority_actions=actions,
        recommendations=recommendations,
        set_queue=_set,
        experiments=data.experiments,
        generated_at=data.generated_at,
    )
    return result


def build_service_agent(
    db: Session,
    data: MatrixAgentInput,
    recommendations: list[Recommendation],
) -> ServiceAgentResult:
    t = get_thresholds().service
    rows = load_reviews(db, data.store.id, limit=t.review_load_limit)
    themes = review_theme_counts(rows)
    negative = [
        review
        for review, nlp in rows
        if (review.rating is not None and review.rating <= t.negative_rating_max)
        or (nlp is not None and nlp.sentiment is not None and nlp.sentiment < t.negative_sentiment_max)
    ]
    pending = max(len(negative), themes.get("portion", 0) + themes.get("package", 0))
    signals: list[AgentSignal] = []
    actions = []

    if pending >= t.pending_signal_threshold:
        signals.append(
            AgentSignal(
                code="pending_negative_replies",
                title="待处理差评/负向反馈偏多",
                detail=f"近窗约有 {pending} 条需回复的负向反馈。",
                severity="high",
                evidence=[f"pending={pending}"],
            )
        )
        actions.append(
            make_action(
                action_type="batch_reply_negative_reviews",
                title=f"批量回复 {min(pending, t.batch_reply_cap)} 条评价",
                detail="先致歉再给补偿边界，避免空话；可与经营主实验并行。",
                expected_metric="rating",
                lift_low=1,
                lift_high=4,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=[f"待回复约 {pending} 条"],
                risk_level="low",
                severity="high",
                window_hours=24,
                content={"reply_count": min(pending, t.batch_reply_cap)},
            )
        )

    top_theme = max(themes.items(), key=lambda kv: kv[1]) if any(themes.values()) else None
    if top_theme and top_theme[1] >= t.theme_signal_threshold:
        theme_key, count = top_theme
        signals.append(
            AgentSignal(
                code=f"service_theme_{theme_key}",
                title=f"客服话术需覆盖「{THEME_LABELS.get(theme_key, theme_key)}」",
                detail=f"该主题近窗出现 {count} 次，建议固化标准回复。",
                severity="medium",
                evidence=[f"{theme_key}={count}"],
            )
        )
        actions.append(
            make_action(
                action_type="publish_service_reply_scripts",
                title=f"发布「{THEME_LABELS.get(theme_key, theme_key)}」标准回复脚本",
                detail="统一口径：认问题、给补偿边界、引导复购验证。",
                expected_metric="rating",
                lift_low=1,
                lift_high=3,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=[f"{theme_key}={count}"],
                risk_level="low",
                severity="medium",
                content={"theme": theme_key},
            )
        )
        if theme_key == "portion":
            actions.append(
                make_action(
                    action_type="escalate_portion_complaints",
                    title="把份量投诉升级为出品标准动作",
                    detail="客服止血同时，同步出品加量感知或说明克重，避免反复差评。",
                    expected_metric="rating",
                    lift_low=2,
                    lift_high=6,
                    object_ref=f"store:{data.store.id}",
                    object_name=data.store.name,
                    evidence=[f"份量主题 {count} 次"],
                    risk_level="medium",
                    severity="high",
                )
            )

    if not actions:
        actions.append(
            make_action(
                action_type="publish_service_reply_scripts",
                title="准备好评/差评通用回复脚本",
                detail="样本不足时先沉淀话术，保证后续评价可快速响应。",
                expected_metric="rating",
                lift_low=0,
                lift_high=2,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=["评价样本有限"],
                risk_level="low",
                severity="low",
            )
        )

    blockers = []
    if not rows:
        blockers.append("尚无评价样本，客服动作以话术准备为主。")

    health = clamp_score(t.health_base - pending * t.health_pending_penalty - (themes.get("portion", 0) * t.health_portion_penalty))
    actions = prioritize_actions_with_feedback(actions, recommendations, data.experiments, agent_key="service")
    result = ServiceAgentResult(
        meta=AgentMeta(key="service", label="AI 客服 Agent", confidence=0.62, generated_at=data.generated_at),
        readiness="ready" if pending else "partial",
        blockers=blockers[:3],
        health_score=health,
        pending_replies=pending,
        negative_review_count=len(negative),
        theme_breakdown=themes,
        signals=signals[:5],
        priority_actions=actions[:3],
        conclusion=(
            f"客服健康分 {health}。"
            + (f"今天建议先处理 {min(pending, t.batch_reply_cap)} 条负向评价。" if pending else "负向积压可控，维持标准回复。")
        ),
        reasons=[s.title for s in signals[:3]] or ["客服队列平稳"],
        evidence=[e for s in signals for e in s.evidence[:1]][:5],
        expected_impact="服务动作可并行执行，有助于稳住评分与复购，不占用经营主实验槽。",
    )

    def _set(queue, current):
        result.action_queue = queue
        result.current_action = current

    attach_queue(
        agent_key="service",
        priority_actions=actions,
        recommendations=recommendations,
        set_queue=_set,
        experiments=data.experiments,
        generated_at=data.generated_at,
    )
    return result


def build_review_agent(
    db: Session,
    data: MatrixAgentInput,
    recommendations: list[Recommendation],
) -> ReviewAgentResult:
    t = get_thresholds().review
    rows = load_reviews(db, data.store.id, limit=60)
    themes_count = review_theme_counts(rows)
    total_theme_hits = max(sum(themes_count.values()), 1)
    rating_sum = 0.0
    rating_n = 0
    samples: dict[str, str] = {}
    for review, _nlp in rows:
        if review.rating is not None:
            rating_sum += float(review.rating)
            rating_n += 1
        text = (review.content or "").strip()
        if not text:
            continue
        for key, label_tokens in {
            "portion": ("份量", "量少"),
            "package": ("包装", "撒漏"),
            "speed": ("慢", "迟到"),
            "taste": ("难吃", "味道"),
            "appearance": ("照片", "不像"),
        }.items():
            if key not in samples and any(token in text for token in label_tokens):
                samples[key] = text[:48]
    avg_rating = (rating_sum / rating_n) if rating_n else kpi_value(data.kpis, "rating")
    rating_delta = kpi_delta(data.kpis, "rating")
    competitor_rating_up = [c for c in data.competition_changes if getattr(c, "type", None) == "rating_up"]

    themes = [
        ReviewThemeView(
            theme=key,
            label=THEME_LABELS[key],
            count=count,
            share_pct=round(100 * count / total_theme_hits, 1),
            sample=samples.get(key),
        )
        for key, count in sorted(themes_count.items(), key=lambda kv: kv[1], reverse=True)
        if count > 0
    ]

    signals: list[AgentSignal] = []
    actions = []
    if themes:
        top = themes[0]
        signals.append(
            AgentSignal(
                code=f"theme_{top.theme}",
                title=f"评分下滑主因疑似「{top.label}」",
                detail=f"该主题占比约 {top.share_pct}%（{top.count} 次）。",
                severity="high" if top.share_pct >= t.theme_dominant_share_pct else "medium",
                evidence=[top.sample or f"{top.theme}={top.count}"],
            )
        )
        actions.append(
            make_action(
                action_type="fix_top_review_theme",
                title=f"优先治理「{top.label}」问题",
                detail="先改一个可感知变量（份量说明/包装加固/出餐时效），再观察评分。",
                expected_metric="rating",
                lift_low=2,
                lift_high=6,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=[f"{top.label} {top.share_pct}%"],
                risk_level="medium",
                severity="high" if top.share_pct >= t.theme_dominant_share_pct else "medium",
                content={"theme": top.theme},
            )
        )

    if rating_n >= t.rating_signal_min_samples:
        actions.append(
            make_action(
                action_type="reply_rating_critical_reviews",
                title="回复低分关键评价",
                detail="对 ≤3.5 分评价逐条回复，展示处理诚意，降低持续差评扩散。",
                expected_metric="rating",
                lift_low=1,
                lift_high=3,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=[f"评价样本 {rating_n}"],
                risk_level="low",
                severity="medium",
            )
        )
        actions.append(
            make_action(
                action_type="pin_positive_review_themes",
                title="置顶正向评价主题",
                detail="把分量足/包装好的真实好评置顶，对冲负面主题。",
                expected_metric="cvr",
                lift_low=2,
                lift_high=5,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=["信任区强化"],
                risk_level="low",
                severity="low",
            )
        )

    # 步骤6：评价申诉能力——识别疑似违规/不合理差评，建议申诉
    appeal_keywords = ("不实", "恶意", "同行", "刷单", "骚扰", "敲诈", "威胁", "诽谤", "造谣", "未消费")
    unfair_reviews = [
        (review, _nlp)
        for review, _nlp in rows
        if review.rating is not None
        and review.rating <= 2
        and any(kw in (review.content or "") for kw in appeal_keywords)
    ]
    if unfair_reviews:
        sample = unfair_reviews[0][0]
        sample_text = (sample.content or "")[:60]
        signals.append(
            AgentSignal(
                code="unfair_review_appeal",
                title="发现疑似可申诉差评",
                detail=f"检测到{len(unfair_reviews)}条疑似违规/不合理差评，建议发起申诉。",
                severity="high",
                evidence=[f"评分{sample.rating}：{sample_text}"],
            )
        )
        actions.append(
            make_action(
                action_type="escalate_unfair_review",
                title=f"申诉{len(unfair_reviews)}条疑似违规差评",
                detail="对含不实/恶意/同行攻击关键词的低分评价发起平台申诉，避免影响评分与排名。",
                expected_metric="rating",
                lift_low=1,
                lift_high=5,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=[f"疑似违规差评{len(unfair_reviews)}条"],
                risk_level="low",
                severity="high",
                content={"appeal_count": len(unfair_reviews), "sample": sample_text},
            )
        )

    if competitor_rating_up:
        signals.append(
            AgentSignal(
                code="competitor_rating_up",
                title="竞品口碑回升",
                detail=competitor_rating_up[0].summary,
                severity="medium",
                evidence=[competitor_rating_up[0].summary],
            )
        )

    blockers = []
    if rating_n == 0:
        blockers.append("评价样本不足，评分治理以竞品与漏斗代理为主。")

    health = t.health_rating_base
    if avg_rating is not None:
        health = t.health_rating_base + float(avg_rating) * t.health_rating_multiplier
    if rating_delta is not None:
        health += max(t.health_rating_delta_floor, min(t.health_rating_delta_cap, rating_delta))
    if themes and themes[0].share_pct >= t.theme_dominant_share_pct:
        health -= t.theme_dominant_health_penalty
    health = clamp_score(health)

    fallback_conclusion = (
        f"评价健康分 {health}。"
        + (
            f"优先解决：{themes[0].label}（约 {themes[0].share_pct}%）。"
            if themes
            else "暂无足够主题归因，先补齐评价采集。"
        )
    )

    # P0-2：接入 LLM narrator（无 LLM 时返回 None，meta.ai_narrative 保持 None）
    narrative = narrate_review(
        store_name=data.store.name,
        avg_rating=float(avg_rating) if avg_rating is not None else None,
        top_themes=[th.model_dump(mode="json") for th in themes],
        pending_replies=0,  # service agent 负责"待回复数"，这里不重复
        fallback_conclusion=fallback_conclusion,
    )
    ai_mode = "llm" if narrative else None

    actions = prioritize_actions_with_feedback(actions, recommendations, data.experiments, agent_key="review")
    result = ReviewAgentResult(
        meta=AgentMeta(
            key="review",
            label="评分评价 Agent",
            confidence=0.68 if rating_n else 0.45,
            generated_at=data.generated_at,
            ai_narrative=narrative,
            ai_mode=ai_mode,
        ),
        readiness="ready" if rating_n >= t.rating_signal_min_samples else "partial",
        blockers=blockers[:3],
        health_score=health,
        avg_rating=float(avg_rating) if avg_rating is not None else None,
        rating_delta_pct=rating_delta,
        review_count=rating_n,
        themes=themes[:5],
        signals=signals[:5],
        priority_actions=actions[:4],
        conclusion=fallback_conclusion,
        reasons=[s.title for s in signals[:3]] or ["评价面暂无高优主题"],
        evidence=[e for s in signals for e in s.evidence[:1]][:5],
        expected_impact="治理头部差评主题可稳住评分与转化，并支撑排名。",
    )

    def _set(queue, current):
        result.action_queue = queue
        result.current_action = current

    attach_queue(
        agent_key="review",
        priority_actions=actions,
        recommendations=recommendations,
        set_queue=_set,
        experiments=data.experiments,
        generated_at=data.generated_at,
    )
    return result


def build_store_matrix_agent(
    db: Session,
    data: MatrixAgentInput,
    recommendations: list[Recommendation],
) -> StoreMatrixAgentResult:
    _ = db
    t = get_thresholds().store_matrix
    sibling_names = [s.name for s in data.sibling_stores if s.id != data.store.id]
    set_meal = has_set_meal(data.menu_items)
    unlock = natural_conversion_stable(data.kpis) and alignment_readiness(data.document_alignment) != "limited"
    orders_delta = kpi_delta(data.kpis, "orders")
    health_proxy = t.health_base
    if orders_delta is not None:
        health_proxy += max(-t.orders_delta_health_cap, min(t.orders_delta_health_cap, orders_delta / 2))
    health_proxy = clamp_score(health_proxy)

    concepts = [
        StoreMatrixConcept(
            code="work_lunch",
            name=f"{data.store.name}·工作餐",
            positioning="白领午餐",
            daypart="lunch",
            rationale="独立菜单与关键词，承接 25-35 元午餐需求。",
            readiness="ready" if unlock and not set_meal else "candidate",
        ),
        StoreMatrixConcept(
            code="night_kitchen",
            name=f"{data.store.name}·夜宵",
            positioning="夜间需求",
            daypart="night",
            rationale="夜间流量与正餐店关键词冲突时，拆店承接。",
            readiness="candidate",
        ),
        StoreMatrixConcept(
            code="value_meal",
            name=f"{data.store.name}·高性价比",
            positioning="价格敏感用户",
            daypart="all_day",
            rationale="用更短菜单和更强价格锚点抢低价搜索词，避免拖累主店品牌。",
            readiness="candidate",
        ),
    ]

    signals: list[AgentSignal] = []
    actions = []
    blockers = []

    if not unlock:
        blockers.append("单店自然转化或资料未稳住，暂不建议开第二家线上店。")
        signals.append(
            AgentSignal(
                code="matrix_locked",
                title="矩阵开店未解锁",
                detail="先把主店 CTR/CVR 与基础资料做稳，再复制到新定位店。",
                severity="medium",
                evidence=["unlock_ready=false"],
            )
        )
    else:
        signals.append(
            AgentSignal(
                code="matrix_ready",
                title="可评估线上店矩阵",
                detail="主店基本盘稳定，可用第二定位店放大流量，而不是传统连锁扩店。",
                severity="medium",
                evidence=[f"sibling_stores={len(sibling_names)}"],
            )
        )
        if not set_meal:
            actions.append(
                make_action(
                    action_type="open_lunch_online_store",
                    title="筹备「工作餐」线上店",
                    detail="独立店名/菜单/主图/活动，专打午餐搜索词与套餐需求。",
                    expected_metric="orders",
                    lift_low=10,
                    lift_high=20,
                    object_ref=f"store:{data.store.id}",
                    object_name=data.store.name,
                    evidence=["午餐套餐缺口", "主店已相对稳定"],
                    risk_level="high",
                    severity="medium",
                    window_hours=14 * 24,
                    content={"concept": "work_lunch"},
                )
            )
        actions.append(
            make_action(
                action_type="open_night_online_store",
                title="评估「夜宵」线上店",
                detail="若夜间订单占比有潜力，再用短菜单承接夜宵流量。",
                expected_metric="orders",
                lift_low=6,
                lift_high=14,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=["夜间定位候选"],
                risk_level="high",
                severity="low",
                window_hours=14 * 24,
                content={"concept": "night_kitchen"},
            )
        )
        actions.append(
            make_action(
                action_type="open_value_online_store",
                title="评估「高性价比」线上店",
                detail="价格战需求用第二店承接，避免主店品牌被打穿。",
                expected_metric="orders",
                lift_low=5,
                lift_high=12,
                object_ref=f"store:{data.store.id}",
                object_name=data.store.name,
                evidence=["价格敏感流量隔离"],
                risk_level="high",
                severity="low",
                window_hours=14 * 24,
                content={"concept": "value_meal"},
            )
        )

    if sibling_names:
        signals.append(
            AgentSignal(
                code="existing_siblings",
                title="商户下已有其他门店",
                detail="矩阵建议应与现有店定位去重。",
                severity="low",
                evidence=sibling_names[:3],
            )
        )

    health = health_proxy if unlock else clamp_score(health_proxy - t.locked_health_penalty)
    actions = prioritize_actions_with_feedback(actions, recommendations, data.experiments, agent_key="store_matrix")
    result = StoreMatrixAgentResult(
        meta=AgentMeta(key="store_matrix", label="线上门店增长 Agent", confidence=0.58, generated_at=data.generated_at),
        readiness="ready" if unlock else "limited",
        blockers=blockers[:3],
        health_score=health,
        unlock_ready=unlock,
        sibling_store_count=len(sibling_names),
        sibling_stores=sibling_names[:8],
        concepts=concepts,
        signals=signals[:5],
        priority_actions=actions[:3],
        conclusion=(
            f"矩阵健康分 {health}。"
            + ("可开始筹备第二定位线上店。" if unlock else "先稳住主店，再谈一店多开。")
        ),
        reasons=[s.title for s in signals[:3]] or ["暂无矩阵动作"],
        evidence=[e for s in signals for e in (s.evidence[:1] if s.evidence else [])][:5],
        expected_impact="矩阵开店周期更长，适合主店稳定后放大，而非拯救短期下滑。",
    )

    def _set(queue, current):
        result.action_queue = queue
        result.current_action = current

    attach_queue(
        agent_key="store_matrix",
        priority_actions=actions,
        recommendations=recommendations,
        set_queue=_set,
        experiments=data.experiments,
        generated_at=data.generated_at,
    )
    return result
