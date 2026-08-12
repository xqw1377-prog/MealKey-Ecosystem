"""老板原话评测：意图编译器回归（所想即所得）。"""

from __future__ import annotations

import pytest

from app.services.intent_compiler import compile_intent

# (utterance, expected_kind, extra_assert_key, extra_assert_value)
CASES: list[tuple[str, str, str | None, object]] = [
    ("利润优先，少点优惠", "setting", "slots.priority_style", "profit"),
    ("先赚钱，别瞎冲单量", "setting", "slots.priority_style", "profit"),
    ("多一点订单", "setting", "slots.priority_style", "orders"),
    ("先把量做起来", "setting", "slots.priority_style", "orders"),
    ("提高排名", "setting", "slots.priority_style", "rank"),
    ("你帮我平衡", "setting", "slots.priority_style", "balanced"),
    ("交给你看着办", "setting", "slots.priority_style", "balanced"),
    ("普通好评你可以回", "setting", "slots.low_risk_auto", True),
    ("先不要自动处理", "setting", "slots.low_risk_auto", False),
    ("午餐一小时大概80单", "constraint", "slots.lunch_capacity", 80.0),
    ("厨房高峰最多100单再多顶不住", "constraint", "slots.lunch_capacity", 100.0),
    ("到手率底线58%", "constraint", "slots.profit_floor", 0.58),
    ("利润底线 0.6", "constraint", "slots.profit_floor", 0.6),
    ("广告每天300以内你自己决定", "constraint", "slots.ads_daily_budget", 300.0),
    ("这个月做到20万", "goal", "metric", "gmv"),
    ("本月营业额冲到15万", "goal", "target_value", 150000.0),
    ("利润率拉到18%", "goal", "metric", "take_home_rate"),
    ("把牛肉饭做到前三", "goal", "metric", "rank"),
    ("招牌鸡做到 top 3", "goal", "metric", "rank"),
    ("今天午餐多 120 单", "goal", "metric", "orders"),
    ("换牛肉饭主图", "action", "action_type", "change_main_image"),
    ("主图要不要换一下", "action", "action_type", "change_main_image"),
    ("改一下标题", "action", "action_type", "change_title"),
    ("差评怎么回复", "action", "action_type", "batch_reply_negative_reviews"),
    ("帮我批量回复差评", "action", "action_type", "batch_reply_negative_reviews"),
    ("上个29元套餐", "action", "action_type", "add_set_meal"),
    ("帮我推出套餐", "action", "action_type", "add_set_meal"),
    ("500块广告费帮我花掉", "action", "action_type", "boost_hero_item_ads"),
    ("投流帮我花 200 元", "action", "action_type", "boost_hero_item_ads"),
    ("参加午市活动", "action", "action_type", "join_lunch_campaign"),
    ("帮我连接美团", "action", "action_type", "connect_platform"),
    ("对接饿了么", "action", "action_type", "connect_platform"),
    ("最近订单下降怎么办", "ask", "suggested_agent", "diagnosis"),
    ("为什么没人下单", "ask", "suggested_agent", "diagnosis"),
    ("附近谁在抢我的生意", "ask", "suggested_agent", "competition"),
    ("竞品是不是降价了", "ask", "suggested_agent", "competition"),
    ("菜单要不要加什么菜", "ask", "suggested_agent", "menu"),
    ("评分为什么下降", "ask", "suggested_agent", "review"),
    ("怎么提高复购", "ask", "suggested_agent", "crm"),
    ("要不要投广告", "ask", "suggested_agent", "ads"),
    ("先做什么才能涨", "ask", "suggested_agent", "growth"),
    ("店页装修有问题吗", "ask", "suggested_query_tool", "query_storefront"),
    ("随便看看今天怎样", "ask", "suggested_agent", "growth"),
    ("帮我提升午餐", "ask", "kind", "ask"),
    ("流量是不是不行了", "ask", "suggested_agent", "ads"),
    ("客单价太低了", "ask", "kind", "ask"),
    ("爆品是哪几个", "ask", "suggested_agent", "product"),
    ("商圈排名掉了", "ask", "suggested_agent", "competition"),
    ("好评变少了", "ask", "suggested_agent", "review"),
    ("老客不来了", "ask", "suggested_agent", "crm"),
]


def _lookup(compiled, path: str):
    cur = compiled
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part)
    return cur


@pytest.mark.parametrize("text,kind,key,value", CASES)
def test_compile_intent_corpus(text: str, kind: str, key: str | None, value: object) -> None:
    compiled = compile_intent(text)
    assert compiled.kind == kind, f"{text!r} -> {compiled.kind} expected {kind}"
    if key:
        assert _lookup(compiled, key) == value


def test_spend_action_without_budget_asks() -> None:
    compiled = compile_intent("帮我投广告")
    assert compiled.kind == "action"
    assert compiled.ready is False
    assert compiled.should_ask is True


def test_goal_gmv_ready() -> None:
    compiled = compile_intent("这个月做到20万")
    assert compiled.ready is True
    assert compiled.suggested_write_tool == "create_goal"


def test_corpus_has_at_least_50() -> None:
    assert len(CASES) >= 50
