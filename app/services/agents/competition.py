from __future__ import annotations
import math
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import (
    CompetitorMenuItem,
    CompetitorSnapshot,
    CompetitorStore,
    StoreCompetitorWatch,
)
from app.schemas.agents import CompetitionAgentResult, CompetitionChangeView, CompetitorBrief

from .types import _AgentContext
from .helpers import _agent_meta, _price_band
from .menu import _alignment_readiness, _document_blockers

def _distance_m(
    origin_lat: Optional[float],
    origin_lng: Optional[float],
    target_lat: Optional[float],
    target_lng: Optional[float],
) -> Optional[int]:
    if None in (origin_lat, origin_lng, target_lat, target_lng):
        return None
    earth_radius_m = 6_371_000
    lat1, lat2 = math.radians(origin_lat), math.radians(target_lat)
    delta_lat = math.radians(target_lat - origin_lat)
    delta_lng = math.radians(target_lng - origin_lng)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    return int(round(earth_radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))))

def _positioning(
    store_price_band: Optional[str],
    competitor_min: Optional[float],
    competitor_max: Optional[float],
) -> str:
    if not store_price_band or competitor_min is None or competitor_max is None:
        return "同商圈替代选择"
    store_low, store_high = (float(part) for part in store_price_band.split("-"))
    store_mid = (store_low + store_high) / 2
    competitor_mid = (competitor_min + competitor_max) / 2
    if competitor_mid <= store_mid * 0.85:
        return "低价快餐"
    if competitor_mid >= store_mid * 1.18:
        return "品质溢价"
    return "同价格带竞争"

def _latest_competitor_menu(db: Session, snapshot_id: str) -> list[CompetitorMenuItem]:
    stmt = (
        select(CompetitorMenuItem)
        .where(CompetitorMenuItem.snapshot_id == snapshot_id)
        .order_by(CompetitorMenuItem.rating.desc().nullslast(), CompetitorMenuItem.name)
    )
    return list(db.execute(stmt).scalars().all())

def _build_competition_agent(db: Session, ctx: _AgentContext) -> CompetitionAgentResult:
    store = ctx.store
    store_price_band = _price_band(ctx.menu_items)
    market_focus = list(ctx.store_state.market.market_type or [])
    primary_problem = ctx.store_state.primary_problem.type if ctx.store_state.primary_problem else None
    top_competitors: list[CompetitorBrief] = []

    watched_ids = list(
        db.execute(
            select(StoreCompetitorWatch.c_store_id).where(
                StoreCompetitorWatch.store_id == store.id,
                StoreCompetitorWatch.active.is_(True),
            )
        ).scalars()
    )
    competitor_stmt = (
        select(CompetitorStore)
        .where(CompetitorStore.id.in_(watched_ids))
        .limit(5)
    )
    competitors = db.execute(competitor_stmt).scalars().all()
    change_by_competitor: dict[str, list[Any]] = {}
    for change in ctx.store_state.competition_changes:
        change_by_competitor.setdefault(change.c_store_id, []).append(change)

    threat_signals: list[str] = []
    completeness_scores: list[float] = []
    for competitor in competitors:
        snapshot_stmt = (
            select(CompetitorSnapshot)
            .where(CompetitorSnapshot.c_store_id == competitor.id)
            .order_by(CompetitorSnapshot.captured_at.desc())
            .limit(1)
        )
        snapshot = db.execute(snapshot_stmt).scalar_one_or_none()
        competitor_menu = _latest_competitor_menu(db, snapshot.id) if snapshot else []
        distance_m = _distance_m(
            store.latitude,
            store.longitude,
            competitor.latitude,
            competitor.longitude,
        )
        category_overlap = 1.0 if competitor.category and store.merchant and competitor.category == store.merchant.category else 0.72
        if distance_m is None:
            location_overlap = 0.72 if competitor.area == store.area else 0.45
        elif distance_m <= 500:
            location_overlap = 1.0
        elif distance_m <= 1000:
            location_overlap = 0.88
        elif distance_m <= (store.delivery_radius_m or 2500):
            location_overlap = 0.72
        else:
            location_overlap = 0.42
        price_overlap = 0.65
        price_band = None
        if snapshot and snapshot.price_band_min is not None and snapshot.price_band_max is not None:
            price_band = f"{int(snapshot.price_band_min)}-{int(snapshot.price_band_max)}"
            if store_price_band:
                low, high = [int(part) for part in store_price_band.split("-")]
                overlap_low = max(low, int(snapshot.price_band_min))
                overlap_high = min(high, int(snapshot.price_band_max))
                price_overlap = 1.0 if overlap_low <= overlap_high else 0.45
        rating_strength = min(1.0, float(snapshot.rating) / 5.0) if snapshot and snapshot.rating else 0.62
        menu_strength = min(1.0, len(competitor_menu) / 12) if competitor_menu else 0.45
        score = int(
            round(
                100
                * (
                    0.30 * category_overlap
                    + 0.25 * price_overlap
                    + 0.25 * location_overlap
                    + 0.12 * rating_strength
                    + 0.08 * menu_strength
                )
            )
        )
        positioning = _positioning(
            store_price_band,
            snapshot.price_band_min if snapshot else None,
            snapshot.price_band_max if snapshot else None,
        )
        set_meals = [
            item
            for item in competitor_menu
            if any(token in item.name for token in ("套餐", "组合", "双人", "单人餐"))
        ]
        strengths: list[str] = []
        if price_overlap >= 1:
            strengths.append("价格带与本店高度重合")
        if snapshot and snapshot.rating and snapshot.rating >= 4.6:
            strengths.append("用户评分较高")
        if set_meals:
            strengths.append(f"套餐供给较完整（{len(set_meals)} 个）")
        if distance_m is not None and distance_m <= 800:
            strengths.append("距离近，配送客群重合")
        weaknesses: list[str] = []
        if snapshot and snapshot.rating and snapshot.rating < 4.5:
            weaknesses.append("评分承接偏弱")
        if len(competitor_menu) < 5:
            weaknesses.append("菜单选择较少")
        if not set_meals:
            weaknesses.append("套餐结构不明显")
        advantage = strengths[0] if strengths else "在同商圈形成直接替代选择"
        completeness_scores.append(
            sum(
                (
                    0.25,
                    0.20 if distance_m is not None else 0,
                    0.25 if snapshot else 0,
                    0.30 if competitor_menu else 0,
                )
            )
        )

        # recent moves come from real detected changes
        own_changes = change_by_competitor.get(competitor.id, [])
        if any(c.type == "price_down" for c in own_changes):
            recent_move = "近期主动调低了价格带，正在用价格抢单。"
            threat_signals.append(f"{competitor.name} 近期降价抢单")
        elif any(c.type == "price_up" for c in own_changes):
            recent_move = "近期上探更高价格带，正在抢中高端心智。"
            threat_signals.append(f"{competitor.name} 冲向中高端市场")
        elif any(c.type == "rating_up" for c in own_changes):
            recent_move = "评价近期回升，转化威胁上升。"
            threat_signals.append(f"{competitor.name} 口碑在回升")
        elif any(c.type == "rating_down" for c in own_changes):
            recent_move = "评价近期回落，口碑窗口正在打开。"
        elif any(c.type == "product_added" for c in own_changes):
            added = next(c for c in own_changes if c.type == "product_added")
            recent_move = added.summary
            threat_signals.append(added.summary)
        elif any(c.type == "image_changed" for c in own_changes):
            changed = next(c for c in own_changes if c.type == "image_changed")
            recent_move = changed.summary
            threat_signals.append(changed.summary)
        elif any(c.type == "product_price_changed" for c in own_changes):
            changed = next(c for c in own_changes if c.type == "product_price_changed")
            recent_move = changed.summary
            threat_signals.append(changed.summary)
        else:
            recent_move = "最近快照已更新，建议紧盯图文和套餐变化。"
        top_competitors.append(
            CompetitorBrief(
                competitor_id=competitor.id,
                name=competitor.name,
                score=max(35, min(96, score)),
                distance_m=distance_m,
                price_band=price_band,
                rating=snapshot.rating if snapshot else None,
                positioning=positioning,
                advantage=advantage,
                strengths=strengths[:3],
                weaknesses=weaknesses[:2],
                featured_products=[item.name for item in competitor_menu[:3]],
                menu_item_count=len(competitor_menu),
                set_meal_count=len(set_meals),
                recent_move=recent_move,
            )
        )

    top_competitors.sort(key=lambda row: row.score, reverse=True)
    changes = [
        CompetitionChangeView(type=row.type, summary=row.summary, price=row.price)
        for row in ctx.store_state.competition_changes[:3]
    ]

    competition_score = top_competitors[0].score if top_competitors else (78 if primary_problem == "store_ctr_down" else 66)
    if primary_problem == "store_ctr_down":
        conclusion = "当前更像是在第一眼竞争里输给了同商圈替代选项。"
        actions = [
            "先盯主图和标题的竞争力，再决定要不要动价格。",
            "优先看同价格带门店最近有没有上新套餐或改图。",
        ]
    else:
        conclusion = "当前竞争问题更偏承接能力，而不是单纯曝光不足。"
        actions = [
            "先核对套餐和评价短板，不要直接打折。",
            "先看同商圈高评分门店怎么做承接和搭配。",
        ]

    # 当检测到真实威胁信号时，把动作升级为更具体的应对
    pricedown = [c for c in ctx.store_state.competition_changes if c.type == "price_down"]
    rating_conflict_competitors = [c for c in ctx.store_state.competition_changes if c.type == "rating_up"]
    if pricedown:
        conclusion = f"有竞品（{pricedown[0].summary.split('近期')[0]}）正在用价格抢你的核心客群，第一眼竞争压力上升。"
        actions = [
            "不要跟着硬降价，先用套餐结构和图文价值感回击。",
            "把主推 SKU 的锚点提到竞品之上，用价值感而非低价应对。",
            "盯住该竞品近 72 小时的爆品与评价变化。",
        ]
    elif rating_conflict_competitors and primary_problem == "store_cvr_down":
        conclusion = f"有竞品（{rating_conflict_competitors[0].summary.split('近期')[0]}）口碑在回升，正在抢转化和连带订单。"
        actions = [
            "优先补套餐和评价回复，稳住转化承接。",
            "用真实分量/包装亮点对冲竞品口碑回升。",
            "将差评主题收敛成 1 个改进点，别分散动作。",
        ]

    reasons = [
        f"商圈聚焦：{' / '.join(market_focus) if market_focus else '同商圈、同价格带'}。",
        top_competitors[0].name + " 是当前最值得盯的竞品。" if top_competitors else "当前还没有竞品快照，先用商圈和价格带做保守判断。",
        changes[0].summary if changes else "暂无显式变更记录，优先补 competitor snapshot。",
    ]
    reasons = list(dict.fromkeys(reasons))[:3]
    blockers = _document_blockers(ctx)
    if not top_competitors:
        blockers.append("缺少同商圈竞品快照，当前竞争判断偏保守。")
    readiness = "ready" if top_competitors and _alignment_readiness(ctx) == "ready" else _alignment_readiness(ctx)
    confidence = (
        round(sum(completeness_scores) / len(completeness_scores), 2)
        if completeness_scores
        else 0.35
    )
    evidence = [
        f"资料对齐状态：{ctx.document_alignment.get('status')} / {ctx.document_alignment.get('alignment_score')} 分。",
        *reasons,
        *threat_signals[:2],
    ]

    return CompetitionAgentResult(
        meta=_agent_meta("competition", ctx.generated_at, confidence),
        readiness=readiness,
        blockers=list(dict.fromkeys(blockers))[:3],
        benchmark_group="同商圈 / 同价格带 / 同用户群",
        competition_score=competition_score,
        nearby_total=len(watched_ids) or len(top_competitors),
        market_focus=market_focus,
        top_competitors=top_competitors[:3],
        changes=changes,
        conclusion=conclusion,
        reasons=reasons[:3],
        evidence=list(dict.fromkeys(evidence))[:5],
        actions=actions[:3],
        expected_impact="预计降低同价格带竞品分流风险，并为后续 CTR/CVR 实验建立可验证基线。",
        threat_signals=threat_signals[:3],
    )
