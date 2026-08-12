"""自然语言 → 偏好 / 约束 / 权限更新（设置即对话）。"""

from __future__ import annotations

import re
from typing import Optional

from app.schemas.merchant_understanding import MerchantUnderstanding, UnderstandingUpdateResult


def apply_nl_update(understanding: MerchantUnderstanding, text: str) -> Optional[UnderstandingUpdateResult]:
    """识别设置类原话；无法识别返回 None。"""
    raw = (text or "").strip()
    if not raw:
        return None

    changed: list[str] = []
    replies: list[str] = []

    # —— 经营原则 ——
    if re.search(r"(利润优先|先赚钱|别.*(冲|冲单|瞎冲)|少点优惠|宁愿少点单)", raw):
        understanding.preferences.priority_style = "profit"
        understanding.preferences.promotion_aggressiveness = min(
            understanding.preferences.promotion_aggressiveness, 0.35
        )
        changed.append("priority_style")
        replies.append("明白。以后经营原则：利润优先，不为了 GMV 做明显亏损的活动。")
        _close_gap(understanding, "priority_style")

    elif re.search(r"(冲单量|订单优先|多(点|一点)?订单|先把量做起来|以订单为)", raw):
        understanding.preferences.priority_style = "orders"
        understanding.preferences.promotion_aggressiveness = max(
            understanding.preferences.promotion_aggressiveness, 0.65
        )
        changed.append("priority_style")
        replies.append("明白。我会更积极争量，同时盯住明显亏损的活动。")
        _close_gap(understanding, "priority_style")

    elif re.search(r"(提高排名|冲排名|排名优先)", raw):
        understanding.preferences.priority_style = "rank"
        changed.append("priority_style")
        replies.append("明白。排名相关动作会优先，但仍避开不可逆的大亏。")
        _close_gap(understanding, "priority_style")

    elif re.search(r"(交给你|你平衡|都交给我|你看着办|你帮我平衡)", raw) or (
        "平衡" in raw and len(raw) <= 12
    ):
        understanding.preferences.priority_style = "balanced"
        changed.append("priority_style")
        replies.append("好。我会在利润与订单之间自己平衡，偏离太大时再找你。")
        _close_gap(understanding, "priority_style")

    # —— 周末更积极 ——
    if re.search(r"周末.*(大胆|积极|冲)|周末可以", raw):
        understanding.preferences.weekend_more_aggressive = True
        changed.append("weekend_more_aggressive")
        replies.append("明白。工作日偏稳，周末允许更积极争量。")

    # —— 厨房产能 ——
    m = re.search(r"(?:一小时|每小时|小时).*?(\d+)\s*单|(?:最多|顶多|顶不住).*?(\d+)\s*单", raw)
    if m and ("午餐" in raw or "厨房" in raw or "高峰" in raw or "忙" in raw or "单" in raw):
        cap = float(m.group(1) or m.group(2))
        understanding.constraints.lunch_capacity_per_hour = cap
        changed.append("lunch_capacity")
        soft = max(1, int(cap * 0.9))
        replies.append(f"明白。午餐小时订单接近 {soft} 单时，我会开始降低激进投流。")
        _close_gap(understanding, "lunch_capacity")

    # —— 成本 / 最低价 ——
    m = re.search(r"(.+?)(?:成本|进货).*?(?:现在|是|到)?\s*(\d+(?:\.\d+)?)\s*块?", raw)
    if m and ("成本" in raw or "进货" in raw):
        name = m.group(1).strip(" ，,的")[-20:]
        cost = float(m.group(2))
        understanding.constraints.item_cost_floor[name] = cost
        changed.append(f"cost:{name}")
        replies.append(f"收到。{name}成本已更新为 {cost:g} 元，我会重新评估活动和底价。")

    if re.search(r"(不太清楚|不知道).{0,8}(帮我算|你算|慢慢)", raw) or (
        understanding.last_interview_key == "hero_item_floor_price"
        and re.search(r"(不清楚|不知道|你算)", raw)
    ):
        understanding.constraints.notes = (
            f"{understanding.constraints.notes} 招牌最低价待系统按利润校正".strip()
        )
        changed.append("hero_item_floor_price")
        replies.append("好。我先按真实利润慢慢估算安全底价，算清楚后再告诉你。")
        _close_gap(understanding, "hero_item_floor_price")

    if understanding.last_interview_key == "competitor_focus" and re.search(
        r"(你先|帮我判断|最危险)", raw
    ):
        understanding.store_profile["competitor_focus"] = "ai_pick"
        changed.append("competitor_focus")
        replies.append("好。我先按商圈重叠度和抢单强度判断最危险的竞品，有变化再找你。")
        _close_gap(understanding, "competitor_focus")

    m = re.search(r"(?:最低|不能低于|亏.*)?\s*(\d+(?:\.\d+)?)\s*(?:块|元)?", raw)
    if m and ("最低" in raw or "不会亏" in raw or "底线" in raw) and "广告" not in raw and "投流" not in raw:
        # 若前文带菜名则写入 min_price；否则记 notes
        price = float(m.group(1))
        dish = None
        dm = re.search(r"([\u4e00-\u9fff]{2,12}(?:饭|面|套餐|餐))", raw)
        if dm:
            dish = dm.group(1)
            understanding.constraints.item_min_price[dish] = price
            changed.append(f"min_price:{dish}")
            replies.append(f"好，{dish} 先按 {price:g} 元作为安全底线，后续按真实利润校正。")
            _close_gap(understanding, "hero_item_floor_price")
        elif "min_price_default" not in changed:
            understanding.constraints.notes = (understanding.constraints.notes + f" 默认可接受底价约{price:g}元").strip()
            changed.append("min_price_default")
            replies.append(f"好，我先按 {price:g} 元作为安全底线参考。")
            _close_gap(understanding, "hero_item_floor_price")

    # —— 访谈选项：提高利润 / 多一点订单… ——
    if understanding.last_interview_key == "priority_style" or re.search(
        r"^(A|B|C|D)[\.、\s]", raw, re.I
    ):
        if re.search(r"提高利润|先赚钱|^B\b", raw, re.I):
            understanding.preferences.priority_style = "profit"
            changed.append("priority_style")
            replies.append("明白。以后经营原则：利润优先，不为了 GMV 做明显亏损的活动。")
            _close_gap(understanding, "priority_style")
        elif re.search(r"多一点订单|多点订单|^A\b", raw, re.I):
            understanding.preferences.priority_style = "orders"
            changed.append("priority_style")
            replies.append("明白。我会更积极争量，同时盯住明显亏损的活动。")
            _close_gap(understanding, "priority_style")
        elif re.search(r"提高排名|^C\b", raw, re.I):
            understanding.preferences.priority_style = "rank"
            changed.append("priority_style")
            replies.append("明白。排名相关动作会优先，但仍避开不可逆的大亏。")
            _close_gap(understanding, "priority_style")
        elif re.search(r"平衡|交给|你帮我|^D\b", raw, re.I):
            understanding.preferences.priority_style = "balanced"
            changed.append("priority_style")
            replies.append("好。我会在利润与订单之间自己平衡，偏离太大时再找你。")
            _close_gap(understanding, "priority_style")

    # —— 低风险自动 ——
    if re.search(r"先不要|先都问我|不要自动", raw) and (
        understanding.last_interview_key == "low_risk_auto" or "自动" in raw or "好评" in raw
    ):
        understanding.permissions.low_risk_auto_ok = False
        understanding.permissions.auto_reply_good_reviews = False
        changed.append("low_risk_auto")
        replies.append("好。低风险事项我也会先问你，再动手。")
        _close_gap(understanding, "low_risk_auto")
    elif re.search(r"(可以|允许|同意).*(自动|直接|你处理)|普通好评.*(可以|你)|监控.*(可以|你)", raw) or (
        understanding.last_interview_key == "low_risk_auto"
        and re.search(r"^(可以|没问题|允许|同意|行|好的|ok|A\b)", raw, re.I)
    ):
        understanding.permissions.low_risk_auto_ok = True
        understanding.permissions.auto_reply_good_reviews = True
        understanding.permissions.monitor_promo_expiry = True
        understanding.permissions.monitor_stockout = True
        understanding.permissions.monitor_competitors = True
        changed.append("low_risk_auto")
        replies.append("好。这些低风险事项我直接处理，需要你时再出现。")
        _close_gap(understanding, "low_risk_auto")

    # —— 到手率/利润底线 ——
    m = re.search(r"(?:到手|到手率|利润率|利润底线)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*%?", raw)
    if m:
        val = float(m.group(1))
        if val > 1:
            val = val / 100.0
        understanding.constraints.profit_floor_rate = val
        changed.append("profit_floor_rate")
        replies.append(f"好。到手率底线设为 {val*100:.0f}%，低于这个线的活动我不会参加。")
        _close_gap(understanding, "profit_floor")

    # —— 投流权限扩展：不再强制要求"广告/投流"前置词 ——
    # 场景1：带"广告/投流"的明确表述（原有逻辑）
    m_ads = re.search(r"(?:广告|投流|推广)[^0-9]{0,16}(\d+(?:\.\d+)?)\s*(?:元|块)?", raw)
    # 场景2：访谈上下文 + 金额 + 权限词（"以后300以内你自己决定"）
    m_ctx = None
    if understanding.last_interview_key == "ads_daily_budget":
        m_ctx = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块)?", raw)
    # 场景3：带预算词 + 金额 + 权限词
    m_budget = re.search(r"(?:每天|每日|预算|花)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*(?:元|块)?", raw)
    if (m_ads or m_ctx or m_budget) and re.search(r"(以内|自己|自动|你定|你决定|授权|花掉|帮你花)", raw):
        limit = float((m_ads or m_ctx or m_budget).group(1))
        understanding.permissions.ads_auto_daily_limit_cny = limit
        changed.append("ads_auto_daily_limit_cny")
        replies.append(f"好的，已更新投流权限：每天 {limit:g} 元以内我自己调整，超过再问你。")
        _close_gap(understanding, "ads_daily_budget")

    # —— 周末策略 ——
    if understanding.last_interview_key == "weekend_strategy" or re.search(r"周末|礼拜天|休息日", raw):
        if re.search(r"激进|大胆|冲一冲|放量", raw):
            understanding.preferences.weekend_more_aggressive = True
            changed.append("weekend_strategy")
            replies.append("明白。工作日稳，周末可以更激进争量。")
            _close_gap(understanding, "weekend_strategy")
        elif re.search(r"保守|稳一点|少做|一样", raw):
            understanding.preferences.weekend_more_aggressive = False
            changed.append("weekend_strategy")
            replies.append("明白。周末和工作日保持同样节奏。")
            _close_gap(understanding, "weekend_strategy")

    # —— 重点竞品 ——
    if understanding.last_interview_key == "competitor_focus" or re.search(
        r"(旁边那家|重点盯|特别在意).{0,12}", raw
    ):
        name = raw.strip()
        m = re.search(r"(?:盯|在意|关注|怕).{0,4}([\u4e00-\u9fffA-Za-z0-9]{2,20})", raw)
        if m:
            name = m.group(1)
        if 1 < len(name) <= 40 and not re.search(r"^(没问题|可以|好的)$", name):
            understanding.preferences.notes = (
                f"{understanding.preferences.notes} 重点竞品：{name}".strip()
            )
            understanding.store_profile["competitor_focus"] = name
            changed.append("competitor_focus")
            replies.append(f"好，我会重点盯「{name}」的价格、活动和主图变化。")
            _close_gap(understanding, "competitor_focus")

    # —— B 类确认 ——
    if re.search(r"^(没问题|对的|是的|没错)$", raw) or ("客群" in raw and "没问题" in raw):
        for fact in understanding.inferred:
            if not fact.confirmed:
                fact.confirmed = True
                changed.append(f"confirm:{fact.key}")
                replies.append(f"好，我按「{fact.label or fact.key}」继续经营。")
                break

    if not changed:
        return None

    if not understanding.open_gaps and understanding.onboarding_stage == "interview":
        understanding.onboarding_stage = "operating"

    understanding.unknown_count = len(understanding.open_gaps)
    reply = "\n".join(dict.fromkeys(replies))  # 去重保序
    return UnderstandingUpdateResult(
        understanding=understanding,
        changed_keys=changed,
        reply=reply or "已记下，我会按这个原则经营。",
    )


def _close_gap(understanding: MerchantUnderstanding, key: str) -> None:
    understanding.open_gaps = [g for g in understanding.open_gaps if g != key]
    if understanding.last_interview_key == key:
        understanding.last_interview_key = None
