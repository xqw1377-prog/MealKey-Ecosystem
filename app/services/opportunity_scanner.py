"""Opportunity Scanner — 外部找钱信号扫描（第 4 类触发）。

和 event_engine 的异常检测不同：这里扫描的是"现在不做也不会出事，
但做了能多赚钱"的外部机会信号。

信号来源（V1）：
- 平台活动窗口：promo agent unlock 且未参加午餐活动 → 补贴机会
- 竞品空档：竞品活动结束/停投 → 排名抢夺机会
- 时段未覆盖：菜单无夜宵但商圈有夜宵需求 → 新时段机会
- 价格带空档：商圈某价格带无竞品覆盖 → 蓝海价格带
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.opportunity import OpportunityTrigger
from app.services.agents import build_agent_context


def _now_hour() -> int:
    """当前小时（UTC，调用方可按需转时区）。"""
    return datetime.now(timezone.utc).hour


def scan_subsidy_opportunity(agents_payload) -> Optional[OpportunityTrigger]:
    """平台补贴机会：promo agent 检测到活动窗口但本店未参加。"""
    promo = getattr(agents_payload, "promo", None)
    if promo is None:
        return None
    # unlock_ready=True 说明自然转化稳定，可以参加活动
    # 但如果本店还没有套餐动作（launch_value_bundle_promo 在 actions 里），
    # 说明还没抓住补贴窗口
    if promo.unlock_ready and promo.health_score >= 70:
        has_bundle_action = any(
            a.action_type == "launch_value_bundle_promo" for a in promo.priority_actions
        )
        if has_bundle_action:
            return OpportunityTrigger(
                key="subsidy_lunch_window",
                type="subsidy_window",
                title="平台午餐补贴窗口开放，建议参与",
                detail="自然转化已稳定，平台午餐活动当前可解锁，参加可抢午餐排名。",
                expected_gain="预计 +8-15% 午餐订单",
                window="今天 11:00-13:00",
                recommended_action="join_lunch_campaign",
            )
    return None


def scan_competitor_gap(agents_payload) -> Optional[OpportunityTrigger]:
    """竞品空档：竞品活动结束或停投，本店有机会抢排名。"""
    competition = getattr(agents_payload, "competition", None)
    if competition is None:
        return None
    # 检查竞品变化里是否有"活动结束/停投"信号（type 可能没有，但 summary 会有）
    for change in (getattr(competition, "changes", None) or []):
        summary = (getattr(change, "summary", "") or "").lower()
        if any(kw in summary for kw in ("结束", "停投", "下架", "取消", "停止")):
            return OpportunityTrigger(
                key=f"competitor_gap:{getattr(change, 'c_store_id', 'unknown')}",
                type="competitor_gap",
                title="竞品活动结束，排名出现空档",
                detail=f"竞品{summary}，你的核心商品有机会抢回搜索排名。",
                expected_gain="预计 +5-10% 曝光与点击",
                recommended_action="boost_hero_item_ads",
            )
    return None


def scan_daypart_untapped(agents_payload, menu_items: list) -> Optional[OpportunityTrigger]:
    """时段未覆盖：菜单无夜宵但商圈有夜宵流量。"""
    has_night_food = any(
        any(kw in (item.get("name") or "") for kw in ("夜宵", "烧烤", "小龙虾", "啤酒"))
        for item in menu_items
    )
    store_matrix = getattr(agents_payload, "store_matrix", None)
    if not has_night_food and store_matrix and store_matrix.unlock_ready:
        # 主店稳定 + 菜单无夜宵 → 夜宵线上店机会
        return OpportunityTrigger(
            key="daypart_night_untapped",
            type="daypart_untapped",
            title="夜宵时段流量未被覆盖",
            detail="主店已稳定，但菜单无夜宵品类。商圈夜间流量可用第二线上店承接。",
            expected_gain="预计新增 10-20% 夜间订单",
            window="夜间 21:00-02:00",
            recommended_action="open_night_online_store",
        )
    return None


def scan_opportunities(db: Session, store_id: str, *, days: int = 7) -> list[OpportunityTrigger]:
    """扫描门店的所有外部找钱机会。"""
    # 复用 agent context（带缓存）
    from app.services.agent_context_cache import get_context

    ctx = get_context(db, store_id, days=days)
    if ctx is None:
        return []

    # 轻量级：只跑需要的几个 agent（promo/competition/store_matrix）
    triggers: list[OpportunityTrigger] = []

    # 构造一个轻量 agents 视图（不全跑 13 个）
    try:
        from app.services.agents import _build_one_agent

        # promo
        promo = _build_one_agent(db, ctx, "promo")
        if promo:
            t = scan_subsidy_opportunity(promo)
            if t:
                triggers.append(t)

        # competition
        competition = _build_one_agent(db, ctx, "competition")
        if competition:
            t = scan_competitor_gap(competition)
            if t:
                triggers.append(t)

        # store_matrix + menu
        store_matrix = _build_one_agent(db, ctx, "store_matrix")
        if store_matrix:
            # 构造一个临时命名空间让 scan_daypart_untapped 能读
            class _LightAgents:
                pass

            light = _LightAgents()
            light.store_matrix = store_matrix
            t = scan_daypart_untapped(light, ctx.menu_items)
            if t:
                triggers.append(t)
    except Exception:  # noqa: BLE001
        pass

    return triggers
