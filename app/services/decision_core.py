"""Decision Core V1 — Profit Calculator + Campaign Decision + Profit Diagnosis。

这是 MealKey 第一次拥有"真正能算账、做判断"的经营能力。
不是 LLM 给建议，而是确定性计算 + 结构化决策。
"""

from __future__ import annotations

from typing import Any, Optional

from app.schemas.decision_core import (
    CampaignCalcResult,
    CampaignDecision,
    CampaignOverlay,
    CampaignRule,
    CampaignVerdict,
    MoneyItem,
    ProfitBreakdown,
    ProfitCalcResult,
    ProfitDiagnosisResult,
    ProfitFactorContribution,
)

# ═══════════════════════════════════════════════════════════
# 1. Canonical Profit Calculator
# ═══════════════════════════════════════════════════════════


def calculate_profit(
    *,
    customer_paid: float | None = None,
    platform_subsidy: float | None = None,
    original_price: float | None = None,
    platform_commission: float | None = None,
    merchant_subsidy: float | None = None,
    delivery_fee_borne: float | None = None,
    food_cost: float | None = None,
    packaging_cost: float | None = None,
    ads_allocation: float | None = None,
    refund_compensation: float | None = None,
    orders: int = 1,
    # 来源标记（默认 platform，除非手动标注）
    food_cost_source: str = "missing",
    packaging_cost_source: str = "missing",
) -> ProfitCalcResult:
    """统一利润计算——确定性公式，不靠 LLM。

    Missing Data 是一等状态：
    - 食材/包装缺失 → has_critical_missing=True → safe_to_decide=False
    - 其他字段缺失 → 尽力计算但标注 warning
    """
    breakdown = ProfitBreakdown()

    # 收入侧
    breakdown.customer_paid = MoneyItem(value=customer_paid, source="platform", confidence=0.95)
    breakdown.platform_subsidy = MoneyItem(value=platform_subsidy, source="platform", confidence=0.95)
    breakdown.original_price = MoneyItem(value=original_price, source="platform", confidence=0.95)

    # 成本侧
    breakdown.platform_commission = MoneyItem(
        value=platform_commission, source="platform" if platform_commission is not None else "missing",
        confidence=0.9 if platform_commission is not None else 0.0,
    )
    breakdown.merchant_subsidy = MoneyItem(
        value=merchant_subsidy, source="platform" if merchant_subsidy is not None else "missing",
        confidence=0.9 if merchant_subsidy is not None else 0.0,
    )
    breakdown.delivery_fee_borne = MoneyItem(
        value=delivery_fee_borne, source="platform" if delivery_fee_borne is not None else "missing",
        confidence=0.8 if delivery_fee_borne is not None else 0.0,
    )
    breakdown.food_cost = MoneyItem(
        value=food_cost, source=food_cost_source,
        confidence=0.85 if food_cost is not None and food_cost_source != "missing" else 0.0,
    )
    breakdown.packaging_cost = MoneyItem(
        value=packaging_cost, source=packaging_cost_source,
        confidence=0.85 if packaging_cost is not None and packaging_cost_source != "missing" else 0.0,
    )
    breakdown.ads_allocation = MoneyItem(
        value=ads_allocation, source="platform" if ads_allocation is not None else "missing",
        confidence=0.9 if ads_allocation is not None else 0.0,
    )
    breakdown.refund_compensation = MoneyItem(
        value=refund_compensation, source="platform" if refund_compensation is not None else "missing",
        confidence=0.8 if refund_compensation is not None else 0.0,
    )

    # 检查关键缺失
    missing: list[str] = []
    if food_cost is None:
        missing.append("食材成本")
    if packaging_cost is None:
        missing.append("包装成本")
    breakdown.missing_fields = missing
    breakdown.has_critical_missing = len(missing) > 0

    # 计算——即使部分缺失也尽力算
    # 商家实收 = 顾客实付 + 平台补贴 - 平台佣金 - 商家补贴 - 配送
    revenue_parts = []
    if customer_paid is not None:
        revenue_parts.append(("customer_paid", customer_paid))
    if platform_subsidy is not None:
        revenue_parts.append(("platform_subsidy", platform_subsidy))
    if platform_commission is not None:
        revenue_parts.append(("platform_commission", -platform_commission))
    if merchant_subsidy is not None:
        revenue_parts.append(("merchant_subsidy", -merchant_subsidy))
    if delivery_fee_borne is not None:
        revenue_parts.append(("delivery_fee_borne", -delivery_fee_borne))

    if customer_paid is not None:
        merchant_revenue = customer_paid
        if platform_subsidy is not None:
            merchant_revenue += platform_subsidy
        if platform_commission is not None:
            merchant_revenue -= platform_commission
        if merchant_subsidy is not None:
            merchant_revenue -= merchant_subsidy
        if delivery_fee_borne is not None:
            merchant_revenue -= delivery_fee_borne
        breakdown.merchant_revenue = round(merchant_revenue, 2)
    else:
        merchant_revenue = None

    # 贡献利润 = 实收 - 食材 - 包装 - 广告 - 退款
    if merchant_revenue is not None:
        contribution = merchant_revenue
        if food_cost is not None:
            contribution -= food_cost
        if packaging_cost is not None:
            contribution -= packaging_cost
        if ads_allocation is not None:
            contribution -= ads_allocation
        if refund_compensation is not None:
            contribution -= refund_compensation
        breakdown.contribution_profit = round(contribution, 2)

        # 利润率
        if customer_paid and customer_paid > 0:
            breakdown.contribution_margin = round(contribution / customer_paid, 4)
            breakdown.take_home_rate = round(merchant_revenue / customer_paid, 4)

        breakdown.profit_per_order = round(contribution, 2)

    # 汇总
    total_profit = None
    if breakdown.contribution_profit is not None:
        total_profit = round(breakdown.contribution_profit * orders, 2)

    total_gmv = None
    if customer_paid is not None:
        total_gmv = round(customer_paid * orders, 2)

    warning = ""
    if breakdown.has_critical_missing:
        warning = f"关键数据缺失：{'、'.join(missing)}。利润计算不完整，不建议基于此做经营决策。"

    return ProfitCalcResult(
        breakdown=breakdown,
        orders=orders,
        total_gmv=total_gmv,
        total_contribution_profit=total_profit,
        safe_to_decide=not breakdown.has_critical_missing,
        warning=warning,
    )


# ═══════════════════════════════════════════════════════════
# 2. Campaign Decision Engine
# ═══════════════════════════════════════════════════════════


def calculate_campaign(
    rule: CampaignRule,
    *,
    sku_price: float,
    food_cost: float | None = None,
    packaging_cost: float | None = None,
    platform_commission_rate: float = 0.18,  # 默认 18%
    delivery_fee_borne: float = 0.0,
    avg_daily_orders: int = 100,
    expected_lift_pct: float = 10.0,
    profit_floor: float = 0.17,  # 贡献利润率底线
    existing_discounts: list[dict] | None = None,
    capacity_per_hour: int | None = None,
) -> CampaignDecision:
    """活动测算 + GREEN/YELLOW/RED/BLACK 分档。

    核心原则：Missing Data 是一等状态。
    食材成本缺失 → 无法安全判断 → 返回"需要补充成本数据"。
    """
    calc = CampaignCalcResult()
    missing: list[str] = []

    if food_cost is None:
        missing.append("食材成本")
    if packaging_cost is None:
        missing.append("包装成本")

    calc.missing_data = missing

    # 叠加检查
    overlay = CampaignOverlay(existing_discounts=existing_discounts or [])
    if existing_discounts:
        for disc in existing_discounts:
            if disc.get("time") and rule.applicable_time and disc["time"] == rule.applicable_time:
                overlay.has_overlap = True
                overlay.overlap_detail = f"与现有「{disc.get('name', '优惠')}」存在时段叠加"

    # 如果关键数据缺失 → 无法安全判断
    if missing:
        return CampaignDecision(
            verdict="BLACK",
            strategy="无法安全判断——缺少关键成本数据",
            calc=calc,
            reasoning=f"已算完其他部分，但缺少{'、'.join(missing)}。请先补充成本数据，我会重新计算。",
            confidence=0.0,
        )

    # 计算活动后价格
    if rule.discount_type == "amount":
        discount = rule.discount_value
    else:
        discount = sku_price * rule.discount_value / 100

    final_price = sku_price - discount
    if final_price < 0:
        final_price = 0

    # 活动后的实付
    final_customer_paid = final_price
    # 平台承担部分不影响商家收入，商家承担部分扣减
    final_merchant_revenue = final_price + rule.platform_bears - rule.merchant_bears

    # 平台佣金（按活动后价格）
    commission = final_customer_paid * platform_commission_rate
    final_merchant_revenue -= commission
    final_merchant_revenue -= delivery_fee_borne

    # 贡献利润
    profit_with = final_merchant_revenue - food_cost - packaging_cost
    profit_without = (sku_price * (1 - platform_commission_rate) - delivery_fee_borne
                      - food_cost - packaging_cost)

    calc.final_customer_price = round(final_customer_paid, 2)
    calc.final_merchant_revenue = round(final_merchant_revenue, 2)
    calc.merchant_bears_per_order = round(rule.merchant_bears + (sku_price - final_price - rule.platform_bears), 2)
    calc.profit_per_order_with_campaign = round(profit_with, 2)
    calc.profit_per_order_without_campaign = round(profit_without, 2)
    calc.profit_delta_per_order = round(profit_with - profit_without, 2)

    # 预估量
    calc.expected_order_lift_pct = expected_lift_pct
    expected_orders = int(avg_daily_orders * (1 + expected_lift_pct / 100) * rule.applicable_days)
    calc.expected_total_orders = expected_orders
    calc.expected_total_profit_delta = round(profit_with * expected_orders - profit_without * avg_daily_orders * rule.applicable_days, 2)

    # 碗均价影响
    calc.avg_price_impact = round(final_customer_paid - sku_price, 2)

    # 产能风险
    if capacity_per_hour and expected_orders / rule.applicable_days > capacity_per_hour * 0.8:
        calc.capacity_risk = "severe"
    elif expected_lift_pct > 20:
        calc.capacity_risk = "moderate"

    # 到手率
    if final_customer_paid > 0:
        calc.take_home_rate_after = round(final_merchant_revenue / final_customer_paid, 4)
    calc.profit_floor = profit_floor
    calc.safe_margin_maintained = (
        profit_with / final_customer_paid >= profit_floor if final_customer_paid > 0 else False
    )

    # ═══ 分档决策 ═══

    # BLACK：负利润
    if profit_with <= 0:
        return CampaignDecision(
            verdict="BLACK",
            strategy="禁止参加——活动后单均亏损",
            calc=calc,
            reasoning=f"活动后单均贡献利润 ¥{profit_with:.2f}，参加即亏钱。",
            confidence=0.95,
        )

    # RED：利润率跌破底线
    profit_margin = profit_with / final_customer_paid if final_customer_paid > 0 else 0
    if profit_margin < profit_floor:
        return CampaignDecision(
            verdict="RED",
            strategy="不建议参加——利润率跌破安全线",
            calc=calc,
            reasoning=f"活动后贡献利润率 {profit_margin:.1%}，低于安全线 {profit_floor:.0%}。",
            confidence=0.9,
        )

    # GREEN：利润安全 + 有正增量
    if calc.safe_margin_maintained and calc.profit_delta_per_order >= -1.0:
        strategy = "建议参加"
        guardrails = ["贡献利润率", "碗均价", "CVR"]
        stop_conds = [f"贡献利润率 < {profit_floor:.0%} 则停止", "碗均价降幅 > 15% 则停止"]

        # 产能风险 → 降为 YELLOW
        if calc.capacity_risk == "severe":
            return CampaignDecision(
                verdict="YELLOW",
                strategy="建议参加但限量测试——产能有瓶颈风险",
                scope="仅午餐时段",
                test_duration_days=min(rule.applicable_days, 3),
                test_max_orders=capacity_per_hour * 3 if capacity_per_hour else 200,
                guardrail_metrics=guardrails + ["出餐时间"],
                stop_conditions=stop_conds + ["出餐超时率 > 10% 则停止"],
                calc=calc,
                reasoning=f"活动利润安全（利润率 {profit_margin:.1%}），但预估订单量接近产能上限。",
                confidence=0.82,
            )

        return CampaignDecision(
            verdict="GREEN",
            strategy=strategy,
            guardrail_metrics=guardrails,
            stop_conditions=stop_conds,
            calc=calc,
            reasoning=(
                f"活动后单均利润 ¥{profit_with:.2f}（利润率 {profit_margin:.1%}），"
                f"高于安全线 {profit_floor:.0%}。"
                f"预计 {rule.applicable_days} 天增收利润 ¥{calc.expected_total_profit_delta:.0f}。"
            ),
            confidence=0.88,
        )

    # YELLOW：利润率安全但单均利润下降较多
    return CampaignDecision(
        verdict="YELLOW",
        strategy="建议限量测试",
        scope="仅午餐时段",
        test_duration_days=min(rule.applicable_days, 3),
        test_max_orders=200,
        guardrail_metrics=["贡献利润率", "碗均价", "CVR", "复购率"],
        stop_conditions=[
            f"贡献利润率 < {profit_floor:.0%} 则停止",
            "碗均价降幅 > 15% 则停止",
            "复购率下降则停止",
        ],
        calc=calc,
        reasoning=(
            f"活动后单均利润 ¥{profit_with:.2f}（利润率 {profit_margin:.1%}），"
            f"利润率安全但单均利润下降 ¥{abs(calc.profit_delta_per_order):.2f}。"
            f"建议先限量 3 天测试，观察订单增长是否弥补利润下降。"
        ),
        confidence=0.75,
    )


# ═══════════════════════════════════════════════════════════
# 3. Profit Diagnosis
# ═══════════════════════════════════════════════════════════


def diagnose_profit_change(
    *,
    current: dict[str, float | None],
    baseline: dict[str, float | None],
    orders_current: int | None = None,
    orders_baseline: int | None = None,
) -> ProfitDiagnosisResult:
    """利润归因拆解——回答"为什么利润变差"。

    固定拆成 8 个贡献项，每个算 delta 金额。
    不用 LLM——纯确定性计算。
    """
    factors: list[ProfitFactorContribution] = []

    # 定义因子：key → (label, is_cost)
    # is_cost=True 意味着该因子增加 → 利润减少（delta 取反）
    factor_defs = [
        ("customer_paid", "顾客实付", False),
        ("platform_subsidy", "平台补贴", False),
        ("platform_commission", "平台佣金", True),
        ("merchant_subsidy", "商家补贴", True),
        ("delivery_fee", "配送费", True),
        ("food_cost", "食材成本", True),
        ("packaging_cost", "包装成本", True),
        ("ads_spend", "广告支出", True),
        ("refund_cost", "退款赔付", True),
    ]

    total_delta = 0.0
    missing: list[str] = []

    for key, label, is_cost in factor_defs:
        curr = current.get(key)
        base = baseline.get(key)

        if curr is None or base is None:
            if key in ("food_cost", "packaging_cost"):
                missing.append(label)
            continue

        delta_val = curr - base
        if is_cost:
            delta_val = -delta_val  # 成本增加 → 利润减少

        pct = None
        if base != 0:
            pct = round((curr - base) / abs(base) * 100, 1)

        factors.append(ProfitFactorContribution(
            factor=key,
            label=label,
            delta=round(delta_val, 2),
            delta_pct=pct,
        ))
        total_delta += delta_val

    # 订单量影响
    if orders_current is not None and orders_baseline is not None and orders_baseline > 0:
        order_delta_pct = (orders_current - orders_baseline) / orders_baseline
        # 估算订单量对利润的贡献（用基线单均利润 × 订单增量）
        base_profit_per_order = 0
        if baseline.get("customer_paid") and baseline.get("food_cost"):
            base_profit_per_order = baseline["customer_paid"] - baseline.get("food_cost", 0) - baseline.get("packaging_cost", 0)
        order_profit_delta = round(base_profit_per_order * (orders_current - orders_baseline), 2)
        factors.append(ProfitFactorContribution(
            factor="order_volume",
            label="订单量",
            delta=order_profit_delta,
            delta_pct=round(order_delta_pct * 100, 1),
        ))
        total_delta += order_profit_delta

    # 找主因
    factors.sort(key=lambda f: abs(f.delta), reverse=True)
    if factors:
        factors[0].is_primary = True
        primary = factors[0]
        direction = "增加" if primary.delta > 0 else "减少"
        primary_cause = f"主要是{primary.label}{direction} ¥{abs(primary.delta):.0f}"

        if total_delta < 0:
            conclusion = f"利润下降 ¥{abs(total_delta):.0f}。{primary_cause}。"
        elif total_delta > 0:
            conclusion = f"利润增长 ¥{total_delta:.0f}。{primary_cause}。"
        else:
            conclusion = "利润基本持平。"
    else:
        primary_cause = "数据不足，无法归因"
        conclusion = "缺少关键数据，无法判断利润变化原因。"

    return ProfitDiagnosisResult(
        total_profit_delta=round(total_delta, 2),
        factors=factors,
        primary_cause=primary_cause,
        conclusion=conclusion,
        confidence=0.85 if not missing else 0.5,
        missing_data=missing,
    )
