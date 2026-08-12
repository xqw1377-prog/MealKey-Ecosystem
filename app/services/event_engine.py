"""Event Engine: turn sensing deltas into operating events for the AI store manager.

V2 升级（对齐产品要求）：
- 量化影响：HERO_SKU_SOLD_OUT 真正算出"损失 N 单"，填 estimated_impact_amount；
- 补全 3 个缺失事件：ADS_ROI_DROP / IM_REPLY_DROP / COMPETITOR_NEW_PRODUCT；
- 区分 COMPETITOR_NEW_PRODUCT（新品） vs COMPETITOR_NEW_PROMOTION（活动/套餐）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.schemas.events import EventEngineResult, ManagerDecision, OperatingEvent
from app.schemas.store_state import StoreState


def _eid() -> str:
    return str(uuid.uuid4())


def _decide(severity: str, confidence: float) -> ManagerDecision:
    if severity in {"critical", "high"} and confidence >= 0.65:
        return "alert_owner" if severity == "critical" else "handle_today"
    if severity == "medium":
        return "handle_today" if confidence >= 0.7 else "record"
    if severity == "low":
        return "record"
    return "ignore"


# 步骤 4：5 种 AI 行为决策
# action_type → 是否需要线下操作 + 风险等级
_NEEDS_ASSIST_ACTIONS = {
    "refresh_hero_image",      # 需要老板拍照
    "refresh_signature_card",  # 需要老板拍照
    "change_main_image",       # 需要老板提供新图
    "open_lunch_online_store", # 需要老板传资质
    "open_night_online_store",
    "open_value_online_store",
    "escalate_unfair_review",  # 需要老板确认申诉内容
}

_AUTO_HANDLE_ACTIONS = {
    "batch_reply_negative_reviews",   # AI 可以自动回复
    "publish_service_reply_scripts",  # AI 可以生成话术
    "pin_positive_review_themes",     # AI 可以置顶
}

_NEEDS_CONFIRM_ACTIONS = {
    "change_title", "add_set_meal", "adjust_price_value",
    "boost_hero_item_ads", "shift_ads_to_high_cvr_item", "pause_broad_ads",
    "join_lunch_campaign", "launch_value_bundle_promo", "match_competitor_promo",
    "fix_top_review_theme", "menu_patch", "menu_cleanup", "store_discount",
    "recall_churn_risk_users", "nurture_new_customers",
}


def _decide_ai_action(
    event_type: str,
    severity: str,
    confidence: float,
    recommended_agent: str | None,
) -> str:
    """5 种 AI 行为决策。

    核心原则：AI 真正高级不是天天找老板，而是知道什么时候别烦你。
    """
    # 结果型事件：只告诉老板，不需要他做事
    if event_type in {"OPPORTUNITY_DETECTED"} and confidence < 0.6:
        return "silent_observe"

    # 低置信度/弱信号：静默观察
    if confidence < 0.55:
        return "silent_observe"

    # critical 异常（闭店）：必须让老板知道并协助
    if severity == "critical":
        return "need_assist"

    # 根据推荐 agent 判断动作类型
    # service 类（回复评价/话术）：AI 自己做
    if recommended_agent == "service":
        return "auto_handle"

    # review 类：评价治理 AI 可以自动回复，申诉需要老板确认
    if recommended_agent == "review":
        return "auto_handle"

    # 高严重度 + 需要 CTR/CVR 动作：让老板确认
    if severity in {"high"} and recommended_agent in {"storefront", "product", "menu"}:
        return "need_confirm"  # 换主图/改标题/补套餐需要老板确认或协助

    # 中等严重度：AI 可以准备方案，但执行让老板确认
    if severity == "medium":
        if recommended_agent in {"promo", "ads"}:
            return "need_confirm"  # 活动/投流需要老板确认花钱
        return "silent_observe"  # 其他中等信号先观察

    return "silent_observe"


# ---------------------------------------------------------------------------
# 量化影响估算（步骤 1 核心）
# ---------------------------------------------------------------------------


def _daily_orders(state: StoreState) -> Optional[float]:
    """取当前窗口的总订单量（日均）。"""
    orders_kpi = state.kpis.get("orders")
    if orders_kpi is None:
        return None
    value = getattr(orders_kpi, "observed_value", None)
    return float(value) if value is not None else None


def _estimate_hero_sku_loss(state: StoreState) -> tuple[Optional[float], Optional[str], Optional[str]]:
    """估算核心商品售罄的损失。

    返回 (损失单量, hero 商品名, 文案)。
    逻辑：(1 - 在售率) × 日订单 × 贡献占比。
    """
    in_stock_rate = state.platform_health.hero_sku_in_stock_rate
    if in_stock_rate is None:
        return None, None, None
    daily = _daily_orders(state)
    if daily is None or daily <= 0:
        return None, None, None
    # 找贡献最高的核心商品
    hero = None
    hero_share = 0.0
    for item in (state.core_items or []):
        share = getattr(item, "order_share_pct", None) or 0
        if share > hero_share:
            hero_share = share
            hero = item
    sold_out_ratio = max(0.0, 1.0 - in_stock_rate)
    if hero is not None and hero_share > 0:
        # 有单品贡献数据：算这个单品的损失
        loss = round(daily * sold_out_ratio * (hero_share / 100.0))
        name = getattr(hero, "name", "核心商品")
        text = f"{name}贡献约{hero_share:.0f}%订单，在售率{in_stock_rate:.0%}，预计今日损失约{int(loss)}单"
        return float(loss), name, text
    # 无单品数据：用聚合估算
    loss = round(daily * sold_out_ratio * 0.28)  # 默认假设核心商品占 28%
    return float(loss), None, f"核心商品在售率{in_stock_rate:.0%}，预计今日损失约{int(loss)}单"


def _estimate_metric_loss(state: StoreState, delta_pct: float, metric_label: str) -> Optional[float]:
    """估算 CTR/CVR 下跌带来的订单损失。"""
    daily = _daily_orders(state)
    if daily is None or daily <= 0:
        return None
    # 影响量 = 日订单 × |delta%| / 100 × 转化传导系数（CTR 传导约 0.6，CVR 直接 1.0）
    coefficient = 0.6 if "点击" in metric_label or "ctr" in metric_label.lower() else 1.0
    loss = round(daily * abs(delta_pct) / 100.0 * coefficient)
    return float(loss) if loss > 0 else None


def _estimate_store_closed_loss(state: StoreState) -> Optional[float]:
    """估算异常闭店的损失（按半天计）。"""
    daily = _daily_orders(state)
    if daily is None or daily <= 0:
        return None
    return round(daily * 0.5)  # 假设闭店影响半天


def _estimate_activity_loss(state: StoreState) -> Optional[float]:
    """估算活动失效的损失（按活动贡献 15% 计）。"""
    daily = _daily_orders(state)
    if daily is None or daily <= 0:
        return None
    return round(daily * 0.15)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


def build_operating_events(state: StoreState, *, generated_at: Optional[datetime] = None) -> EventEngineResult:
    now = generated_at or datetime.now(timezone.utc)
    events: list[OperatingEvent] = []

    ctr = state.kpis.get("ctr")
    cvr = state.kpis.get("cvr")
    if ctr and ctr.delta_pct is not None and ctr.delta_pct <= -5:
        severity = "high" if ctr.delta_pct <= -10 else "medium"
        loss = _estimate_metric_loss(state, ctr.delta_pct, "点击率")
        impact_text = "第一眼吸引力下降，可能拖累订单"
        if loss:
            impact_text = f"CTR 较基线{ctr.delta_pct:.1f}%，预计今日损失约{int(loss)}单"
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type="CTR_DROP",
                title="点击率下降",
                detail=f"CTR 较基线 {ctr.delta_pct:.1f}%",
                severity=severity,
                detected_at=now,
                affected_metric="ctr",
                estimated_impact=impact_text,
                estimated_impact_amount=loss,
                confidence=0.82,
                recommended_agent="storefront",
                manager_decision=_decide(severity, 0.82),
                evidence=[f"ctr_delta={ctr.delta_pct:.1f}%"],
            )
        )
    if cvr and cvr.delta_pct is not None and cvr.delta_pct <= -5:
        severity = "high" if cvr.delta_pct <= -10 else "medium"
        loss = _estimate_metric_loss(state, cvr.delta_pct, "转化率")
        impact_text = "进店后成交变弱"
        if loss:
            impact_text = f"CVR 较基线{cvr.delta_pct:.1f}%，预计今日损失约{int(loss)}单"
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type="CVR_DROP",
                title="转化率下降",
                detail=f"CVR 较基线 {cvr.delta_pct:.1f}%",
                severity=severity,
                detected_at=now,
                affected_metric="cvr",
                estimated_impact=impact_text,
                estimated_impact_amount=loss,
                confidence=0.8,
                recommended_agent="product",
                manager_decision=_decide(severity, 0.8),
                evidence=[f"cvr_delta={cvr.delta_pct:.1f}%"],
            )
        )

    if state.profit.take_home_rate_delta_pct is not None and state.profit.take_home_rate_delta_pct <= -8:
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type="TAKE_RATE_DROP",
                title="到手率下滑",
                detail=f"到手率变化 {state.profit.take_home_rate_delta_pct:.1f}%",
                severity="high",
                detected_at=now,
                affected_metric="take_home_rate",
                estimated_impact="增长动作可能在买流水",
                confidence=0.75,
                recommended_agent="promo",
                manager_decision="handle_today",
                evidence=[state.profit.judgment],
            )
        )

    # ADS_ROI_DROP（步骤 2 新增）：投流花了钱但订单没涨
    ads_spend = getattr(state.profit, "ads_spend", None)
    if ads_spend and ads_spend > 0:
        orders_kpi = state.kpis.get("orders")
        orders_delta = getattr(orders_kpi, "delta_pct", None) if orders_kpi else None
        if orders_delta is not None and orders_delta <= 0:
            severity = "high" if ads_spend > 200 else "medium"
            events.append(
                OperatingEvent(
                    id=_eid(),
                    store_id=state.store.store_id,
                    event_type="ADS_ROI_DROP",
                    title="投流ROI下滑",
                    detail=f"广告消耗¥{ads_spend:.0f}，但订单{orders_delta:.1f}%",
                    severity=severity,
                    detected_at=now,
                    affected_metric="ads_roi",
                    estimated_impact=f"广告花了¥{ads_spend:.0f}但订单未增长，可能亏损投流",
                    confidence=0.78,
                    recommended_agent="ads",
                    manager_decision=_decide(severity, 0.78),
                    evidence=[f"ads_spend={ads_spend}", f"orders_delta={orders_delta:.1f}%"],
                )
            )

    # IM_REPLY_DROP（步骤 2 新增）：回复率低于 60%
    im_reply = state.platform_health.im_reply_rate
    if im_reply is not None and im_reply < 0.6:
        severity = "high" if im_reply < 0.4 else "medium"
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type="IM_REPLY_DROP",
                title="IM回复率偏低",
                detail=f"当前回复率 {im_reply:.0%}",
                severity=severity,
                detected_at=now,
                affected_metric="im_reply_rate",
                estimated_impact="回复不及时影响店铺权重与转化",
                confidence=0.72,
                recommended_agent="service",
                manager_decision=_decide(severity, 0.72),
                evidence=[f"im_reply_rate={im_reply:.2f}"],
            )
        )

    if state.platform_health.store_rating is not None and state.platform_health.store_rating < 4.5:
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type="RATING_DROP",
                title="店铺评分承压",
                detail=f"当前评分 {state.platform_health.store_rating:.2f}",
                severity="medium",
                detected_at=now,
                affected_metric="rating",
                estimated_impact="可能影响排名与转化",
                confidence=0.7,
                recommended_agent="review",
                manager_decision="handle_today",
                evidence=[state.platform_health.judgment],
            )
        )

    # HERO_SKU_SOLD_OUT（步骤 1 量化影响）
    if state.platform_health.hero_sku_in_stock_rate is not None and state.platform_health.hero_sku_in_stock_rate < 0.95:
        loss, hero_name, impact_text = _estimate_hero_sku_loss(state)
        title = f"核心商品售罄风险" if hero_name else "核心商品在售不稳"
        if hero_name:
            title = f"{hero_name}可能售罄"
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type="HERO_SKU_SOLD_OUT",
                title=title,
                detail=f"核心商品在售率 {state.platform_health.hero_sku_in_stock_rate:.0%}",
                severity="high",
                detected_at=now,
                affected_metric="orders",
                estimated_impact=impact_text or "午高峰售罄会直接损失订单与排名",
                estimated_impact_amount=loss,
                confidence=0.72,
                recommended_agent="menu",
                manager_decision="alert_owner",
                evidence=[f"hero_sku_in_stock_rate={state.platform_health.hero_sku_in_stock_rate:.2f}"],
            )
        )

    # ACTIVITY_EXPIRING（步骤 1 量化影响）
    if state.platform_health.activity_valid is False:
        loss = _estimate_activity_loss(state)
        impact_text = "活动空窗期可能掉单"
        if loss:
            impact_text = f"活动失效，预计损失约{int(loss)}单"
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type="ACTIVITY_EXPIRING",
                title="活动失效或即将到期",
                detail="检测到活动有效状态异常",
                severity="medium",
                detected_at=now,
                affected_metric="orders",
                estimated_impact=impact_text,
                estimated_impact_amount=loss,
                confidence=0.68,
                recommended_agent="promo",
                manager_decision="handle_today",
            )
        )

    # STORE_ABNORMAL_CLOSED（步骤 1 量化影响）
    if state.platform_health.open_status == "closed":
        loss = _estimate_store_closed_loss(state)
        impact_text = "营业损失与排名下降"
        if loss:
            impact_text = f"闭店预计损失约{int(loss)}单/半天"
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type="STORE_ABNORMAL_CLOSED",
                title="异常闭店",
                detail="营业状态为关闭",
                severity="critical",
                detected_at=now,
                affected_metric="orders",
                estimated_impact=impact_text,
                estimated_impact_amount=loss,
                confidence=0.9,
                recommended_agent="diagnosis",
                manager_decision="alert_owner",
            )
        )

    # 竞品变化：区分 NEW_PRODUCT vs NEW_PROMOTION vs PRICE_CHANGE（步骤 2）
    for change in state.competition_changes[:5]:
        summary = change.summary or ""
        is_promo = any(kw in summary for kw in ("套餐", "活动", "满减", "补贴", "促销"))
        is_new_product = change.type == "menu_added" and any(kw in summary for kw in ("新品", "新上", "新增"))
        if is_new_product:
            event_type = "COMPETITOR_NEW_PRODUCT"
            title = "竞品上新"
        elif is_promo:
            event_type = "COMPETITOR_NEW_PROMOTION"
            title = "竞品新活动"
        elif change.type in {"price_down"}:
            event_type = "COMPETITOR_PRICE_CHANGE"
            title = "竞品降价"
        elif change.type in {"menu_added"}:
            event_type = "COMPETITOR_NEW_PRODUCT"
            title = "竞品上新"
        else:
            continue
        events.append(
            OperatingEvent(
                id=_eid(),
                store_id=state.store.store_id,
                event_type=event_type,
                title=title,
                detail=summary,
                severity="medium",
                detected_at=now,
                affected_metric="orders",
                estimated_impact="可能分流点击与订单",
                confidence=0.66,
                recommended_agent="competition",
                manager_decision="record",
                evidence=[summary],
            )
        )

    # Sort: alert > today > record
    rank = {"alert_owner": 0, "handle_today": 1, "record": 2, "ignore": 3}
    events.sort(key=lambda e: (rank.get(e.manager_decision or "record", 9), e.severity))

    for idx, event in enumerate(events):
        ai_action = _decide_ai_action(
            event.event_type, event.severity, event.confidence, event.recommended_agent
        )
        events[idx] = event.model_copy(
            update={
                "fingerprint": f"{event.event_type}|{event.affected_metric or ''}|{event.title}",
                "ai_action": ai_action,
            }
        )

    handle_today = sum(1 for e in events if e.manager_decision == "handle_today")
    alerts = sum(1 for e in events if e.manager_decision == "alert_owner")
    open_count = sum(1 for e in events if e.status == "open")
    summary = (
        f"MealKey 今天发现 {handle_today + alerts} 个你需要处理的异常。"
        if (handle_today + alerts)
        else "今日暂无必须立刻处理的异常。"
    )
    return EventEngineResult(
        store_id=state.store.store_id,
        generated_at=now,
        events=events,
        open_count=open_count,
        handle_today_count=handle_today,
        alert_count=alerts,
        summary=summary,
    )
