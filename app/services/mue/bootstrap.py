"""从平台/StoreState 自动填充 A 类知识，并列出 C 类缺口。"""

from __future__ import annotations

from typing import Any

from app.schemas.merchant_understanding import (
    GapQuestion,
    InferredFact,
    MerchantUnderstanding,
    OperatingConstraints,
    OperatingPreferences,
    PermissionPolicy,
)


# 访谈题库：只覆盖 AI 不该自决的项（C 类：必须问老板）
_GAP_CATALOG: dict[str, GapQuestion] = {
    "priority_style": GapQuestion(
        key="priority_style",
        question="经营这家店，你现在最在乎什么？",
        context="平台数据能告诉我订单和利润的张力，但你更想冲量、保利润还是冲排名，只有你能定。我以后会按这个原则替你做判断。",
        options=["多一点订单", "提高利润", "提高排名", "你帮我平衡"],
    ),
    "lunch_capacity": GapQuestion(
        key="lunch_capacity",
        question="午餐高峰时，厨房一小时大概最多能稳妥做多少单？",
        context="接近上限时我会主动收一收激进投流，避免为了排名把后厨打爆。",
    ),
    "low_risk_auto": GapQuestion(
        key="low_risk_auto",
        question="这些低风险的事，我可以直接替你做吗？",
        context="普通好评回复、活动到期、商品售罄和竞品监控——低风险、可撤销。建议先放开，信任建立后再谈投流额度。",
        options=["可以", "先不要"],
    ),
    "profit_floor": GapQuestion(
        key="profit_floor",
        question="一笔订单最低赚多少钱你才愿意接？或者说，你的到手率底线大概是多少？",
        context="参加活动、投流、做满减都会压利润。有了这个底线，我就能自己判断哪些活动值得参加、哪些是买流水。",
    ),
    "hero_item_floor_price": GapQuestion(
        key="hero_item_floor_price",
        question="你的招牌菜（比如牛肉饭）最低多少钱卖不会亏？",
        context="平台经常要求降价参加活动。有了成本底线，我能判断哪些活动可以接、哪些会亏，不用每次都问你。",
    ),
    "ads_daily_budget": GapQuestion(
        key="ads_daily_budget",
        question="广告投流这块，你每天大概愿意花多少？给个上限就行，超过的我再问你。",
        context="有了预算上限，我可以在范围内自己调整投流策略，不用每天找你确认。一开始可以先给少一点，信任建立后再加。",
    ),
    "weekend_strategy": GapQuestion(
        key="weekend_strategy",
        question="周末的经营策略和工作日一样吗？还是周末可以更激进/更保守一点？",
        context="有些店周末是高峰（商圈/商场），有些店周末反而淡（写字楼）。告诉我你的节奏，我会按周几调整策略。",
        options=["和工作日一样", "周末可以激进一点", "周末保守一点"],
    ),
    "competitor_focus": GapQuestion(
        key="competitor_focus",
        question="有没有哪些竞品是你特别在意的？（比如旁边那家鸡肉饭）",
        context="商圈里可能有几十家店，但真正抢你生意的可能就两三家。告诉我你最在意谁，我重点盯他们。",
    ),
}


def default_open_gaps() -> list[str]:
    # 按优先级排序：偏好 > 约束 > 权限
    return [
        "priority_style",
        "lunch_capacity",
        "profit_floor",
        "hero_item_floor_price",
        "low_risk_auto",
        "ads_daily_budget",
        "weekend_strategy",
        "competitor_focus",
    ]


def gap_question(key: str) -> GapQuestion | None:
    return _GAP_CATALOG.get(key)


def extract_known_from_agents(agents: Any | None) -> dict[str, Any]:
    """A 类：能从已有 Agent/StoreState 读到的，一律不问。"""
    profile: dict[str, Any] = {}
    if agents is None:
        return profile
    state = getattr(agents, "store_state", None)
    if state is None:
        return profile

    store = getattr(state, "store", None)
    if store is not None:
        profile["store_name"] = getattr(store, "name", None) or getattr(state, "store_name", None)
        profile["city"] = getattr(store, "city", None)
        profile["area"] = getattr(store, "area", None)
        profile["category"] = getattr(store, "category", None)

    # 兼容 ManagerHomeBrief / StoreState 扁平字段
    for key in ("store_name", "city", "area", "category"):
        if key not in profile or not profile[key]:
            val = getattr(state, key, None)
            if val:
                profile[key] = val

    kpis = getattr(state, "kpis", None) or {}
    if isinstance(kpis, dict):
        for k in ("gmv", "orders", "ctr", "cvr", "rating"):
            kpi = kpis.get(k)
            if kpi is not None:
                profile[f"kpi_{k}"] = getattr(kpi, "observed_value", kpi)

    profit = getattr(state, "profit", None)
    if profit is not None:
        rate = getattr(profit, "take_home_rate", None)
        if rate is not None:
            profile["take_home_rate"] = rate

    return {k: v for k, v in profile.items() if v is not None}


def infer_audience(agents: Any | None) -> InferredFact | None:
    """B 类推断：基于真实经营数据推断客群类型。

    不再不管输入都返回 office_lunch，而是根据：
    - store.primary_audience 字段（如果商家填过）
    - 品类（快餐/正餐/夜宵/甜品）
    - 订单/客单特征
    做真实推断。
    """
    if agents is None:
        return None
    state = getattr(agents, "store_state", None)
    if state is None:
        return None

    store = getattr(state, "store", None)
    category = getattr(store, "category", None) or ""
    audience_hint = getattr(store, "primary_audience", None) or ""
    area = getattr(store, "area", None) or ""

    # 真实推断逻辑：根据品类 + 客群线索
    if any(kw in category for kw in ("夜宵", "烧烤", "小龙虾")):
        return InferredFact(
            key="primary_audience",
            value="night_snack",
            label="夜间消费人群",
            confidence=0.78,
            confirmed=False,
            source="category_inference",
        )
    if any(kw in audience_hint for kw in ("写字楼", "办公", "白领")):
        return InferredFact(
            key="primary_audience",
            value="office_lunch",
            label="写字楼午餐人群",
            confidence=0.82,
            confirmed=False,
            source="store_profile",
        )
    if any(kw in audience_hint for kw in ("社区", "小区", "居民", "家庭")):
        return InferredFact(
            key="primary_audience",
            value="community",
            label="社区居民",
            confidence=0.80,
            confirmed=False,
            source="store_profile",
        )
    if any(kw in audience_hint for kw in ("学生", "大学", "学校")):
        return InferredFact(
            key="primary_audience",
            value="student",
            label="学生群体",
            confidence=0.80,
            confirmed=False,
            source="store_profile",
        )
    # 基于品类的 fallback 推断
    if any(kw in category for kw in ("快餐", "盖饭", "便当", "工作餐")):
        return InferredFact(
            key="primary_audience",
            value="office_lunch",
            label="写字楼午餐人群（基于品类推断）",
            confidence=0.65,
            confirmed=False,
            source="category_inference",
        )
    if any(kw in category for kw in ("火锅", "烧烤", "正餐", "炒菜")):
        return InferredFact(
            key="primary_audience",
            value="dinner_social",
            label="晚餐社交人群",
            confidence=0.62,
            confirmed=False,
            source="category_inference",
        )
    # 最终 fallback：无法推断，标注低置信度
    return InferredFact(
        key="primary_audience",
        value="unknown",
        label="待确认客群",
        confidence=0.3,
        confirmed=False,
        source="fallback",
    )


def bootstrap_understanding(
    store_id: str,
    *,
    agents: Any | None = None,
    existing: MerchantUnderstanding | None = None,
) -> MerchantUnderstanding:
    """读取后建立/刷新第一版理解；只保留仍未知的缺口。"""
    base = existing or MerchantUnderstanding(store_id=store_id)
    known = extract_known_from_agents(agents)
    base.store_profile = {**base.store_profile, **known}
    base.known_count = len(base.store_profile)

    # B：推断客群（未确认则保留）
    if not any(f.key == "primary_audience" for f in base.inferred):
        fact = infer_audience(agents)
        if fact:
            base.inferred.append(fact)

    # C：缺口 — 已填的从 open_gaps 去掉
    # 注意：open_gaps 为空列表时不要重新生成 default（可能已经全部答完）
    if base.open_gaps is not None and len(base.open_gaps) >= 0 and base.onboarding_stage not in {"connect", "reading"}:
        gaps = list(base.open_gaps)
    elif base.open_gaps:
        gaps = list(base.open_gaps)
    else:
        gaps = default_open_gaps()
    if base.preferences.priority_style:
        gaps = [g for g in gaps if g != "priority_style"]
    if base.constraints.lunch_capacity_per_hour is not None:
        gaps = [g for g in gaps if g != "lunch_capacity"]
    if base.permissions.low_risk_auto_ok:
        gaps = [g for g in gaps if g != "low_risk_auto"]
    if base.constraints.profit_floor_rate is not None:
        gaps = [g for g in gaps if g != "profit_floor"]
    if base.constraints.item_min_price:
        gaps = [g for g in gaps if g != "hero_item_floor_price"]
    if base.permissions.ads_auto_daily_limit_cny is not None:
        gaps = [g for g in gaps if g != "ads_daily_budget"]
    # weekend_strategy 和 competitor_focus 是偏好类，填了 priority_style 后可视为部分覆盖
    if base.preferences.priority_style and "weekend_strategy" in gaps:
        # 没有明确回答周末策略时，默认保留但降优先级（排到最后）
        gaps.remove("weekend_strategy")
        gaps.append("weekend_strategy")
    base.open_gaps = gaps
    base.unknown_count = len(gaps)

    if base.store_profile and base.onboarding_stage in {"connect", "reading"}:
        base.onboarding_stage = "interview" if gaps else "operating"
    if not gaps and base.onboarding_stage != "connect":
        base.onboarding_stage = "operating"

    # MOS + Safe Mode 检查
    from app.services.mos_engine import update_mos_status

    base = update_mos_status(base)

    return base


def empty_shell(store_id: str) -> MerchantUnderstanding:
    return MerchantUnderstanding(
        store_id=store_id,
        preferences=OperatingPreferences(),
        constraints=OperatingConstraints(),
        permissions=PermissionPolicy(),
        open_gaps=default_open_gaps(),
        unknown_count=len(default_open_gaps()),
    )
