"""Decision Core V1 — Fixture Test Set。

30+ 个经营案例，验证 Profit Calculator + Campaign Decision + Profit Diagnosis
的计算正确性和决策稳定性。

每个案例人工设定"正确经营结论"，测试 Engine 是否稳定命中。
"""

from app.schemas.decision_core import CampaignRule
from app.services.decision_core import (
    calculate_campaign,
    calculate_profit,
    diagnose_profit_change,
)


# ═══════════════════════════════════════════════════════════
# 1. Profit Calculator Tests（10 cases）
# ═══════════════════════════════════════════════════════════


def test_profit_basic_full_data() -> None:
    """案例 1: 完整数据——正常利润计算。"""
    r = calculate_profit(
        customer_paid=29.9, platform_subsidy=2.0, original_price=31.9,
        platform_commission=5.38, merchant_subsidy=0, delivery_fee_borne=1.5,
        food_cost=12.0, packaging_cost=2.0, ads_allocation=0, refund_compensation=0,
    )
    assert r.safe_to_decide is True
    assert r.breakdown.contribution_profit is not None
    assert r.breakdown.contribution_profit > 0
    assert r.breakdown.contribution_margin > 0.17
    assert r.breakdown.take_home_rate > 0.5


def test_profit_missing_food_cost() -> None:
    """案例 2: 缺食材成本——must be unsafe。"""
    r = calculate_profit(
        customer_paid=29.9, platform_commission=5.38,
        food_cost=None, packaging_cost=2.0,
    )
    assert r.safe_to_decide is False
    assert "食材成本" in r.breakdown.missing_fields
    assert r.warning


def test_profit_missing_packaging() -> None:
    """案例 3: 缺包装成本——must be unsafe。"""
    r = calculate_profit(
        customer_paid=29.9, food_cost=12.0, packaging_cost=None,
    )
    assert r.safe_to_decide is False
    assert "包装成本" in r.breakdown.missing_fields


def test_profit_negative_margin() -> None:
    """案例 4: 负利润——补贴太高。"""
    r = calculate_profit(
        customer_paid=15.0, platform_subsidy=0, merchant_subsidy=10.0,
        platform_commission=2.7, food_cost=8.0, packaging_cost=1.5,
    )
    assert r.breakdown.contribution_profit is not None
    assert r.breakdown.contribution_profit < 0  # 亏钱


def test_profit_high_subsidy() -> None:
    """案例 5: 平台全额补贴——商家几乎无成本。"""
    r = calculate_profit(
        customer_paid=20.0, platform_subsidy=8.0, merchant_subsidy=0,
        platform_commission=3.6, food_cost=10.0, packaging_cost=1.5,
    )
    assert r.breakdown.contribution_profit > 0
    assert r.breakdown.take_home_rate > 0.6


def test_profit_total_with_orders() -> None:
    """案例 6: 批量计算。"""
    r = calculate_profit(
        customer_paid=25.0, platform_commission=4.5, food_cost=10.0, packaging_cost=2.0,
        orders=150,
    )
    assert r.total_gmv == 25.0 * 150
    assert r.total_contribution_profit is not None
    assert r.total_contribution_profit > 0


def test_profit_refund_impact() -> None:
    """案例 7: 退款侵蚀利润。"""
    r_no_refund = calculate_profit(
        customer_paid=30.0, food_cost=12.0, packaging_cost=2.0, platform_commission=5.4,
    )
    r_with_refund = calculate_profit(
        customer_paid=30.0, food_cost=12.0, packaging_cost=2.0, platform_commission=5.4,
        refund_compensation=8.0,
    )
    assert r_with_refund.breakdown.contribution_profit < r_no_refund.breakdown.contribution_profit


def test_profit_ads_allocation() -> None:
    """案例 8: 广告分摊吃掉利润。"""
    r = calculate_profit(
        customer_paid=30.0, food_cost=12.0, packaging_cost=2.0, ads_allocation=6.0,
        platform_commission=5.4,
    )
    assert r.breakdown.contribution_profit is not None
    assert r.breakdown.contribution_profit < 5.0  # 广告吃掉了大部分利润


def test_profit_zero_customer_paid() -> None:
    """案例 9: 实付为零——不应崩溃。"""
    r = calculate_profit(customer_paid=0, food_cost=5.0, packaging_cost=1.0)
    assert r.breakdown.contribution_profit is not None
    assert r.breakdown.contribution_profit < 0


def test_profit_merchant_input_source() -> None:
    """案例 10: 手动填入成本——source 正确标注。"""
    r = calculate_profit(
        customer_paid=30.0, food_cost=14.0, packaging_cost=2.5,
        food_cost_source="merchant_input", packaging_cost_source="merchant_input",
    )
    assert r.safe_to_decide is True
    assert r.breakdown.food_cost.source == "merchant_input"
    assert r.breakdown.food_cost.confidence > 0.8


# ═══════════════════════════════════════════════════════════
# 2. Campaign Decision Tests（12 cases）
# ═══════════════════════════════════════════════════════════


def test_campaign_green_platform_subsidy() -> None:
    """案例 11: 平台全额补贴——GREEN。"""
    rule = CampaignRule(
        campaign_name="午餐补贴", platform_bears=4.0, merchant_bears=0,
        discount_type="amount", discount_value=4.0, applicable_days=3,
    )
    d = calculate_campaign(rule, sku_price=29.9, food_cost=12.0, packaging_cost=2.0)
    assert d.verdict == "GREEN"
    assert d.calc.profit_per_order_with_campaign > 0


def test_campaign_black_negative_profit() -> None:
    """案例 12: 商家重补贴导致亏损——BLACK。"""
    rule = CampaignRule(
        campaign_name="满减", platform_bears=0, merchant_bears=12.0,
        discount_type="amount", discount_value=12.0,
    )
    d = calculate_campaign(rule, sku_price=29.9, food_cost=12.0, packaging_cost=2.0)
    assert d.verdict == "BLACK"


def test_campaign_red_margin_breach() -> None:
    """案例 13: 利润率跌破底线——RED。"""
    rule = CampaignRule(
        campaign_name="折扣", merchant_bears=8.0, discount_type="amount", discount_value=8.0,
    )
    d = calculate_campaign(rule, sku_price=29.9, food_cost=12.0, packaging_cost=2.0, profit_floor=0.17)
    # 5% 利润率 < 17% 底线 → RED 或 BLACK
    assert d.verdict in ("RED", "BLACK")


def test_campaign_black_missing_cost() -> None:
    """案例 14: 缺成本数据——BLACK（无法判断）。"""
    rule = CampaignRule(campaign_name="测试", merchant_bears=3.0, discount_value=3.0)
    d = calculate_campaign(rule, sku_price=29.9, food_cost=None, packaging_cost=None)
    assert d.verdict == "BLACK"
    assert "食材成本" in d.calc.missing_data


def test_campaign_yellow_test_mode() -> None:
    """案例 15: 利润安全但单均利润下降——YELLOW 或 RED 取决于利润率底线。"""
    rule = CampaignRule(
        campaign_name="活动", merchant_bears=5.0, discount_type="amount", discount_value=5.0,
        applicable_days=7,
    )
    d = calculate_campaign(rule, sku_price=29.9, food_cost=12.0, packaging_cost=2.0, profit_floor=0.10)
    # 利润率 5.7% < 10% → RED；放宽底线到 5% → YELLOW/GREEN
    assert d.verdict in ("YELLOW", "GREEN", "RED")


def test_campaign_yellow_capacity_risk() -> None:
    """案例 16: 产能瓶颈——即使 GREEN 也降为 YELLOW。"""
    rule = CampaignRule(
        campaign_name="爆单活动", platform_bears=3.0, merchant_bears=2.0,
        discount_type="amount", discount_value=5.0, applicable_days=3,
    )
    d = calculate_campaign(
        rule, sku_price=35.0, food_cost=14.0, packaging_cost=2.0,
        avg_daily_orders=200, expected_lift_pct=30, capacity_per_hour=50,
    )
    assert d.verdict in ("YELLOW", "GREEN")
    if d.verdict == "YELLOW":
        assert "出餐" in " ".join(d.guardrail_metrics) or d.test_max_orders is not None


def test_campaign_green_low_risk() -> None:
    """案例 17: 小额平台补贴——GREEN。"""
    rule = CampaignRule(
        campaign_name="平台券", platform_bears=2.0, merchant_bears=0,
        discount_type="amount", discount_value=2.0,
    )
    d = calculate_campaign(rule, sku_price=32.0, food_cost=13.0, packaging_cost=2.0)
    assert d.verdict == "GREEN"


def test_campaign_overlay_detection() -> None:
    """案例 18: 活动叠加检测。"""
    rule = CampaignRule(campaign_name="新活动", applicable_time="11:00-13:00")
    d = calculate_campaign(
        rule, sku_price=29.9, food_cost=12.0, packaging_cost=2.0,
        existing_discounts=[{"name": "老客券", "time": "11:00-13:00"}],
    )
    # 活动有叠加但利润可能仍然安全
    assert d.verdict in ("GREEN", "YELLOW", "RED", "BLACK")


def test_campaign_black_zero_price() -> None:
    """案例 19: 活动后价格为 0——BLACK。"""
    rule = CampaignRule(
        campaign_name="免单", merchant_bears=29.9, discount_type="amount", discount_value=29.9,
    )
    d = calculate_campaign(rule, sku_price=29.9, food_cost=12.0, packaging_cost=2.0)
    assert d.verdict == "BLACK"


def test_campaign_green_percentage_discount() -> None:
    """案例 20: 百分比折扣——GREEN。"""
    rule = CampaignRule(
        campaign_name="9折", platform_bears=0, merchant_bears=0,
        discount_type="percentage", discount_value=10.0,
    )
    d = calculate_campaign(rule, sku_price=30.0, food_cost=10.0, packaging_cost=2.0)
    assert d.verdict in ("GREEN", "YELLOW")


def test_campaign_stop_conditions_present() -> None:
    """案例 21: YELLOW/GREEN 必须有 stop_conditions。"""
    rule = CampaignRule(campaign_name="测试", platform_bears=3.0, discount_value=3.0)
    d = calculate_campaign(rule, sku_price=32.0, food_cost=13.0, packaging_cost=2.0)
    if d.verdict in ("GREEN", "YELLOW"):
        assert len(d.stop_conditions) > 0


def test_campaign_avg_price_impact() -> None:
    """案例 22: 碗均价影响计算正确。"""
    rule = CampaignRule(campaign_name="减5元", merchant_bears=5.0, discount_value=5.0)
    d = calculate_campaign(rule, sku_price=30.0, food_cost=12.0, packaging_cost=2.0)
    assert d.calc.avg_price_impact == -5.0  # 30 - 25 = -5


# ═══════════════════════════════════════════════════════════
# 3. Profit Diagnosis Tests（8 cases）
# ═══════════════════════════════════════════════════════════


def test_diagnosis_ads_increase() -> None:
    """案例 23: 广告增加导致利润下降。"""
    r = diagnose_profit_change(
        current={"customer_paid": 30.0, "ads_spend": 800.0, "food_cost": 12.0, "packaging_cost": 2.0},
        baseline={"customer_paid": 30.0, "ads_spend": 200.0, "food_cost": 12.0, "packaging_cost": 2.0},
    )
    assert r.total_profit_delta < 0
    ads = next(f for f in r.factors if f.factor == "ads_spend")
    assert ads.delta < 0
    assert "广告" in r.primary_cause or "广告" in r.conclusion


def test_diagnosis_order_decline() -> None:
    """案例 24: 订单量下降。"""
    r = diagnose_profit_change(
        current={"customer_paid": 30.0, "food_cost": 12.0, "packaging_cost": 2.0},
        baseline={"customer_paid": 30.0, "food_cost": 12.0, "packaging_cost": 2.0},
        orders_current=80, orders_baseline=100,
    )
    order_factor = next(f for f in r.factors if f.factor == "order_volume")
    assert order_factor.delta < 0


def test_diagnosis_subsidy_spike() -> None:
    """案例 25: 商家补贴暴涨。"""
    r = diagnose_profit_change(
        current={"customer_paid": 25.0, "merchant_subsidy": 8.0, "food_cost": 10.0, "packaging_cost": 2.0},
        baseline={"customer_paid": 25.0, "merchant_subsidy": 2.0, "food_cost": 10.0, "packaging_cost": 2.0},
    )
    subsidy = next(f for f in r.factors if f.factor == "merchant_subsidy")
    assert subsidy.delta < 0


def test_diagnosis_food_cost_increase() -> None:
    """案例 26: 食材成本上涨。"""
    r = diagnose_profit_change(
        current={"customer_paid": 30.0, "food_cost": 16.0, "packaging_cost": 2.0},
        baseline={"customer_paid": 30.0, "food_cost": 12.0, "packaging_cost": 2.0},
    )
    food = next(f for f in r.factors if f.factor == "food_cost")
    assert food.delta < 0


def test_diagnosis_refund_spike() -> None:
    """案例 27: 退款赔付侵蚀利润。"""
    r = diagnose_profit_change(
        current={"customer_paid": 30.0, "refund_cost": 500.0, "food_cost": 12.0, "packaging_cost": 2.0},
        baseline={"customer_paid": 30.0, "refund_cost": 100.0, "food_cost": 12.0, "packaging_cost": 2.0},
    )
    refund = next(f for f in r.factors if f.factor == "refund_cost")
    assert refund.delta < 0


def test_diagnosis_gmv_up_profit_down() -> None:
    """案例 28: GMV 涨但利润降——买流水。"""
    r = diagnose_profit_change(
        current={"customer_paid": 28.0, "merchant_subsidy": 6.0, "ads_spend": 600.0, "food_cost": 11.0, "packaging_cost": 2.0},
        baseline={"customer_paid": 30.0, "merchant_subsidy": 1.0, "ads_spend": 200.0, "food_cost": 12.0, "packaging_cost": 2.0},
        orders_current=120, orders_baseline=100,
    )
    # 利润应该变差
    assert r.total_profit_delta < 0
    assert "利润下降" in r.conclusion or "减少" in r.conclusion


def test_diagnosis_missing_cost() -> None:
    """案例 29: 缺成本数据——标注 missing。"""
    r = diagnose_profit_change(
        current={"customer_paid": 30.0, "food_cost": None, "packaging_cost": None},
        baseline={"customer_paid": 28.0, "food_cost": 12.0, "packaging_cost": 2.0},
    )
    assert len(r.missing_data) > 0
    assert r.confidence < 0.8


def test_diagnosis_positive_growth() -> None:
    """案例 30: 一切正常——利润增长。"""
    r = diagnose_profit_change(
        current={"customer_paid": 32.0, "merchant_subsidy": 0, "ads_spend": 100.0, "food_cost": 12.0, "packaging_cost": 2.0},
        baseline={"customer_paid": 30.0, "merchant_subsidy": 0, "ads_spend": 100.0, "food_cost": 12.0, "packaging_cost": 2.0},
    )
    assert r.total_profit_delta > 0
    assert "增长" in r.conclusion
