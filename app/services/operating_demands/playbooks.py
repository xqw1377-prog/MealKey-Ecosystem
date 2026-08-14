"""经营诊断剧本：按经营家族跑专用判断，不靠 LLM 编故事。"""

from __future__ import annotations

from typing import Any, Iterable

from app.services.operating_demands.models import DemandVerdict, OperatingDemand

BAD = -8.0
WATCH = -3.0
STABLE = 5.0

_STEP_DIAGNOSIS = {
    "exposure": ("曝光下降", "检查活动位/排名/投放是否掉量"),
    "ctr": ("点击竞争力下降", "检查主图/首屏"),
    "cvr": ("进店转化下降", "检查价格感知、套餐和评价"),
    "aov": ("客单下降", "检查低价引流品位置和套餐结构"),
    "activity": ("活动把利润或转化吃掉了", "复核活动叠加与参加范围"),
    "competition": ("对手内容或价格变化造成相对流失", "对照对手变化，过利润门禁后再行动"),
    "review": ("评价/口碑在拖转化", "先处理高优先级差评"),
    "fulfillment": ("履约问题在拖单和口碑", "派门店整改并回收证据"),
    "ads": ("付费流量效率变差", "按 ROI 调整预算，不先加码"),
    "profit": ("利润结构恶化", "先止住亏损活动或亏损 SKU"),
    "cost": ("成本上升在吃利润", "量化冲击后再决定调价或换料"),
    "refund": ("退款赔付在吃利润", "分流正常退款与风险退款"),
}


def _num(facts: dict[str, Any], key: str) -> float | None:
    value = facts.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(facts: dict[str, Any], key: str) -> bool:
    return bool(facts.get(key))


def _cost_not_ready(facts: dict[str, Any]) -> bool:
    if "cost_ready" not in facts and "precise_profit" not in facts:
        return False
    if "cost_ready" in facts:
        return not bool(facts.get("cost_ready"))
    return not bool(facts.get("precise_profit"))


def _text(facts: dict[str, Any], key: str) -> str:
    return str(facts.get(key) or "").strip()


def _stable(value: float | None) -> bool:
    if value is None:
        return True
    return abs(value) < STABLE


def _negative(value: float | None, *, threshold: float = BAD) -> bool:
    return value is not None and value <= threshold


def _positive(value: float | None, *, threshold: float = 0.0) -> bool:
    return value is not None and value > threshold


def _has_truth(facts: dict[str, Any], key: str) -> bool:
    if key in facts and facts.get(key) is not None:
        return True
    alias = {
        "order_pnl": ("unit_profit", "contribution_profit", "paid_order_profit"),
        "store_cost": ("food_cost", "packaging_cost", "ingredient_cost", "pack_cost"),
        "promo_cost": ("promo_cost", "merchant_subsidy"),
        "promo_rules": ("official_promos", "promo_rules"),
        "ad_spend": ("ad_spend", "ads_spend", "total_ads_cost"),
        "refund_amount": ("refund_cost", "refund_amount"),
        "payout_amount": ("payout_amount", "refund_cost"),
        "ingredient_cost": ("ingredient_cost", "food_cost"),
        "pack_cost": ("pack_cost", "packaging_cost"),
        "campaign_result": ("campaign_result", "campaign_profit", "campaign_effect"),
        "unit_cost": ("unit_cost",),
        "new_customers": ("new_customers", "new_customer_share_pct"),
        "repeat_orders": ("repeat_orders", "repurchase_rate"),
        "orders_history": ("orders", "forecast_orders"),
        "reviews": ("reviews", "recent_bad_review_count"),
        "competitor_snapshots": ("competition_changes_count", "competitor_price_changes", "competitor_promo_changes"),
        "hours": ("open_status", "business_hours_ok"),
        "inventory": ("hero_stock_rate", "inventory_risk"),
        "capacity": ("capacity_util", "forecast_orders"),
        "task": ("open_human_tasks_count",),
        "evidence": ("missing_evidence_tasks", "open_human_tasks_count"),
        "platform_pnl": ("platform_pnl_count", "multi_platform_profit"),
        "seasonality": ("seasonality_index",),
    }.get(key, ())
    return any(alias_key in facts and facts.get(alias_key) is not None for alias_key in alias)


def _missing_truth(demand: OperatingDemand, facts: dict[str, Any]) -> list[str]:
    return [item for item in demand.truth if not _has_truth(facts, item)]


def _truth_blocked(demand: OperatingDemand, facts: dict[str, Any]) -> bool:
    if demand.coverage == "green":
        return False
    if demand.loop == "C":
        return False
    return any(not _has_truth(facts, item) for item in demand.blockers)


def _evidence_pairs(facts: dict[str, Any], keys: Iterable[str]) -> list[str]:
    evidence: list[str] = []
    for key in keys:
        value = facts.get(key)
        if value is None:
            continue
        if isinstance(value, float):
            evidence.append(f"{key}={value:+.1f}" if abs(value) <= 1000 else f"{key}={value:.2f}")
        else:
            evidence.append(f"{key}={value}")
    return evidence


def _default_why_not(demand: OperatingDemand) -> list[str]:
    why_not = [f"禁止：{item}" for item in demand.forbidden_actions[:2]]
    if demand.coverage == "red":
        why_not.append("实体动作必须由门店完成，AI 只负责发现、派单、催办和验证")
    return why_not


def _verdict(
    demand: OperatingDemand,
    *,
    diagnosis: str,
    action: str,
    facts: dict[str, Any],
    evidence_keys: Iterable[str] = (),
    why_not: list[str] | None = None,
    missing_truth: list[str] | None = None,
    blocked: bool | None = None,
    execution: str | None = None,
) -> DemandVerdict:
    if missing_truth is None:
        missing_truth = _missing_truth(demand, facts)
    if blocked is None:
        blocked = _truth_blocked(demand, facts)
    if blocked and demand.coverage == "yellow" and demand.blockers:
        action = f"判断已有，但被卡住：{'/'.join(demand.blockers)}"
    if demand.coverage == "red" and demand.loop != "C":
        action = "生成门店整改任务并追踪证据，不假装已经改完后厨"
    if demand.loop == "C":
        execution = "HUMAN_TASK"
        blocked = False
    return DemandVerdict(
        demand=demand,
        diagnosis=diagnosis,
        action=action,
        execution=execution or demand.execution,
        missing_truth=list(demand.blockers) if blocked else missing_truth,
        evidence=_evidence_pairs(facts, evidence_keys),
        why_not=why_not or _default_why_not(demand),
        blocked=blocked,
    )


def diagnose_order_drop(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    exposure = _num(facts, "exposure")
    ctr = _num(facts, "ctr")
    cvr = _num(facts, "cvr")
    aov = _num(facts, "aov")

    if _negative(exposure):
        diagnosis, action = _STEP_DIAGNOSIS["exposure"]
    elif _negative(ctr):
        diagnosis, action = _STEP_DIAGNOSIS["ctr"]
    elif _negative(cvr):
        diagnosis, action = _STEP_DIAGNOSIS["cvr"]
    elif _negative(aov):
        diagnosis, action = _STEP_DIAGNOSIS["aov"]
    else:
        diagnosis = "订单下降，但漏斗尚未指向单一主因"
        action = demand.actions[0]

    if exposure is not None and exposure >= 0 and _negative(ctr) and _stable(cvr):
        diagnosis = "点击竞争力下降"
        action = "检查主图/首屏"

    why_not = []
    if "平台限流" in demand.forbidden_diagnosis and exposure is not None and exposure >= 0:
        why_not.append("曝光未下降，不能把主因写成平台限流")
    if "立即大幅降价" in demand.forbidden_actions:
        why_not.append("主因在点击竞争力时，禁止先大幅降价")

    return _verdict(
        demand,
        diagnosis=diagnosis,
        action=action,
        facts=facts,
        evidence_keys=("orders", "exposure", "ctr", "cvr", "aov"),
        why_not=why_not,
    )


def diagnose_next_best(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    ranked: list[tuple[float, str, str, str]] = []
    mapping = (
        ("orders", "订单正在掉", "先处理当前订单主因，只做一件事"),
        ("profit", "利润正在被吃掉", "先止住最亏的活动或 SKU"),
        ("ctr", "点击竞争力变差", "检查主图/首屏"),
        ("cvr", "进店后转化变差", "检查价格感知、套餐和评价"),
        ("rating", "口碑正在恶化", "先处理高优先级差评"),
        ("ads_roi", "投放已经不赚钱", "先减亏损预算，而不是加码"),
    )
    for key, diagnosis, action in mapping:
        value = _num(facts, key)
        if _negative(value):
            ranked.append((value or 0.0, key, diagnosis, action))
    ranked.sort(key=lambda row: row[0])
    if ranked:
        _, key, diagnosis, action = ranked[0]
        evidence = [f"{row[1]} 触发优先" for row in ranked]
        return _verdict(
            demand,
            diagnosis=diagnosis,
            action=action,
            facts={**facts, "_winner": key},
            evidence_keys=(),
            why_not=["不要一次抛 20 个指标"],
            missing_truth=[],
            blocked=False,
            execution=demand.execution,
        )
    return _verdict(
        demand,
        diagnosis="今天没有压过其他事项的单一经营危机",
        action="守住当前利润，不主动加码",
        facts=facts,
        evidence_keys=("orders", "profit", "ctr", "cvr", "ads_roi"),
        why_not=["没有危机时不要为了有动作而动作"],
        missing_truth=[],
        blocked=False,
        execution=demand.execution,
    )


def diagnose_follow_price(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    unit = _num(facts, "unit_profit")
    rival = _num(facts, "rival_price_delta")
    gate_ok = _bool(facts, "profit_gate_passed")
    if rival is not None and rival < 0 and not gate_ok:
        return _verdict(
            demand,
            diagnosis="对手降价了，但跟价会穿过利润门禁",
            action="过利润门禁后再决定是否跟价",
            facts=facts,
            evidence_keys=("rival_price_delta", "unit_profit"),
            why_not=["竞争情报不能直接变成别人降价我也降价"],
            blocked=False,
            execution="ASK_APPROVAL",
        )
    return _verdict(
        demand,
        diagnosis="对手价格变化需要对照自身单均利润后再决定",
        action="给出跟或不跟的利润对照，提交老板确认",
        facts=facts,
        evidence_keys=("rival_price_delta", "unit_profit"),
        why_not=["禁止立即跟价"],
        blocked=False,
        execution="ASK_APPROVAL",
    )


def diagnose_profit_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    if _cost_not_ready(facts):
        return _verdict(
            demand,
            diagnosis="没有食材成本，不能报精确利润，也不能说今天亏多少",
            action="先上传食材成本表，再判断利润",
            facts=facts,
            evidence_keys=("cost_ready", "cost_coverage_pct"),
            why_not=["禁止在没有成本时报精确利润", "禁止建议报名或加预算"],
            blocked=True,
            missing_truth=["item_cost_map"],
        )
    refund_cost = _num(facts, "refund_cost")
    promo_cost = _num(facts, "promo_cost") or _num(facts, "merchant_subsidy")
    ad_spend = _num(facts, "ad_spend") or _num(facts, "ads_spend")
    take_home = _num(facts, "take_home_rate")
    take_home_delta = _num(facts, "profit")
    ingredient_cost = _num(facts, "ingredient_cost") or _num(facts, "food_cost")
    pack_cost = _num(facts, "pack_cost") or _num(facts, "packaging_cost")
    forecast_gap = _num(facts, "forecast_gap")

    if demand.code == "REFUND_PROFIT" and _positive(refund_cost):
        return _verdict(demand, diagnosis="退款赔付正在吃利润", action="量化退款赔付并分流处理", facts=facts, evidence_keys=("refund_cost", "payout_amount", "profit"))
    if demand.code == "CAMPAIGN_EATS_PROFIT" and _positive(promo_cost):
        return _verdict(demand, diagnosis="活动补贴正在吃利润", action="退出或改叠加规则", facts=facts, evidence_keys=("promo_cost", "profit", "take_home_rate"))
    if demand.code == "AD_ORDER_PROFIT" and _positive(ad_spend):
        return _verdict(demand, diagnosis="投流订单利润被广告花费吃掉", action="保留赚钱投放、砍亏损投放", facts=facts, evidence_keys=("ad_spend", "paid_order_profit", "profit"))
    if demand.code == "TAKEHOME_DROP" and (_negative(take_home_delta) or _negative(take_home)):
        return _verdict(demand, diagnosis="到手率下降，先查活动、投流和成本", action="找出到手率下降主因", facts=facts, evidence_keys=("take_home_rate", "profit", "promo_cost", "ads_spend"))
    if demand.code == "COST_SHOCK" and (_positive(ingredient_cost) or _positive(pack_cost)):
        return _verdict(demand, diagnosis="食材或包装成本上升在吃利润", action="量化成本冲击并给调价/换料建议", facts=facts, evidence_keys=("ingredient_cost", "pack_cost", "profit"))
    if demand.code == "MONTH_TARGET" and _negative(forecast_gap):
        return _verdict(demand, diagnosis="按当前趋势，本月利润目标有缺口", action="给出完成概率与缺口动作", facts=facts, evidence_keys=("profit", "forecast_gap"))
    if _positive(refund_cost):
        diagnosis = "退款赔付正在吃利润"
        action = "分流正常退款与风险退款"
    elif _positive(promo_cost):
        diagnosis = "活动补贴在吃利润"
        action = "复核活动叠加与参加范围"
    elif _positive(ad_spend):
        diagnosis = "广告成本正在吃利润"
        action = "先保住赚钱投放"
    elif _positive(ingredient_cost) or _positive(pack_cost):
        diagnosis = "成本上升在吃利润"
        action = "量化冲击后再决定调价或换料"
    else:
        diagnosis = f"围绕「{demand.question}」完成利润判断"
        action = demand.actions[0]
    return _verdict(
        demand,
        diagnosis=diagnosis,
        action=action,
        facts=facts,
        evidence_keys=("profit", "take_home_rate", "refund_cost", "promo_cost", "ads_spend", "food_cost", "packaging_cost"),
    )


def diagnose_campaign_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    stacked_profit = _num(facts, "stacked_profit") or _num(facts, "unit_profit")
    safe_takehome = _num(facts, "safe_takehome")
    campaign_effect = _num(facts, "campaign_effect") or _num(facts, "campaign_result")
    aov = _num(facts, "aov")
    cvr = _num(facts, "cvr")
    price_delta = _num(facts, "price_delta") or _num(facts, "price_elasticity")

    if demand.code == "JOIN_CAMPAIGN":
        if _cost_not_ready(facts):
            titles = [str(item.get("title") or "").strip() for item in (facts.get("official_promos") or []) if isinstance(item, dict)]
            titles = [title for title in titles if title][:3]
            prefix = f"官网公开活动有：{'、'.join(titles)}。" if titles else ""
            return _verdict(
                demand,
                diagnosis=f"{prefix}没有食材成本，不能判断参不参加活动，更不能无账报名",
                action="先上传成本表，再过利润门禁",
                facts=facts,
                evidence_keys=("cost_ready", "unit_profit", "official_promos"),
                blocked=True,
                missing_truth=["item_cost_map", "unit_cost"],
            )
        promos = facts.get("official_promos") or []
        policies = facts.get("official_policies") or []
        intel_status = str(facts.get("intel_status") or "")
        titles = [str(item.get("title") or "").strip() for item in promos if isinstance(item, dict)]
        titles = [title for title in titles if title][:3]
        if titles:
            diagnosis = f"官网公开活动有：{'、'.join(titles)}。参不参加仍要过利润门禁，不能无账报名"
            action = "对照本店成本和叠加券，给出参加/拒绝建议"
        elif intel_status == "failed":
            diagnosis = "官网政策/活动采集失败，不能假装有可报名活动"
            action = "先重试采集公开页，有证据后再判断参不参加"
        else:
            diagnosis = "官网还没采到可报名活动，不能无账报名"
            action = "先采集官网活动，再按利润门禁判断参不参加"
        evidence = ["official_promos", "official_policies", "unit_profit"]
        if policies and not titles:
            policy_titles = [str(item.get("title") or "").strip() for item in policies if isinstance(item, dict)]
            policy_titles = [title for title in policy_titles if title][:2]
            if policy_titles:
                diagnosis = f"官网公开政策有：{'、'.join(policy_titles)}。没有可报名活动证据时，先不参加"
        return _verdict(demand, diagnosis=diagnosis, action=action, facts=facts, evidence_keys=evidence)
    if demand.code == "STACK_LOSS" and stacked_profit is not None:
        diagnosis = "活动和现有券叠加后仍有利润" if stacked_profit > 0 else "活动和现有券叠加后会亏损"
        action = "算出叠加后到手价与单均利润"
        return _verdict(demand, diagnosis=diagnosis, action=action, facts=facts, evidence_keys=("stacked_profit", "unit_profit", "promo_cost"))
    if demand.code == "SAFE_TAKEHOME" and safe_takehome is not None:
        return _verdict(demand, diagnosis="已算出最低安全到手价", action="给出安全到手价", facts=facts, evidence_keys=("safe_takehome", "unit_cost"))
    if demand.code == "RENEW_CAMPAIGN" and campaign_effect is not None:
        diagnosis = "活动续报前要先回看 3 天效果"
        if campaign_effect > 0:
            action = "根据3天效果决定续/停/改"
        else:
            action = "根据3天效果决定停或改规则"
        return _verdict(demand, diagnosis=diagnosis, action=action, facts=facts, evidence_keys=("campaign_effect", "campaign_profit", "profit"))
    if demand.code == "PRICE_CHANGE" and (price_delta is not None or cvr is not None):
        return _verdict(
            demand,
            diagnosis="调价要同时看利润弹性和转化护栏",
            action="给出调价幅度建议",
            facts=facts,
            evidence_keys=("price_delta", "unit_profit", "cvr"),
        )
    if demand.code in {"RAISE_AOV", "BEST_BUNDLE"} and (aov is not None or cvr is not None):
        return _verdict(
            demand,
            diagnosis="当前客单提升优先走套餐/加价购，而不是直接硬涨价",
            action=demand.actions[0],
            facts=facts,
            evidence_keys=("aov", "cvr", "unit_profit"),
        )
    diagnosis = f"围绕「{demand.question}」完成活动/定价判断"
    return _verdict(
        demand,
        diagnosis=diagnosis,
        action=demand.actions[0],
        facts=facts,
        evidence_keys=("unit_profit", "campaign_effect", "aov", "cvr", "promo_cost"),
    )


def diagnose_ads_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    roi = _num(facts, "ads_roi")
    pace = _num(facts, "budget_pace")
    daypart = _num(facts, "daypart_roi")
    search_rank = _num(facts, "search_rank")
    organic_orders = _num(facts, "organic_orders")
    paid_orders = _num(facts, "paid_orders")
    paid_cvr = _num(facts, "paid_cvr")

    if demand.code in {"BUDGET_UP_DOWN", "SCALE_WINNER"} and _cost_not_ready(facts):
        return _verdict(
            demand,
            diagnosis="没有食材成本，不能建议加预算",
            action="先上传成本表，再按利润看预算",
            facts=facts,
            evidence_keys=("cost_ready", "ads_roi"),
            blocked=True,
            missing_truth=["item_cost_map"],
        )
    if demand.code == "ADS_ROI" and roi is not None:
        diagnosis = "今天推广花的钱已经赚回来了" if roi > 1 else "今天推广花的钱还没赚回来"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("ads_roi", "ads_spend", "paid_orders"))
    if demand.code in {"BUDGET_UP_DOWN", "CUT_LOSER", "SCALE_WINNER"} and roi is not None:
        if roi <= 1:
            diagnosis = "投流 ROI 已经偏差，优先减亏损预算"
        else:
            diagnosis = "投流 ROI 健康，但仍要看预算节奏和利润门禁"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("ads_roi", "budget_pace", "profit"))
    if demand.code == "BUDGET_BURN" and pace is not None:
        diagnosis = "预算有在午高峰前烧完的风险" if pace > 0.7 else "预算节奏仍可控"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("budget_pace", "ads_spend"))
    if demand.code == "SHIFT_DAYPART" and daypart is not None:
        diagnosis = "午餐时段 ROI 更高，应把钱挪到高价值时段" if daypart > 0 else "时段 ROI 差异不明显，先不激进挪预算"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("daypart_roi", "budget_pace"))
    if demand.code == "PAID_CVR_DROP" and _negative(paid_cvr):
        return _verdict(demand, diagnosis="付费流量转化下降，先查落地页、价格感知和评价", action=demand.actions[0], facts=facts, evidence_keys=("paid_cvr", "ctr", "cvr"))
    if demand.code == "ORGANIC_VS_PAID" and (organic_orders is not None or paid_orders is not None):
        diagnosis = "今天订单增长主要来自付费流量" if (paid_orders or 0) > (organic_orders or 0) else "今天订单增长主要来自自然流量"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("organic_orders", "paid_orders"))
    if demand.code == "SEARCH_RANK" and search_rank is not None:
        diagnosis = "搜索曝光/关键词排名正在下降，先查标题主图活动再决定是否买词" if search_rank < 0 else "搜索排名暂未明显恶化"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("search_rank", "impressions", "ctr"))
    return _verdict(
        demand,
        diagnosis=f"围绕「{demand.question}」完成投流判断",
        action=demand.actions[0],
        facts=facts,
        evidence_keys=("ads_roi", "budget_pace", "paid_cvr", "organic_orders", "paid_orders"),
    )


def diagnose_product_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    ctr = _num(facts, "ctr") or _num(facts, "hero_ctr")
    cvr = _num(facts, "cvr")
    hero_stock = _num(facts, "hero_stock_rate")
    new_sku_orders = _num(facts, "new_sku_orders")
    first_screen = _num(facts, "first_screen_ctr")

    if demand.code == "HERO_CTR_DROP" and _negative(ctr):
        return _verdict(demand, diagnosis="招牌商品点击竞争力下降", action="诊断招牌点击竞争力", facts=facts, evidence_keys=("hero_ctr", "ctr", "impressions"))
    if demand.code in {"CHANGE_IMAGE", "GENERATE_IMAGE"} and _negative(ctr):
        return _verdict(demand, diagnosis="当前主图竞争力不足，需要换图验证", action=demand.actions[0], facts=facts, evidence_keys=("hero_ctr", "ctr", "cvr"))
    if demand.code == "CHANGE_TITLE" and _negative(ctr):
        return _verdict(demand, diagnosis="商品标题点击力不足", action=demand.actions[0], facts=facts, evidence_keys=("ctr", "hero_ctr"))
    if demand.code == "CHANGE_DESC" and _negative(cvr):
        return _verdict(demand, diagnosis="商品描述未能把进店流量转成下单", action=demand.actions[0], facts=facts, evidence_keys=("cvr", "rating"))
    if demand.code == "FIRST_SCREEN" and (_negative(first_screen) or _negative(ctr)):
        return _verdict(demand, diagnosis="首屏陈列没有把最能打的商品顶出来", action=demand.actions[0], facts=facts, evidence_keys=("first_screen_ctr", "ctr", "aov"))
    if demand.code == "NEW_SKU_STALL" and (new_sku_orders is not None and new_sku_orders <= 0):
        return _verdict(demand, diagnosis="新品上线后没有拿到足够曝光和转化", action=demand.actions[0], facts=facts, evidence_keys=("new_sku_orders", "ctr", "cvr"))
    if demand.code == "SOLD_OUT":
        diagnosis = "爆款已经售罄，先决定补货还是切换主推" if hero_stock is not None and hero_stock < 0.5 else "库存信号还不完整，但售罄判断应走人机闭环"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("hero_stock_rate", "hero_orders"), execution="HUMAN_TASK", blocked=False)
    return _verdict(
        demand,
        diagnosis=f"围绕「{demand.question}」完成商品/菜单判断",
        action=demand.actions[0],
        facts=facts,
        evidence_keys=("ctr", "cvr", "aov", "hero_stock_rate", "new_sku_orders"),
    )


def diagnose_order_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    exposure = _num(facts, "exposure")
    ctr = _num(facts, "ctr")
    cvr = _num(facts, "cvr")
    aov = _num(facts, "aov")
    new_customers = _num(facts, "new_customers")
    repeat_orders = _num(facts, "repeat_orders")
    forecast_orders = _num(facts, "forecast_orders")

    if demand.code == "EXPOSURE_DROP" and _negative(exposure):
        return _verdict(demand, diagnosis="曝光明显下降，优先查活动位/排名/投放", action=demand.actions[0], facts=facts, evidence_keys=("exposure", "search_rank", "ads_spend"))
    if demand.code == "ENTRY_CTR" and _negative(ctr):
        return _verdict(demand, diagnosis="有人看到店但不点进来，问题更像在主图/标题/首屏", action=demand.actions[0], facts=facts, evidence_keys=("ctr", "exposure"))
    if demand.code == "CVR_DROP" and _negative(cvr):
        return _verdict(demand, diagnosis="进店后不下单，问题更像在价格感知、套餐和评价", action=demand.actions[0], facts=facts, evidence_keys=("cvr", "rating", "aov"))
    if demand.code == "AOV_DROP" and _negative(aov, threshold=WATCH):
        return _verdict(demand, diagnosis="订单没掉但客单下降，优先查引流品和套餐结构", action=demand.actions[0], facts=facts, evidence_keys=("aov", "orders"))
    if demand.code == "NEW_CUSTOMER_DROP" and _negative(new_customers):
        return _verdict(demand, diagnosis="新客减少，要先查流量来源和新客活动效率", action=demand.actions[0], facts=facts, evidence_keys=("new_customers", "ads_roi"))
    if demand.code == "REPEAT_DROP" and _negative(repeat_orders):
        return _verdict(demand, diagnosis="老客复购下降，要先查体验、评价和召回节奏", action=demand.actions[0], facts=facts, evidence_keys=("repeat_orders", "recent_bad_review_count"))
    if demand.code == "LUNCH_FORECAST" and forecast_orders is not None:
        return _verdict(demand, diagnosis="已给出午晚高峰订单预测，接下来要核对产能是否撑得住", action=demand.actions[0], facts=facts, evidence_keys=("forecast_orders", "capacity_util"))
    if demand.code == "EXTERNAL_VS_SELF":
        diagnosis = "先对照商圈，再判断问题来自外部波动还是自身漏斗"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("exposure", "ctr", "cvr", "orders"))
    return diagnose_generic(demand, facts)


def diagnose_review_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    bad_reviews = _num(facts, "recent_bad_review_count")
    bad_rate = _num(facts, "bad_review_rate")
    refund_risk = _num(facts, "refund_risk")
    complaint_age = _num(facts, "complaint_age_hours")
    themes = _text(facts, "review_theme")

    if demand.code == "URGENT_REVIEWS" and (bad_reviews or 0) > 0:
        return _verdict(demand, diagnosis="已有新差评进入高优先级处理队列", action=demand.actions[0], facts=facts, evidence_keys=("recent_bad_review_count", "bad_review_rate"))
    if demand.code == "REVIEW_ATTRIBUTION":
        owner = _text(facts, "review_owner") or "产品/门店/骑手/顾客"
        return _verdict(demand, diagnosis=f"这条差评更像是{owner}问题", action=demand.actions[0], facts=facts, evidence_keys=("recent_bad_review_count", "bad_review_rate"))
    if demand.code in {"REVIEW_REPLY", "AUTO_REPLY_ORDINARY"}:
        diagnosis = "这条评价可生成结构化回复" if demand.code == "REVIEW_REPLY" else "普通评价可按权限进入自动回复"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("recent_bad_review_count", "reviews"))
    if demand.code == "MALICIOUS_REFUND" and refund_risk is not None:
        diagnosis = "退款更像恶意骗赔" if refund_risk > 0.7 else "退款更像正常售后问题"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("refund_risk", "refund_cost"))
    if demand.code == "SLA_24H" and complaint_age is not None:
        diagnosis = "已有投诉即将超过 24 小时 SLA" if complaint_age >= 20 else "当前投诉工单尚未逼近 SLA"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("complaint_age_hours", "recent_bad_review_count"))
    if demand.code == "REPEAT_ROOT_CAUSE" and themes:
        return _verdict(demand, diagnosis=f"最近差评重复聚焦在「{themes}」", action=demand.actions[0], facts=facts, evidence_keys=("recent_bad_review_count", "bad_review_rate"))
    return _verdict(
        demand,
        diagnosis=f"围绕「{demand.question}」完成评价/售后判断",
        action=demand.actions[0],
        facts=facts,
        evidence_keys=("recent_bad_review_count", "bad_review_rate", "refund_risk", "complaint_age_hours"),
    )


def diagnose_crm_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    repurchase = _num(facts, "repurchase_rate")
    new_share = _num(facts, "new_customer_share_pct")
    churn = _text(facts, "churn_risk_level")
    high_value = _num(facts, "high_value_count")
    sleeping = _num(facts, "sleeping_count")
    if _truth_blocked(demand, facts):
        return _verdict(
            demand,
            diagnosis="CRM 判断骨架已就位，但缺少用户级复购明细和用户身份主数据",
            action=f"判断已有，但被卡住：{'/'.join(demand.blockers)}",
            facts=facts,
            evidence_keys=("repurchase_rate", "new_customer_share_pct"),
            blocked=True,
        )
    if demand.code == "HIGH_VALUE" and high_value is not None:
        return _verdict(demand, diagnosis="已识别当前高价值顾客", action=demand.actions[0], facts=facts, evidence_keys=("high_value_count", "repurchase_rate"))
    if demand.code == "SLEEPING" and sleeping is not None:
        return _verdict(demand, diagnosis="已有沉睡老客名单", action=demand.actions[0], facts=facts, evidence_keys=("sleeping_count", "repurchase_rate"))
    if demand.code == "SECOND_ORDER" and new_share is not None:
        return _verdict(demand, diagnosis="新客第二单问题要优先看首单体验和召回节奏", action=demand.actions[0], facts=facts, evidence_keys=("new_customer_share_pct", "repurchase_rate"))
    if demand.code == "CHURN_RISK" and churn:
        return _verdict(demand, diagnosis=f"当前流失风险等级：{churn}", action=demand.actions[0], facts=facts, evidence_keys=("repurchase_rate",))
    return _verdict(
        demand,
        diagnosis=f"围绕「{demand.question}」完成顾客经营判断",
        action=demand.actions[0],
        facts=facts,
        evidence_keys=("repurchase_rate", "new_customer_share_pct"),
    )


def diagnose_competition_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    snapshots = _num(facts, "competition_changes_count")
    price_changes = _num(facts, "competitor_price_changes")
    promo_changes = _num(facts, "competitor_promo_changes")
    rival_signal = _text(facts, "competition_signal")
    if _truth_blocked(demand, facts):
        return _verdict(
            demand,
            diagnosis="竞品判断已挂链，但缺商圈真实订单趋势与稳定竞品快照",
            action=f"判断已有，但被卡住：{'/'.join(demand.blockers)}",
            facts=facts,
            evidence_keys=("competition_changes_count", "competitor_price_changes", "competitor_promo_changes"),
            blocked=True,
        )
    if demand.code == "RIVAL_PRICE" and _positive(price_changes):
        return _verdict(demand, diagnosis="已有竞争对手最近改价信号", action=demand.actions[0], facts=facts, evidence_keys=("competitor_price_changes",))
    if demand.code == "RIVAL_PROMO" and _positive(promo_changes):
        return _verdict(demand, diagnosis="已有竞争对手活动变化信号", action=demand.actions[0], facts=facts, evidence_keys=("competitor_promo_changes",))
    if demand.code == "RIVAL_SPIKE" and rival_signal:
        return _verdict(demand, diagnosis=f"对手最近上升更像是「{rival_signal}」驱动", action=demand.actions[0], facts=facts, evidence_keys=("competition_changes_count",))
    diagnosis = "已拉起商圈竞品判断，但不能把代理快照写成真实市场份额"
    return _verdict(
        demand,
        diagnosis=diagnosis,
        action=demand.actions[0],
        facts=facts,
        evidence_keys=("competition_changes_count", "competitor_price_changes", "competitor_promo_changes"),
        why_not=["竞争情报不能直接变成别人降价我也降价"],
    )


def diagnose_fulfillment_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    open_status = _text(facts, "open_status")
    hero_stock = _num(facts, "hero_stock_rate")
    capacity = _num(facts, "capacity_util")
    device = _text(facts, "device_status")
    missing_evidence = _num(facts, "missing_evidence_tasks")
    if demand.code == "WRONG_HOURS":
        diagnosis = "营业时间或开关店状态存在异常" if open_status in {"closed", "unknown"} else "营业时间配置基本正常"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("open_status", "business_hours_ok"))
    if demand.code == "RESTOCK_WHO":
        diagnosis = "爆款库存正在逼近售罄" if hero_stock is not None and hero_stock < 0.5 else "需要店长确认是否补货或换主推"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("hero_stock_rate", "hero_orders"), execution="HUMAN_TASK", blocked=False)
    if demand.code == "DEVICE_MISS":
        diagnosis = "设备信号异常可能正在导致漏单" if device and device != "ok" else "接单/打印链路需要排查设备状态"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("device_status", "orders"))
    if demand.code == "RECTIFY_EVIDENCE":
        diagnosis = f"仍有 {int(missing_evidence or 0)} 件整改缺证据" if missing_evidence else "门店整改需要证据回传才能算完成"
        return _verdict(demand, diagnosis=diagnosis, action="催办并核验证据，没有证据不算做完", facts=facts, evidence_keys=("open_human_tasks_count", "missing_evidence_tasks"), execution="HUMAN_TASK", blocked=False, why_not=["禁止：相信口头回复", "禁止：整改过就一定有效"])
    if demand.code in {"SLOW_COOK", "MERCHANT_CANCEL", "SPILL", "WRONG_ITEM", "CAPACITY_PEAK", "MATERIALS"}:
        diagnosis_map = {
            "SLOW_COOK": "最近出餐变慢，需要按 SKU/班次做线下整改",
            "MERCHANT_CANCEL": "商责取消上升，需要排查缺货/设备/营业配置",
            "SPILL": "包装洒漏在重复发生，需要核包装动作和包装材质",
            "WRONG_ITEM": "漏餐错餐在重复发生，需要核打包检查流程",
            "CAPACITY_PEAK": "午高峰即将逼近产能上限，需要备人备料",
            "MATERIALS": "原料或包装物料存在短缺风险，需要补货",
        }
        evidence_keys = {
            "CAPACITY_PEAK": ("capacity_util", "forecast_orders"),
            "MATERIALS": ("inventory_risk", "hero_stock_rate"),
        }.get(demand.code, ("capacity_util", "orders"))
        return _verdict(demand, diagnosis=diagnosis_map[demand.code], action=demand.actions[0], facts=facts, evidence_keys=evidence_keys, execution="HUMAN_TASK", blocked=False)
    return _verdict(
        demand,
        diagnosis=f"围绕「{demand.question}」完成履约判断",
        action=demand.actions[0],
        facts=facts,
        evidence_keys=("open_status", "hero_stock_rate", "device_status", "capacity_util"),
    )


def diagnose_chain_family(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    multi_profit = _num(facts, "multi_platform_profit")
    platform_count = _num(facts, "platform_pnl_count")
    store_rank = _text(facts, "store_rank_summary")
    copy_lift = _num(facts, "copy_lift")
    week_delta = _text(facts, "week_delta_summary")

    if demand.code == "MULTI_PLATFORM_PROFIT":
        diagnosis = "多平台利润已汇总" if multi_profit is not None else "多平台利润还没真正汇总起来"
        return _verdict(demand, diagnosis=diagnosis, action=demand.actions[0], facts=facts, evidence_keys=("multi_platform_profit", "platform_pnl_count"))
    if demand.code == "BEST_WORST_STORES" and store_rank:
        return _verdict(demand, diagnosis=f"门店优劣排名已产出：{store_rank}", action=demand.actions[0], facts=facts, evidence_keys=("store_rank_summary",))
    if demand.code == "COPY_STRATEGY" and copy_lift is not None:
        return _verdict(demand, diagnosis="已存在可复制的门店策略样本", action=demand.actions[0], facts=facts, evidence_keys=("copy_lift",))
    if demand.code == "WEEK_CHANGE" and week_delta:
        return _verdict(demand, diagnosis=f"本周最重要的经营变化：{week_delta}", action=demand.actions[0], facts=facts, evidence_keys=("week_delta_summary",))
    return _verdict(
        demand,
        diagnosis=f"围绕「{demand.question}」完成多店/多平台经营判断",
        action=demand.actions[0],
        facts=facts,
        evidence_keys=("multi_platform_profit", "platform_pnl_count", "copy_lift"),
    )


def diagnose_generic(demand: OperatingDemand, facts: dict[str, Any]) -> DemandVerdict:
    missing = _missing_truth(demand, facts)
    for step in demand.playbook:
        mapped = _STEP_DIAGNOSIS.get(step)
        signal = _num(facts, step)
        if mapped and _negative(signal):
            diagnosis, action = mapped
            return _verdict(demand, diagnosis=diagnosis, action=action, facts=facts, missing_truth=missing)
    return _verdict(
        demand,
        diagnosis=f"围绕「{demand.question}」完成判断",
        action=demand.actions[0] if demand.actions else "给出下一步经营动作",
        facts=facts,
        missing_truth=missing,
    )


def run_playbook(demand: OperatingDemand, facts: dict[str, Any] | None = None) -> DemandVerdict:
    facts = facts or {}
    if demand.code == "ORDER_DROP":
        return diagnose_order_drop(demand, facts)
    if demand.code == "NEXT_BEST":
        return diagnose_next_best(demand, facts)
    if demand.code == "FOLLOW_PRICE":
        if _cost_not_ready(facts):
            return _verdict(
                demand,
                diagnosis="没有食材成本，不能过利润门禁，更不能跟价",
                action="先上传成本表，再决定跟不跟",
                facts=facts,
                evidence_keys=("cost_ready", "unit_profit"),
                why_not=["利润门禁不通过不得跟价"],
                blocked=True,
                missing_truth=["item_cost_map", "unit_cost"],
            )
        return diagnose_follow_price(demand, facts)
    if demand.code == "RECTIFY_EVIDENCE":
        return diagnose_fulfillment_family(demand, facts)

    family_dispatch = {
        "profit": diagnose_profit_family,
        "campaign": diagnose_campaign_family,
        "ads": diagnose_ads_family,
        "product": diagnose_product_family,
        "order": diagnose_order_family,
        "review": diagnose_review_family,
        "crm": diagnose_crm_family,
        "competition": diagnose_competition_family,
        "fulfillment": diagnose_fulfillment_family,
        "chain": diagnose_chain_family,
    }
    handler = family_dispatch.get(demand.family, diagnose_generic)
    verdict = handler(demand, facts)
    findings = facts.get("ops_findings") or []
    if findings and not verdict.blocked:
        top = findings[0]
        if top.get("title"):
            verdict.diagnosis = str(top["title"])
        if top.get("action"):
            verdict.action = str(top["action"])
        detail = str(top.get("detail") or "").strip()
        if detail:
            verdict.evidence = list(verdict.evidence) + [detail[:160]]
    return verdict
