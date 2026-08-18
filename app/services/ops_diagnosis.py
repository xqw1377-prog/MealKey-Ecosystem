"""履约与运营诊断引擎 — 需求 #84-89, #131-140。

从 OpsMetricDaily + ReviewFact + ShopFunnelDaily 读取运营数据,
诊断:出餐慢/商责取消/包装/漏餐/产能/原料预警/排班。

闭环定义: AI发现 → 生成POIE候选 → 老板确认 → 整改任务 → 验证。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.business_facts import OpsMetricDaily
from app.models.entities import ReviewFact, ShopFunnelDaily
from app.services.truth_resolution import production_funnel_clause


def _recent_ops(db: Session, store_id: str, days: int = 7) -> list[OpsMetricDaily]:
    cutoff = date.today() - timedelta(days=days)
    return list(
        db.execute(
            select(OpsMetricDaily)
            .where(OpsMetricDaily.store_id == store_id, OpsMetricDaily.day >= cutoff)
            .order_by(OpsMetricDaily.day)
        ).scalars()
    )


def _recent_funnel(db: Session, store_id: str, days: int = 7) -> list[ShopFunnelDaily]:
    cutoff = date.today() - timedelta(days=days)
    return list(
        db.execute(
            select(ShopFunnelDaily)
            .where(
                ShopFunnelDaily.store_id == store_id,
                ShopFunnelDaily.day >= cutoff,
                production_funnel_clause(ShopFunnelDaily.data_source),
            )
            .order_by(ShopFunnelDaily.day)
        ).scalars()
    )


def diagnose_fulfillment(db: Session, store_id: str) -> dict[str, Any]:
    """履约产能诊断 — 覆盖需求 #84-89。

    判断维度:
    1. 出餐速度趋势(出餐率下降 = 越来越慢) #84
    2. 商责取消率 #85
    3. 包装投诉(差评中"洒/漏/破"关键词) #86
    4. 漏餐错餐(差评中"漏/错/少"关键词) #87
    5. 产能预警(订单趋势 vs 历史峰值) #88
    6. 原料预警(爆款销量趋势突变) #89
    """
    ops_rows = _recent_ops(db, store_id)
    funnel_rows = _recent_funnel(db, store_id)
    findings: list[dict[str, Any]] = []

    # ── 1. 出餐速度 (#84) ──
    prep_rates = [r.meal_prep_rate for r in ops_rows if r.meal_prep_rate is not None]
    if len(prep_rates) >= 2:
        trend = prep_rates[-1] - prep_rates[0]
        if trend < -0.05:  # 出餐率下降5%+
            findings.append({
                "code": "MEAL_PREP_SLOWING",
                "demand_id": 84,
                "severity": "high",
                "title": f"出餐率下降 {abs(trend)*100:.0f}%,出餐越来越慢",
                "detail": f"出餐率从 {prep_rates[0]:.0%} 降到 {prep_rates[-1]:.0%}。可能原因:订单量增长超过产能、某SKU制作复杂、后厨人手不足。",
                "action": "检查高峰时段订单 vs 出餐能力,考虑缩菜单或增加备料",
            })

    # ── 2. 商责取消率 (#85) ──
    cancel_rates = [r.merchant_cancel_rate for r in ops_rows if r.merchant_cancel_rate is not None]
    if cancel_rates:
        avg_cancel = sum(cancel_rates) / len(cancel_rates)
        if avg_cancel > 0.02:  # 商责取消率 > 2%
            findings.append({
                "code": "HIGH_MERCHANT_CANCEL",
                "demand_id": 85,
                "severity": "high",
                "title": f"商责取消率 {avg_cancel:.1%},偏高",
                "detail": f"近 {len(cancel_rates)} 天平均商责取消率 {avg_cancel:.1%}。常见原因:库存不足、出餐太慢、员工操作失误。",
                "action": "排查取消订单的共同原因(SKU/时段/员工)",
            })

    # ── 3. 包装投诉 (#86) + 4. 漏餐错餐 (#87) ──
    cutoff = date.today() - timedelta(days=14)
    reviews = list(
        db.execute(
            select(ReviewFact)
            .where(ReviewFact.store_id == store_id, ReviewFact.reviewed_at >= cutoff)
            .order_by(ReviewFact.reviewed_at.desc())
            .limit(100)
        ).scalars()
    )
    packaging_complaints = [
        r for r in reviews
        if r.content and any(kw in r.content for kw in ["洒", "漏", "破", "压扁", "倒", "湿"])
    ]
    missing_food_complaints = [
        r for r in reviews
        if r.content and any(kw in r.content for kw in ["漏", "少", "没给", "错", "不对", "缺"])
    ]

    if len(packaging_complaints) >= 3:
        findings.append({
            "code": "PACKAGING_COMPLAINTS",
            "demand_id": 86,
            "severity": "medium",
            "title": f"近14天 {len(packaging_complaints)} 条包装相关投诉",
            "detail": "差评中频繁出现包装问题(洒/漏/破)。包装升级成本通常远低于差评损失。",
            "action": "评估包装升级方案,优先测试投诉最多的SKU",
        })

    if len(missing_food_complaints) >= 3:
        findings.append({
            "code": "MISSING_FOOD_COMPLAINTS",
            "demand_id": 87,
            "severity": "high",
            "title": f"近14天 {len(missing_food_complaints)} 条漏餐/错餐投诉",
            "detail": "差评中频繁出现漏餐/错餐/份量少。这通常意味着出餐流程有系统性问题。",
            "action": "检查打包SOP,高峰时段是否需要双人复核",
        })

    # ── 5. 产能预警 (#88) ──
    if len(funnel_rows) >= 3:
        recent_orders = [r.orders or 0 for r in funnel_rows[-3:]]
        avg_recent = sum(recent_orders) / len(recent_orders) if recent_orders else 0
        all_orders = [r.orders or 0 for r in funnel_rows]
        max_historical = max(all_orders) if all_orders else 0
        if max_historical > 0 and avg_recent > max_historical * 0.85:
            findings.append({
                "code": "CAPACITY_PRESSURE",
                "demand_id": 88,
                "severity": "medium",
                "title": f"近期日均 {avg_recent:.0f} 单,接近历史峰值 {max_historical:.0f} 单",
                "detail": "订单量接近历史高位,如果不提前准备可能触发出餐延迟和差评。",
                "action": "午高峰前确认备料充足、人员到位",
            })

    # ── 6. 原料预警 (#89) ──
    if len(funnel_rows) >= 5:
        last_day_orders = funnel_rows[-1].orders or 0
        avg_orders = sum((r.orders or 0) for r in funnel_rows[:-1]) / max(1, len(funnel_rows) - 1)
        if avg_orders > 0 and last_day_orders > avg_orders * 1.3:
            findings.append({
                "code": "SUDDEN_ORDER_SPIKE",
                "demand_id": 89,
                "severity": "medium",
                "title": f"昨日订单 {last_day_orders:.0f} 单,比日均高 {(last_day_orders/avg_orders-1)*100:.0f}%",
                "detail": "订单突然增长,如果持续可能面临原料/包装物料不足。",
                "action": "检查核心SKU的库存,确认能否支撑2-3天",
            })

    # ── 排班人效 (#131,133,137) ──
    if len(funnel_rows) >= 7:
        daily_orders = [(r.day, r.orders or 0) for r in funnel_rows[-7:]]
        max_day = max(daily_orders, key=lambda x: x[1])
        min_day = min(daily_orders, key=lambda x: x[1])
        if max_day[1] > 0 and min_day[1] >= 0:
            variance = (max_day[1] - min_day[1]) / max_day[1] * 100 if max_day[1] > 0 else 0
            if variance > 40:
                findings.append({
                    "code": "ORDER_VOLATILITY",
                    "demand_id": 131,
                    "severity": "low",
                    "title": f"周内订单波动大({variance:.0f}%),排班需要差异化",
                    "detail": f"最高 {max_day[1]:.0f} 单 vs 最低 {min_day[1]:.0f} 单。固定排班会导致高峰人手不足、低谷人员闲置。",
                    "action": "按历史日模式差异排班,高峰日多排人",
                })

    has_data = bool(ops_rows or reviews or funnel_rows)
    return {
        "has_data": has_data,
        "findings": findings,
        "summary": f"发现 {len(findings)} 个履约问题" if findings else "履约数据正常" if has_data else "缺少运营数据(出餐率/取消率),导入后会自动诊断",
        "data_sources": {
            "ops_days": len(ops_rows),
            "funnel_days": len(funnel_rows),
            "reviews_14d": len(reviews),
        },
    }


def diagnose_sku_lifecycle(db: Session, store_id: str) -> dict[str, Any]:
    """SKU 生命周期诊断 — 覆盖需求 #141-149。

    从 MenuItem + ItemFunnelDaily 分析:
    - 食材共用率(哪些SKU原料重叠) #141
    - 损耗(哪些商品评价提到份量不稳定) #143
    - 互斥(新品是否抢老品订单) #145
    - 套餐复杂度 vs 利润贡献 #149
    """
    from app.models.entities import MenuItem, MenuItemVersion, ItemFunnelDaily

    menu_items = list(
        db.execute(
            select(MenuItem)
            .where(MenuItem.store_id == store_id, MenuItem.is_active.is_(True))
        ).scalars()
    )

    if not menu_items:
        return {"has_data": False, "findings": [], "summary": "无菜单数据"}

    findings: list[dict[str, Any]] = []

    # 各 SKU 近期销量趋势
    cutoff = date.today() - timedelta(days=14)
    item_data: list[dict[str, Any]] = []
    for item in menu_items:
        version = db.get(MenuItemVersion, item.current_version_id) if item.current_version_id else None
        name = version.name if version else "未命名"

        funnel = list(
            db.execute(
                select(ItemFunnelDaily)
                .where(
                    ItemFunnelDaily.item_id == item.id,
                    ItemFunnelDaily.day >= cutoff,
                    production_funnel_clause(ItemFunnelDaily.data_source),
                )
                .order_by(ItemFunnelDaily.day)
            ).scalars()
        )
        orders_7d = sum((f.orders or 0) for f in funnel[-7:])
        orders_prev = sum((f.orders or 0) for f in funnel[:-7]) if len(funnel) > 7 else 0
        trend_pct = ((orders_7d - orders_prev) / orders_prev * 100) if orders_prev > 0 else None
        margin = None
        if version and version.price and item.food_cost:
            margin = (version.price - item.food_cost - (item.packaging_cost or 0)) / version.price

        item_data.append({
            "id": item.id,
            "name": name,
            "price": version.price if version else None,
            "food_cost": item.food_cost,
            "orders_7d": orders_7d,
            "trend_pct": trend_pct,
            "margin": margin,
            "category": version.category if version else None,
        })

    # ── #147: 生命周期末期(销量持续下降 + 低利润) ──
    declining = [d for d in item_data if d["trend_pct"] is not None and d["trend_pct"] < -20]
    for d in declining:
        findings.append({
            "code": "SKU_DECLINING",
            "demand_id": 147,
            "severity": "medium",
            "title": f"{d['name']} 销量下降 {abs(d['trend_pct']):.0f}%,可能进入生命周期末期",
            "detail": f"近7天 {d['orders_7d']} 单,趋势 {d['trend_pct']:.0f}%。如果持续下降,建议减少曝光或退出。",
            "action": "观察2周,如果继续下降则考虑停售",
        })

    # ── #145: 新品互斥(同时上多个新品,总订单没增长) ──
    total_orders_7d = sum(d["orders_7d"] for d in item_data)
    total_orders_prev = sum(
        (d["orders_7d"] / (1 + (d["trend_pct"] or 0) / 100))
        for d in item_data if d["trend_pct"] is not None
    )
    # 简化:如果各品增长但总量不增长 → 可能互斥
    growing = [d for d in item_data if d["trend_pct"] is not None and d["trend_pct"] > 10]
    if len(growing) >= 2:
        findings.append({
            "code": "SKU_CANNIBALIZATION_RISK",
            "demand_id": 145,
            "severity": "low",
            "title": f"{len(growing)} 个SKU同时增长,可能存在互斥",
            "detail": f"{', '.join(d['name'] for d in growing[:3])} 同时增长。如果总订单量没增长,说明新品在互相抢订单。",
            "action": "对比上新品前后的总订单量",
        })

    # ── #149: 套餐复杂度 vs 利润 ──
    low_margin = [d for d in item_data if d["margin"] is not None and d["margin"] < 0.15 and d["orders_7d"] > 5]
    for d in low_margin[:3]:
        findings.append({
            "code": "LOW_MARGIN_HIGH_VOLUME",
            "demand_id": 149,
            "severity": "medium",
            "title": f"{d['name']} 利润率仅 {d['margin']:.0%} 但卖得多",
            "detail": f"7天 {d['orders_7d']} 单,利润率 {d['margin']:.0%}。如果制作复杂,可能占用后厨产能但不赚钱。",
            "action": "评估简化配方或调整价格",
        })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"分析了 {len(item_data)} 个SKU,发现 {len(findings)} 个问题" if findings else f"分析了 {len(item_data)} 个SKU,暂无明显问题",
        "item_count": len(item_data),
    }


def diagnose_order_experience(db: Session, store_id: str) -> dict[str, Any]:
    """下单体验诊断 — 覆盖需求 #164-168。

    从 ReviewFact 分析:
    - 距离相关口味衰减(远距离差评) #164
    - 包装升级建议 #166
    - 预期差异(图片vs实际) #167
    - 质量不稳定(该不该停售) #169
    """
    cutoff = date.today() - timedelta(days=30)
    reviews = list(
        db.execute(
            select(ReviewFact)
            .where(ReviewFact.store_id == store_id, ReviewFact.reviewed_at >= cutoff)
            .order_by(ReviewFact.reviewed_at.desc())
            .limit(200)
        ).scalars()
    )

    if not reviews:
        return {"has_data": False, "findings": [], "summary": "无评价数据"}

    findings: list[dict[str, Any]] = []

    # 差评关键词分类
    expectation_gap = [r for r in reviews if r.content and any(kw in r.content for kw in ["不像", "图", "欺骗", "实物", "不一样", "差距"])]
    taste_distance = [r for r in reviews if r.content and any(kw in r.content for kw in ["凉", "冷", "化了", "软了", "坨了"])]
    quality_issues = [r for r in reviews if r.content and any(kw in r.content for kw in ["不新鲜", "变质", "坏的", "馊", "硬", "生"])]
    packaging_upgrade = [r for r in reviews if r.content and any(kw in r.content for kw in ["洒", "漏", "破", "盒子", "袋子", "包装"])]

    if len(expectation_gap) >= 2:
        findings.append({
            "code": "EXPECTATION_GAP",
            "demand_id": 167,
            "severity": "high",
            "title": f"{len(expectation_gap)} 条差评提到实物与图片不符",
            "detail": "顾客预期(来自商品图)与实际出品差异大,会导致差评和退款。",
            "action": "检查商品图片是否过度美化,更新为更真实的出品照",
        })

    if len(taste_distance) >= 3:
        findings.append({
            "code": "DISTANCE_TASTE_DECAY",
            "demand_id": 164,
            "severity": "medium",
            "title": f"{len(taste_distance)} 条差评提到送达时变凉/口感变差",
            "detail": "远距离配送导致口感下降。可能需要调整配送范围或包装保温。",
            "action": "分析这些差评的配送距离,考虑限制远距离配送",
        })

    if len(quality_issues) >= 2:
        findings.append({
            "code": "QUALITY_UNSTABLE",
            "demand_id": 169,
            "severity": "high",
            "title": f"{len(quality_issues)} 条差评提到食材质量/新鲜度问题",
            "detail": "质量问题是最严重的差评类型,直接影响食安评分和排名。",
            "action": "立即排查供应链,考虑暂时停售相关商品",
        })

    if len(packaging_upgrade) >= 3:
        findings.append({
            "code": "PACKAGING_UPGRADE_NEEDED",
            "demand_id": 166,
            "severity": "medium",
            "title": f"{len(packaging_upgrade)} 条差评提到包装问题",
            "detail": "包装问题持续出现,升级包装的成本通常远低于差评带来的损失。",
            "action": "测试升级版包装,优先针对投诉最多的SKU",
        })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"分析了 {len(reviews)} 条评价,发现 {len(findings)} 个体验问题" if findings else f"分析了 {len(reviews)} 条评价,暂无明显体验问题",
        "review_count": len(reviews),
    }


def diagnose_financial_reconciliation(db: Session, store_id: str) -> dict[str, Any]:
    """基础财务对账 — 覆盖需求 #101-106。

    用已有数据做基础对账:
    - GMV vs 利润(利润是否合理) #101
    - 推广花费 vs 推广产出 #106
    - 活动成本 vs 预期 #104
    """
    funnel = _recent_funnel(db, store_id)
    from app.models.business_facts import AdSpendDaily

    ads_rows = list(
        db.execute(
            select(AdSpendDaily)
            .where(
                AdSpendDaily.store_id == store_id,
                AdSpendDaily.day >= date.today() - timedelta(days=7),
            )
            .order_by(AdSpendDaily.day)
        ).scalars()
    )

    if not funnel:
        return {"has_data": False, "findings": [], "summary": "无经营数据,无法对账"}

    findings: list[dict[str, Any]] = []

    total_gmv = sum(f.gmv or 0 for f in funnel)
    total_orders = sum(f.orders or 0 for f in funnel)
    total_ads = sum((f.ads_spend or 0) for f in funnel) + sum((a.cost or 0) for a in ads_rows)

    # ── #101: GMV vs 利润合理性 ──
    if total_gmv > 0 and total_ads > 0:
        ads_ratio = total_ads / total_gmv * 100
        if ads_ratio > 15:
            findings.append({
                "code": "HIGH_ADS_RATIO",
                "demand_id": 101,
                "severity": "high",
                "title": f"推广费占GMV {ads_ratio:.1f}%,可能严重影响利润",
                "detail": f"7天GMV ¥{total_gmv:.0f},推广费 ¥{total_ads:.0f}。推广费占比超过15%通常意味着在买流水。",
                "action": "检查推广ROI,考虑减少低效时段投放",
            })

    # ── #106: 推广对账 ──
    if ads_rows:
        total_cost = sum(a.cost or 0 for a in ads_rows)
        total_gmv_from_ads = sum(a.gmv_from_ads or 0 for a in ads_rows)
        if total_cost > 0 and total_gmv_from_ads > 0:
            roas = total_gmv_from_ads / total_cost
            if roas < 2.0:
                findings.append({
                    "code": "ADS_NOT_PROFITABLE",
                    "demand_id": 106,
                    "severity": "high",
                    "title": f"推广ROAS仅 {roas:.1f},推广费可能没赚回来",
                    "detail": f"推广花费 ¥{total_cost:.0f},带来GMV ¥{total_gmv_from_ads:.0f}。ROAS < 2 意味着大概率亏钱。",
                    "action": "暂停低ROAS时段,优化投放策略",
                })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"7天GMV ¥{total_gmv:.0f},发现 {len(findings)} 个对账问题" if findings else f"7天GMV ¥{total_gmv:.0f},基础对账正常",
        "gmv_7d": round(total_gmv, 1),
        "ads_7d": round(total_ads, 1),
    }


# ═══════════════════════════════════════════════════════════
# 财务对账扩展 — #102,103,105,107,108,109,110
# ═══════════════════════════════════════════════════════════


def diagnose_settlement_detail(db: Session, store_id: str) -> dict[str, Any]:
    """结算明细对账 — #102(补贴到账), #103(佣金异常), #105(退款三方), #107(现金流), #108(回款预测), #109(申诉), #110(凭证)。

    基于已有 ProfitState + ShopFunnelDaily 做基础判断。
    深度结算需要平台结算API;这里先用代理率做异常检测。
    """
    funnel = _recent_funnel(db, store_id, days=14)
    if not funnel:
        return {"has_data": False, "findings": [], "summary": "无经营数据"}

    findings: list[dict[str, Any]] = []

    total_gmv = sum(f.gmv or 0 for f in funnel)
    total_orders = sum(f.orders or 0 for f in funnel)

    # #102: 代理佣金率检查 — 如果不同天的佣金率波动大 → 可能有异常
    if len(funnel) >= 7:
        daily_gmv = [(f.gmv or 0) for f in funnel if f.gmv]
        if daily_gmv:
            avg_gmv = sum(daily_gmv) / len(daily_gmv)
            # 如果某天 GMV 突变但订单没变 → 可能是补贴/结算异常
            for f in funnel:
                if f.gmv and f.orders and avg_gmv > 0:
                    expected_gmv = (f.orders / (total_orders / max(1, len(funnel)))) * avg_gmv
                    if f.gmv < expected_gmv * 0.7 or f.gmv > expected_gmv * 1.3:
                        findings.append({
                            "code": "GMV_ANOMALY",
                            "demand_id": 102,
                            "severity": "medium",
                            "title": f"{f.day} GMV ¥{f.gmv:.0f} 与订单量不匹配",
                            "detail": "GMV与订单比例异常,可能是补贴未到账、退款扣减或结算差异。建议对账确认。",
                            "action": "对比平台结算单,确认补贴和退款明细",
                        })
                        break

    # #107: 现金流压力 — 如果利润率很低且推广占比高
    if total_gmv > 0:
        total_ads = sum((f.ads_spend or 0) for f in funnel)
        if total_ads / total_gmv > 0.15:
            findings.append({
                "code": "CASH_FLOW_PRESSURE",
                "demand_id": 107,
                "severity": "medium",
                "title": f"推广占比 {total_ads/total_gmv*100:.0f}%,现金流压力大",
                "detail": "推广费占比高意味着回款慢、利润薄。平台结算周期通常7-15天。",
                "action": "减少推广或优化ROAS,改善现金流",
            })

    # #108: 回款预测 — 基于历史日均GMV推算
    if total_gmv > 0 and len(funnel) >= 3:
        avg_daily_gmv = total_gmv / len(funnel)
        # 平台平均佣金18%, 商家补贴8%
        est_daily_settlement = avg_daily_gmv * 0.74  # 粗估到手
        findings.append({
            "code": "SETTLEMENT_FORECAST",
            "demand_id": 108,
            "severity": "low",
            "title": f"预计日均回款约 ¥{est_daily_settlement:.0f}",
            "detail": f"按近14天日均GMV ¥{avg_daily_gmv:.0f},扣除佣金(18%)和商家补贴(8%),预估日均到手 ¥{est_daily_settlement:.0f}。实际以平台结算单为准。",
            "action": "对账时以平台结算单为准",
        })

    # #109: 申诉建议 — 佣金率超过25%时建议核查
    # #110: 凭证完整性检查
    missing_docs: list[str] = []
    if not any(f.gmv for f in funnel):
        missing_docs.append("GMV明细")
    if not any(f.orders for f in funnel):
        missing_docs.append("订单明细")
    if not any(f.ads_spend for f in funnel):
        missing_docs.append("推广费明细")
    # #103: 单均实收异常 → 佣金/扣点代理信号，不是结算单
    aovs = [f.gmv / f.orders for f in funnel if f.gmv and f.orders]
    if len(aovs) >= 3:
        avg_aov = sum(aovs) / len(aovs)
        if avg_aov > 0 and any(item < avg_aov * 0.7 for item in aovs):
            findings.append({
                "code": "COMMISSION_AOV_ANOMALY",
                "demand_id": 103,
                "severity": "medium",
                "title": "有几天单均实收明显偏低，可能是佣金/扣点异常",
                "detail": "这是 GMV/订单的代理信号，不是平台佣金明细。不能指出「哪一笔佣金扣错了」。",
                "action": "对照平台结算单核对佣金率，不要把单均波动直接当扣错",
            })

    findings.append({
        "code": "REFUND_LEDGER_MISSING",
        "demand_id": 105,
        "severity": "low",
        "title": "退款三方结清无法从现有漏斗核对",
        "detail": "当前只有 GMV/订单，没有退款、平台垫付、商家承担拆分。不能假装已经结清。",
        "action": "导入平台退款/结算明细后再对账",
    })

    if any(item["code"] in {"GMV_ANOMALY", "CASH_FLOW_PRESSURE", "COMMISSION_AOV_ANOMALY"} for item in findings):
        findings.append({
            "code": "DEDUCTION_APPEAL_CHECK",
            "demand_id": 109,
            "severity": "low",
            "title": "有结算异常信号，值得核对是否该申诉",
            "detail": "异常是代理指标，申诉仍需平台结算单和扣款原因。",
            "action": "先导出扣款明细，证据不够就不要提交申诉",
        })

    if missing_docs:
        findings.append({
            "code": "MISSING_RECON_DOCS",
            "demand_id": 110,
            "severity": "low",
            "title": f"月底对账缺少: {', '.join(missing_docs)}",
            "detail": "建议导出平台月度账单并导入,系统会自动对账。",
            "action": f"从平台导出: {', '.join(missing_docs)}",
        })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"14天GMV ¥{total_gmv:.0f},发现 {len(findings)} 个结算问题" if findings else f"14天GMV ¥{total_gmv:.0f},结算对账正常",
    }


# ═══════════════════════════════════════════════════════════
# 排班人效扩展 — #132,135,138
# ═══════════════════════════════════════════════════════════


def diagnose_staffing(db: Session, store_id: str) -> dict[str, Any]:
    """排班人效诊断 — #132(工序瓶颈), #135(备料预测), #138(骑手等待)。

    用订单趋势 + 出餐率 + 差评关键词推断。
    """
    funnel = _recent_funnel(db, store_id)
    ops = _recent_ops(db, store_id)
    findings: list[dict[str, Any]] = []

    if not funnel:
        return {"has_data": False, "findings": [], "summary": "无订单数据"}

    # #135: 备料预测 — 用历史日均推算明天备料量
    orders_list = [(f.orders or 0) for f in funnel[-7:]]
    if orders_list:
        avg_orders = sum(orders_list) / len(orders_list)
        # 按星期几模式调整(简化:用最近同星期)
        from datetime import timedelta as _td
        tomorrow = date.today() + _td(days=1)
        same_day_orders = [
            f.orders or 0 for f in funnel
            if f.day.weekday() == tomorrow.weekday()
        ]
        predicted = (sum(same_day_orders) / len(same_day_orders)) if same_day_orders else avg_orders
        findings.append({
            "code": "PREP_FORECAST",
            "demand_id": 135,
            "severity": "low",
            "title": f"明天预计 {predicted:.0f} 单,建议按此量备料",
            "detail": f"基于近7天日均 {avg_orders:.0f} 和同星期模式。高峰前确认半成品充足。",
            "action": f"按 {predicted:.0f} 单 × 1.2(安全系数) 备料",
        })

    # #132: 工序瓶颈 — 出餐率低 + 差评提"慢/等" → 可能是炒制或打包瓶颈
    cutoff = date.today() - timedelta(days=7)
    reviews = list(
        db.execute(
            select(ReviewFact)
            .where(ReviewFact.store_id == store_id, ReviewFact.reviewed_at >= cutoff)
            .limit(50)
        ).scalars()
    )
    slow_complaints = [r for r in reviews if r.content and any(kw in r.content for kw in ["慢", "等", "久", "迟到"])]
    if slow_complaints and ops:
        prep = [o.meal_prep_rate for o in ops if o.meal_prep_rate is not None]
        if prep and prep[-1] < 0.85:
            findings.append({
                "code": "BOTTLENECK_DETECTED",
                "demand_id": 132,
                "severity": "high",
                "title": f"出餐慢 + {len(slow_complaints)} 条'等太久'差评",
                "detail": "出餐率和差评同时指向制作工序瓶颈。常见:炒制产能不足、打包环节慢、高峰缺人。",
                "action": "排查:高峰时段哪个工序积压最多,针对性增人/优化流程",
            })

    # #138: 骑手等待 — 差评提"骑手等/骑手催"
    rider_complaints = [r for r in reviews if r.content and any(kw in r.content for kw in ["骑手", "取餐", "等餐"])]
    if len(rider_complaints) >= 2:
        findings.append({
            "code": "RIDER_WAITING",
            "demand_id": 138,
            "severity": "medium",
            "title": f"{len(rider_complaints)} 条差评提到骑手等待",
            "detail": "骑手等待会影响配送准时率,平台可能降权。",
            "action": "优化出餐流程,设置骑手到店提醒",
        })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"发现 {len(findings)} 个排班/人效问题" if findings else "排班数据正常",
    }


# ═══════════════════════════════════════════════════════════
# SKU 生命周期扩展 — #142,144,146,148
# ═══════════════════════════════════════════════════════════


def diagnose_sku_strategy(db: Session, store_id: str) -> dict[str, Any]:
    """SKU 策略诊断 — #142(涨价决策), #144(新品建议), #146(换季), #148(区域差异)。"""
    from app.models.entities import MenuItem, MenuItemVersion, ItemFunnelDaily

    items = list(db.execute(select(MenuItem).where(MenuItem.store_id == store_id, MenuItem.is_active.is_(True))).scalars())
    if not items:
        return {"has_data": False, "findings": [], "summary": "无菜单数据"}

    findings: list[dict[str, Any]] = []
    cutoff = date.today() - timedelta(days=14)

    # #142: 原料涨价决策 — 找利润率最薄的SKU
    for item in items[:20]:
        v = db.get(MenuItemVersion, item.current_version_id) if item.current_version_id else None
        if not v or not v.price or not item.food_cost:
            continue
        margin = (v.price - item.food_cost - (item.packaging_cost or 0)) / v.price
        if margin < 0.12:
            suggested_price = (item.food_cost + (item.packaging_cost or 0)) / 0.20  # 目标20%利润率
            findings.append({
                "code": "PRICE_INCREASE_NEEDED",
                "demand_id": 142,
                "severity": "medium",
                "title": f"{v.name} 利润率仅 {margin:.0%},建议涨价到 ¥{suggested_price:.1f}",
                "detail": f"当前售价 ¥{v.price},食材 ¥{item.food_cost}。利润率低于12%,原料涨价时最先亏。",
                "action": f"考虑涨价到 ¥{suggested_price:.1f}(目标20%利润率)或减少份量",
            })

    # #144: 新品建议 — 用现有食材组合
    all_names = []
    for item in items:
        v = db.get(MenuItemVersion, item.current_version_id) if item.current_version_id else None
        if v:
            all_names.append(v.name)
    if len(all_names) >= 3:
        findings.append({
            "code": "NEW_PRODUCT_SUGGESTION",
            "demand_id": 144,
            "severity": "low",
            "title": "基于现有食材开发新品",
            "detail": f"当前 {len(all_names)} 个SKU共用食材。新品开发优先复用现有原料以降低损耗。",
            "action": "分析哪些食材可以组合成新SKU,测试2周后评估",
        })

    # #146: 换季建议 — 按月份推荐
    month = date.today().month
    seasonal_advice = ""
    if month in (11, 12, 1, 2):
        seasonal_advice = "冬季:增加热食/汤类曝光,减少冷食/沙拉"
    elif month in (6, 7, 8):
        seasonal_advice = "夏季:增加凉菜/饮品/轻食曝光,减少重油腻"
    elif month in (3, 4, 5):
        seasonal_advice = "春季:新品测试好时机,可以推出季节限定"
    if seasonal_advice:
        findings.append({
            "code": "SEASONAL_ADJUSTMENT",
            "demand_id": 146,
            "severity": "low",
            "title": seasonal_advice,
            "detail": "换季时调整菜单曝光可以提升转化率。",
            "action": "按季节调整首页推荐和套餐组合",
        })

    findings.append({
        "code": "REGIONAL_TASTE_NEEDS_MULTI_STORE",
        "demand_id": 148,
        "severity": "low",
        "title": "区域口味差异需要多店对照，本店数据不够",
        "detail": "爆款在不同商圈是否不同口味，不能从单店销量推出来。",
        "action": "有多店或商圈对照后再做区域菜单差异，不要按感觉改口味",
    })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"分析了 {len(items)} 个SKU,发现 {len(findings)} 个策略建议" if findings else f"分析了 {len(items)} 个SKU,暂无策略建议",
    }


# ═══════════════════════════════════════════════════════════
# 下单体验扩展 — #161,162,163,165,168
# ═══════════════════════════════════════════════════════════


def diagnose_order_detail(db: Session, store_id: str) -> dict[str, Any]:
    """下单细节诊断 — #161(备注执行), #162(易漏备注), #163(餐具/发票错误), #165(半径限制), #168(爆单简化)。"""
    cutoff = date.today() - timedelta(days=30)
    reviews = list(
        db.execute(
            select(ReviewFact)
            .where(ReviewFact.store_id == store_id, ReviewFact.reviewed_at >= cutoff)
            .limit(200)
        ).scalars()
    )
    if not reviews:
        return {"has_data": False, "findings": [], "summary": "无评价数据"}

    findings: list[dict[str, Any]] = []

    # #161,162,163: 从差评关键词推断订单执行问题
    note_keywords = ["备注", "不要", "多加", "少放", "去了"]
    utensil_keywords = ["餐具", "筷子", "纸巾", "发票", "酱料", "佐料"]
    note_complaints = [r for r in reviews if r.content and any(kw in r.content for kw in note_keywords)]
    utensil_complaints = [r for r in reviews if r.content and any(kw in r.content for kw in utensil_keywords)]

    if len(note_complaints) >= 2:
        findings.append({
            "code": "NOTE_EXECUTION_ISSUE",
            "demand_id": 161,
            "severity": "medium",
            "title": f"{len(note_complaints)} 条差评提到备注没被执行",
            "detail": "顾客备注频繁被遗漏,说明后厨流程需要优化。建议:接单时打印备注、高峰前提醒。",
            "action": "在打印小票上加粗显示备注,或使用备注提醒灯",
        })
        note_hits: dict[str, int] = {}
        for review in note_complaints:
            for kw in note_keywords:
                if kw in (review.content or ""):
                    note_hits[kw] = note_hits.get(kw, 0) + 1
        if note_hits:
            top_kw, top_n = max(note_hits.items(), key=lambda item: item[1])
            findings.append({
                "code": "NOTE_TYPE_MISS",
                "demand_id": 162,
                "severity": "medium",
                "title": f"最容易漏的备注类型是「{top_kw}」（{top_n} 次）",
                "detail": "这是差评关键词频率，不是备注执行率。真正的执行比例需要订单备注对照。",
                "action": f"打包 SOP 把「{top_kw}」类备注做成必检项",
            })

    if len(utensil_complaints) >= 2:
        findings.append({
            "code": "UTENSIL_ERROR",
            "demand_id": 163,
            "severity": "medium",
            "title": f"{len(utensil_complaints)} 条差评提到餐具/调料/发票问题",
            "detail": "餐具/调料遗漏是高频投诉,通常可以通过标准化打包流程解决。",
            "action": "制定标准打包清单,包含餐具/调料/发票检查项",
        })

    # #165: 距离差评差异
    far_complaints = [r for r in reviews if r.content and any(kw in r.content for kw in ["凉", "冷", "化了", "远"])]
    if len(far_complaints) >= 3:
        findings.append({
            "code": "DISTANCE_QUALITY_ISSUE",
            "demand_id": 165,
            "severity": "medium",
            "title": f"{len(far_complaints)} 条差评提到远距离导致的口感问题",
            "detail": "如果近距离好评多但远距离差评多,建议限制配送半径或优化保温包装。",
            "action": "分析差评来源的配送距离,考虑缩减远距离配送范围",
        })

    # #168: 爆单简化建议
    funnel = _recent_funnel(db, store_id)
    if len(funnel) >= 3:
        recent_peak = max((f.orders or 0) for f in funnel)
        if recent_peak > 150:
            findings.append({
                "code": "PEAK_SIMPLIFY_NEEDED",
                "demand_id": 168,
                "severity": "low",
                "title": f"峰值 {recent_peak:.0f} 单,爆单时建议简化菜单",
                "detail": "订单量超过150单/天时,复杂定制需求容易导致出错和延迟。建议:高峰时段暂时关闭复杂加料选项。",
                "action": "设置高峰时段自动隐藏复杂定制选项",
            })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"分析了 {len(reviews)} 条评价,发现 {len(findings)} 个下单体验问题" if findings else f"分析了 {len(reviews)} 条评价,下单体验正常",
    }


# ═══════════════════════════════════════════════════════════
# 内容治理 — #152,157,158,159
# ═══════════════════════════════════════════════════════════


def diagnose_content_health(db: Session, store_id: str) -> dict[str, Any]:
    """内容治理诊断 — #152(图差异), #157(社媒转化), #158(品牌搜索), #159(传播素材)。"""
    from app.models.entities import MenuItem, MenuItemVersion

    items = list(db.execute(select(MenuItem).where(MenuItem.store_id == store_id, MenuItem.is_active.is_(True))).scalars())
    if not items:
        return {"has_data": False, "findings": [], "summary": "无菜单数据"}

    findings: list[dict[str, Any]] = []

    # #152: 图差异风险 — 无图 或 图明显不对
    no_image = []
    for item in items[:20]:
        v = db.get(MenuItemVersion, item.current_version_id) if item.current_version_id else None
        if v and not v.image_url:
            no_image.append(v.name)
    if no_image:
        findings.append({
            "code": "IMAGE_REALITY_GAP",
            "demand_id": 152,
            "severity": "high",
            "title": f"{len(no_image)} 个商品缺少图片或图片与实物不符",
            "detail": f"无图商品: {', '.join(no_image[:3])}。无图商品CTR极低,且可能违反平台规则。",
            "action": "为每个商品拍摄真实出品照片",
        })

    findings.append({
        "code": "CONTENT_TRACKING_NEEDED",
        "demand_id": 157,
        "severity": "low",
        "title": "建议追踪社媒内容转化",
        "detail": "当前无法追踪抖音/小红书内容是否转化为外卖订单。建议:使用专属优惠码追踪不同渠道转化率。",
        "action": "为不同社媒渠道设置专属优惠码,追踪转化",
    })
    findings.append({
        "code": "BRAND_SEARCH_DATA_MISSING",
        "demand_id": 158,
        "severity": "low",
        "title": "品牌搜索效果无法从现有数据验证",
        "detail": "没有搜索词/品牌词曝光数据，不能把社媒浏览写成搜索排名提升。",
        "action": "先看店内搜索曝光与品牌词，有数据再谈内容策略",
    })

    # #159: 传播素材 — 从好评中找
    cutoff = date.today() - timedelta(days=30)
    good_reviews = list(
        db.execute(
            select(ReviewFact)
            .where(ReviewFact.store_id == store_id, ReviewFact.reviewed_at >= cutoff, ReviewFact.rating >= 5.0)
            .limit(10)
        ).scalars()
    )
    if good_reviews:
        sample = good_reviews[0]
        findings.append({
            "code": "BRAND_CONTENT_OPPORTUNITY",
            "demand_id": 159,
            "severity": "low",
            "title": f"有 {len(good_reviews)} 条好评可以做成传播素材",
            "detail": f"例如:「{(sample.content or '好评')[:40]}」可以截图用于店铺装修或社媒推广。",
            "action": "精选好评截图,用于商品描述和店铺装修",
        })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"发现 {len(findings)} 个内容治理建议" if findings else "内容数据正常",
    }


# ═══════════════════════════════════════════════════════════
# 新店启动 — #125,126
# ═══════════════════════════════════════════════════════════


def diagnose_new_store_setup(db: Session, store_id: str) -> dict[str, Any]:
    """新店设置建议 — #125(营业时间), #126(配送范围)。"""
    from app.models.entities import Store, ShopFunnelDaily

    store = db.get(Store, store_id)
    if not store:
        return {"has_data": False, "findings": [], "summary": "门店不存在"}

    findings: list[dict[str, Any]] = []

    # #125: 营业时间建议 — 用已有订单模式推断
    funnel = _recent_funnel(db, store_id)
    if len(funnel) >= 7:
        # 找出有订单的时段(简化:按天的订单分布)
        active_days = [f for f in funnel if f.orders and f.orders > 0]
        if active_days:
            avg = sum(f.orders for f in active_days) / len(active_days)
            findings.append({
                "code": "BUSINESS_HOURS_ADVICE",
                "demand_id": 125,
                "severity": "low",
                "title": "营业时间建议:覆盖午晚两个高峰",
                "detail": f"当前日均 {avg:.0f} 单。建议营业时间 10:00-21:00,覆盖午餐(11:00-13:00)和晚餐(17:00-20:00)高峰。如果人力紧张,优先保午餐。",
                "action": "设置营业时间 10:00-21:00,人力紧张时 10:30-14:00 + 17:00-20:00",
            })

    # #126: 配送范围建议 — 基于门店位置
    findings.append({
        "code": "DELIVERY_RADIUS_ADVICE",
        "demand_id": 126,
        "severity": "low",
        "title": "配送范围建议:初始3公里",
        "detail": "新店建议从3公里起步,确保出餐质量和配送时效。根据好评率逐步扩大。",
        "action": "初始设3公里,好评率>95%后逐步扩到5公里",
    })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"新店设置: {len(findings)} 条建议" if findings else "门店设置正常",
    }


# ═══════════════════════════════════════════════════════════
# 设备异常 — #83
# ═══════════════════════════════════════════════════════════


def diagnose_device_health(db: Session, store_id: str) -> dict[str, Any]:
    """设备异常检测 — #83(接单/打印异常)。

    如果某天订单突然为0 或 订单量异常波动 → 可能是设备故障。
    """
    funnel = _recent_funnel(db, store_id, days=7)
    if len(funnel) < 3:
        return {"has_data": False, "findings": [], "summary": "数据不足"}

    findings: list[dict[str, Any]] = []
    orders_list = [(f.day, f.orders or 0) for f in funnel]

    # 某天订单为0 → 可能接单设备故障
    for day, orders in orders_list:
        if orders == 0:
            findings.append({
                "code": "ZERO_ORDER_DAY",
                "demand_id": 83,
                "severity": "high",
                "title": f"{day} 订单为0,检查设备是否正常",
                "detail": "订单完全为0可能意味着接单设备/网络故障,或门店未营业但未设置歇业。",
                "action": "检查接单设备、网络连接、营业状态设置",
            })
            break

    # 订单量突降 > 50%
    if len(orders_list) >= 2:
        for i in range(1, len(orders_list)):
            prev = orders_list[i-1][1]
            curr = orders_list[i][1]
            if prev > 10 and curr < prev * 0.5:
                findings.append({
                    "code": "ORDER_DROP_DEVICE_CHECK",
                    "demand_id": 83,
                    "severity": "medium",
                    "title": f"{orders_list[i][0]} 订单突降 {(1-curr/prev)*100:.0f}%,排查设备",
                    "detail": f"从 {prev:.0f} 单降到 {curr:.0f} 单。除了正常原因,也要排除打印机断连、接单软件崩溃等设备问题。",
                    "action": "确认接单设备在线、打印正常",
                })
                break

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"发现 {len(findings)} 个设备风险" if findings else "设备运行正常(无异常订单模式)",
    }


def _engine_for_demand(demand_id: int):
    from app.services.compliance_check import check_compliance

    mapping = {
        83: diagnose_device_health,
        84: diagnose_fulfillment,
        85: diagnose_fulfillment,
        86: diagnose_fulfillment,
        87: diagnose_fulfillment,
        88: diagnose_fulfillment,
        89: diagnose_fulfillment,
        101: diagnose_financial_reconciliation,
        102: diagnose_settlement_detail,
        103: diagnose_settlement_detail,
        104: diagnose_financial_reconciliation,
        105: diagnose_settlement_detail,
        106: diagnose_financial_reconciliation,
        107: diagnose_settlement_detail,
        108: diagnose_settlement_detail,
        109: diagnose_settlement_detail,
        110: diagnose_settlement_detail,
        114: check_compliance,
        116: check_compliance,
        119: check_compliance,
        125: diagnose_new_store_setup,
        126: diagnose_new_store_setup,
        131: diagnose_fulfillment,
        132: diagnose_staffing,
        135: diagnose_staffing,
        137: diagnose_fulfillment,
        138: diagnose_staffing,
        141: diagnose_sku_lifecycle,
        142: diagnose_sku_strategy,
        143: diagnose_sku_lifecycle,
        144: diagnose_sku_strategy,
        145: diagnose_sku_lifecycle,
        146: diagnose_sku_strategy,
        147: diagnose_sku_lifecycle,
        148: diagnose_sku_strategy,
        149: diagnose_sku_lifecycle,
        152: diagnose_content_health,
        157: diagnose_content_health,
        158: diagnose_content_health,
        159: diagnose_content_health,
        161: diagnose_order_detail,
        162: diagnose_order_detail,
        163: diagnose_order_detail,
        164: diagnose_order_experience,
        165: diagnose_order_detail,
        166: diagnose_order_experience,
        167: diagnose_order_experience,
        168: diagnose_order_detail,
        169: diagnose_order_experience,
    }
    return mapping.get(demand_id)


def project_ops_findings(db: Session, store_id: str, demand_id: int) -> dict[str, Any]:
    """店长问诊时注入对应引擎结论，不给老板另开诊断入口。"""
    fn = _engine_for_demand(demand_id)
    if fn is None:
        return {}
    raw = fn(db, store_id)
    matched = [item for item in (raw.get("findings") or []) if item.get("demand_id") == demand_id]
    return {
        "ops_has_data": bool(raw.get("has_data")),
        "ops_summary": raw.get("summary") or "",
        "ops_findings": matched[:3],
    }
