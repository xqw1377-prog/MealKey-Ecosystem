"""Minimum Operating State (MOS) + Safe Mode 引擎。

材料定义：满足 MOS 后 MealKey 就可以开始经营。
缺关键信息时进入 Safe Mode——可以分析、回复评价、监控竞争，
但不自动执行可能影响利润的活动/价格动作。

MOS 必须项（材料 §一启动前清单）：
1. 平台连接成功（能读数据）
2. 经营原则（priority_style：利润/单量/排名/平衡）
3. 风险边界（ads_auto_daily_limit_cny + low_risk_auto_ok）
4. 关键约束（lunch_capacity_per_hour 或 profit_floor_rate 至少有一个）

Safe Mode 行为：
- 允许：分析、回复评价、监控竞争、商品建议
- 禁止：自动执行活动参加/价格调整/投流加预算
"""

from __future__ import annotations

from app.schemas.merchant_understanding import MerchantUnderstanding

# MOS 聚合字段 → 访谈 gap key（前端/Ask Engine 用 gap，不用 MOS 名当提交 key）
MOS_TO_GAPS: dict[str, list[str]] = {
    "platform_connected": [],
    "priority_style": ["priority_style"],
    "risk_boundary": ["low_risk_auto"],
    "key_constraint": ["lunch_capacity", "profit_floor", "hero_item_floor_price"],
}

# MOS 必须字段定义：(field_key, check_fn, blocking_desc)
_MOS_FIELDS: list[tuple[str, object, str]] = []


def _mos_check(name: str):
    """注册一个 MOS 检查项。"""

    def decorator(fn):
        _MOS_FIELDS.append((name, fn, fn.__doc__ or ""))
        return fn

    return decorator


@_mos_check("platform_connected")
def _check_platform(mu: MerchantUnderstanding) -> bool:
    """平台连接"""
    if getattr(mu, "platform_connected", False):
        return True
    profile = mu.store_profile or {}
    return bool(profile.get("platform_connected"))


@_mos_check("priority_style")
def _check_priority(mu: MerchantUnderstanding) -> bool:
    """经营原则"""
    return mu.preferences.priority_style is not None


@_mos_check("risk_boundary")
def _check_risk(mu: MerchantUnderstanding) -> bool:
    """风险边界（至少知道低风险能不能自动做）"""
    return mu.permissions.low_risk_auto_ok is not None


@_mos_check("key_constraint")
def _check_constraint(mu: MerchantUnderstanding) -> bool:
    """关键约束（产能或利润底线至少有一个）"""
    return (
        mu.constraints.lunch_capacity_per_hour is not None
        or mu.constraints.profit_floor_rate is not None
        or bool(mu.constraints.item_min_price)
    )


def check_mos(mu: MerchantUnderstanding) -> tuple[bool, list[str]]:
    """检查 Minimum Operating State 是否满足。

    返回 (satisfied, blocking_fields)。
    """
    blocking: list[str] = []
    for name, fn, desc in _MOS_FIELDS:
        try:
            if not fn(mu):
                blocking.append(name)
        except Exception:  # noqa: BLE001
            blocking.append(name)
    return (len(blocking) == 0, blocking)


def mos_gap_keys_for(mu: MerchantUnderstanding, blocking: list[str] | None = None) -> list[str]:
    """把 MOS 阻塞项展开成访谈 gap key，并与 open_gaps 求交。"""
    fields = blocking if blocking is not None else list(mu.mos_blocking_fields or [])
    expanded: list[str] = []
    for field in fields:
        mapped = MOS_TO_GAPS.get(field)
        if mapped is None:
            expanded.append(field)
        else:
            expanded.extend(mapped)
    open_gaps = list(mu.open_gaps or [])
    if open_gaps:
        open_set = set(open_gaps)
        ordered = [key for key in expanded if key in open_set]
        if ordered:
            return list(dict.fromkeys(ordered))
        leftover = [key for key in open_gaps if key in set(expanded) or key in MOS_TO_GAPS]
        if leftover:
            return leftover
        return open_gaps[:1]
    return list(dict.fromkeys(expanded))


def gap_blocks_mos(gap_key: str, mu: MerchantUnderstanding) -> bool:
    """访谈缺口是否对应仍未满足的 MOS 项。"""
    key = str(gap_key or "").strip()
    if not key:
        return False
    blocking = list(mu.mos_blocking_fields or [])
    if key in blocking:
        return True
    for field in blocking:
        if key in MOS_TO_GAPS.get(field, []):
            return True
    return False


def determine_system_mode(mu: MerchantUnderstanding) -> str:
    """决定系统模式：operating 或 safe。

    MOS 满足 → operating
    MOS 不满足 → safe（缺关键信息，禁止自动执行利润相关动作）
    """
    satisfied, _ = check_mos(mu)
    return "operating" if satisfied else "safe"


SAFE_MODE_BLOCKED_ACTIONS = {
    "join_lunch_campaign",
    "match_competitor_promo",
    "launch_value_bundle_promo",
    "boost_hero_item_ads",
    "shift_ads_to_high_cvr_item",
    "store_discount",
    "adjust_price_value",
}

SAFE_MODE_ALLOWED_ACTIONS = {
    "batch_reply_negative_reviews",
    "reply_ordinary_reviews",
    "publish_service_reply_scripts",
    "fix_top_review_theme",
    "pin_positive_review_themes",
    "refresh_hero_image",
    "change_main_image",
    "change_title",
    "menu_patch",
    "menu_cleanup",
    "add_set_meal",
}


def is_action_allowed_in_safe_mode(action_type: str) -> bool:
    """判断某个动作在 Safe Mode 下是否允许执行。"""
    if action_type in SAFE_MODE_ALLOWED_ACTIONS:
        return True
    if action_type in SAFE_MODE_BLOCKED_ACTIONS:
        return False
    return False


def update_mos_status(mu: MerchantUnderstanding) -> MerchantUnderstanding:
    """更新 MerchantUnderstanding 的 MOS 状态和 system_mode。"""
    satisfied, blocking = check_mos(mu)
    mu.mos_satisfied = satisfied
    mu.mos_blocking_fields = blocking
    mu.mos_gap_keys = mos_gap_keys_for(mu, blocking)
    mu.system_mode = "operating" if satisfied else "safe"  # type: ignore
    return mu
