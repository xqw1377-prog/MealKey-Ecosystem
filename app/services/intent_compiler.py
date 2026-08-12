"""Intent Compiler：老板原话 → 目标 / 约束 / 动作 / 追问。

所想即所得的第一跳：先编译对象，再决定问、写还是调一个专业工具。
LLM ReAct 只在编译结果为 ask 时才上场。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Optional

IntentKind = Literal["setting", "constraint", "goal", "action", "ask"]
ExecutionTier = Literal["draft", "confirm", "writeback"]

_SPEND_ACTIONS = {
    "boost_hero_item_ads",
    "adjust_ad_budget",
    "join_lunch_campaign",
    "match_competitor_promo",
    "store_discount",
    "launch_value_bundle_promo",
    "run_platform_promo",
}

_LOW_RISK_WRITEBACK = {
    "batch_reply_negative_reviews",
    "publish_service_reply_scripts",
    "change_title",
    "change_main_image",
    "menu_patch",
}

_SKILL_TO_QUERY = {
    "product": "query_product",
    "traffic": "query_ads",
    "profit": "query_growth",
    "competition": "query_competition",
}

_AGENT_TO_QUERY = {
    "diagnosis": "query_diagnosis",
    "competition": "query_competition",
    "menu": "query_menu",
    "product": "query_product",
    "storefront": "query_storefront",
    "review": "query_review",
    "growth": "query_growth",
    "promo": "query_promo",
    "ads": "query_ads",
    "crm": "query_crm",
    "service": "query_service",
    "store_matrix": "query_store_matrix",
}


@dataclass
class CompiledIntent:
    kind: IntentKind
    raw_text: str
    ready: bool = False
    should_ask: bool = False
    ask_question: str = ""
    suggested_agent: str = "growth"
    suggested_query_tool: str = "query_growth"
    suggested_write_tool: Optional[str] = None
    action_type: str = ""
    object_name: str = ""
    metric: str = "orders"
    target_value: Optional[float] = None
    deadline: Optional[date] = None
    detail: str = ""
    budget: Optional[float] = None
    execution_tier: ExecutionTier = "confirm"
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[dict[str, str]] = field(default_factory=list)

    def to_decision(self) -> dict[str, Any]:
        return {
            "object_name": self.object_name or self.raw_text[:40],
            "action": self.detail or self.object_name or self.raw_text[:40],
            "action_type": self.action_type or self.kind,
            "expected_metric": self.metric,
            "window_hours": 48,
            "auto_ok": self.execution_tier == "writeback",
            "execution_tier": self.execution_tier,
            "kind": self.kind,
        }


def _month_end() -> date:
    today = date.today()
    if today.month == 12:
        return date(today.year, 12, 31)
    next_month = date(today.year, today.month + 1, 1)
    return date.fromordinal(next_month.toordinal() - 1)


def _classify_agent(text: str) -> str:
    lowered = text.lower()
    mapping: list[tuple[str, list[str]]] = [
        ("competition", ["竞争", "附近", "谁抢", "商圈", "对手", "竞品"]),
        ("menu", ["菜单", "加什么菜", "卖什么", "sku", "结构", "套餐缺口"]),
        ("product", ["主图", "标题", "单品", "牛肉饭", "爆品", "图片"]),
        ("service", ["客服", "回复", "话术", "投诉", "怎么回复"]),
        ("review", ["评价", "差评", "评分", "口碑", "好评"]),
        ("growth", ["增长", "提升", "计划", "先做什么", "怎么涨", "下一步"]),
        ("ads", ["投流", "广告", "推广", "流量购买"]),
        ("crm", ["复购", "回头客", "流失", "老客", "新客"]),
        ("diagnosis", ["订单", "下降", "为什么", "诊断", "怎么了", "没人"]),
    ]
    for agent_key, keywords in mapping:
        if any(kw in lowered for kw in keywords):
            return agent_key
    return "growth"


def compile_intent(text: str) -> CompiledIntent:
    """把一句话编译成结构化意图。无法落地则 kind=ask。"""
    raw = (text or "").strip()
    if not raw:
        return CompiledIntent(kind="ask", raw_text="", should_ask=True, ask_question="你想先处理哪一件？")

    setting = _compile_setting(raw)
    if setting:
        return setting
    constraint = _compile_constraint(raw)
    if constraint:
        return constraint
    goal = _compile_goal(raw)
    if goal:
        return goal
    action = _compile_action(raw)
    if action:
        return action
    return _compile_ask(raw)


def _compile_setting(raw: str) -> CompiledIntent | None:
    if re.search(r"(利润优先|先赚钱|别.*(冲|冲单)|少点优惠|宁愿少点单)", raw):
        return CompiledIntent(kind="setting", raw_text=raw, ready=True, suggested_write_tool=None, slots={"priority_style": "profit"})
    if re.search(r"(冲单量|订单优先|多(点|一点)?订单|先把量做起来)", raw):
        return CompiledIntent(kind="setting", raw_text=raw, ready=True, slots={"priority_style": "orders"})
    if re.search(r"(提高排名|冲排名|排名优先)", raw) and "做到前" not in raw:
        return CompiledIntent(kind="setting", raw_text=raw, ready=True, slots={"priority_style": "rank"})
    if re.search(r"(交给你|你平衡|你帮我平衡|你看着办)", raw) or ("平衡" in raw and len(raw) <= 12):
        return CompiledIntent(kind="setting", raw_text=raw, ready=True, slots={"priority_style": "balanced"})
    if re.search(r"先不要|先都问我|不要自动", raw) and ("自动" in raw or "好评" in raw or "低风险" in raw):
        return CompiledIntent(kind="setting", raw_text=raw, ready=True, slots={"low_risk_auto": False})
    if re.search(r"(可以|允许|同意).*(自动|直接|你处理)|普通好评.*(可以|你)", raw):
        return CompiledIntent(kind="setting", raw_text=raw, ready=True, slots={"low_risk_auto": True})
    return None


def _compile_constraint(raw: str) -> CompiledIntent | None:
    m = re.search(r"(?:一小时|每小时|小时).*?(\d+)\s*单|(?:最多|顶多|顶不住).*?(\d+)\s*单", raw)
    if m and ("午餐" in raw or "厨房" in raw or "高峰" in raw or "忙" in raw):
        cap = float(m.group(1) or m.group(2))
        return CompiledIntent(kind="constraint", raw_text=raw, ready=True, slots={"lunch_capacity": cap})
    m = re.search(r"(?:到手|到手率|利润率|利润底线)[^0-9]{0,10}(\d+(?:\.\d+)?)\s*%?", raw)
    if m and not re.search(r"(做到|拉到|提到).{0,6}利润", raw):
        val = float(m.group(1))
        if val > 1:
            val = val / 100.0
        return CompiledIntent(kind="constraint", raw_text=raw, ready=True, slots={"profit_floor": val})
    m = re.search(r"(?:广告|投流|推广)[^0-9]{0,16}(\d+(?:\.\d+)?)\s*(?:元|块)?", raw)
    if m and re.search(r"(以内|自己|自动|你定|你决定|授权)", raw):
        return CompiledIntent(kind="constraint", raw_text=raw, ready=True, slots={"ads_daily_budget": float(m.group(1))})
    return None


def _compile_goal(raw: str) -> CompiledIntent | None:
    if re.search(r"利润优先|先赚钱|冲单量|交给你平衡", raw):
        return None
    m = re.search(r"(?:这个月|本月|月内)?.{0,8}(?:做到|冲到|完成|达到)\s*(\d+(?:\.\d+)?)\s*万", raw)
    if m:
        return CompiledIntent(
            kind="goal",
            raw_text=raw,
            ready=True,
            suggested_write_tool="create_goal",
            metric="gmv",
            target_value=float(m.group(1)) * 10000,
            deadline=_month_end(),
            object_name=raw[:40],
            detail=raw,
        )
    m = re.search(r"利润(?:率)?(?:拉回|拉到|做到|提到|提高到)\s*(\d+(?:\.\d+)?)\s*%?", raw)
    if m:
        val = float(m.group(1))
        if val > 1:
            val = val / 100.0
        return CompiledIntent(
            kind="goal",
            raw_text=raw,
            ready=True,
            suggested_write_tool="create_goal",
            metric="take_home_rate",
            target_value=val,
            deadline=_month_end(),
            object_name="利润率目标",
        )
    if re.search(r"(前\s*三|top\s*3)", raw, re.I) and ("饭" in raw or "菜" in raw or "做到" in raw or "帮我" in raw):
        dish = _extract_dish(raw) or "招牌菜"
        return CompiledIntent(
            kind="goal",
            raw_text=raw,
            ready=True,
            suggested_write_tool="create_goal",
            metric="rank",
            target_value=3.0,
            deadline=_month_end(),
            object_name=dish,
            suggested_agent="product",
            suggested_query_tool="query_product",
        )
    m = re.search(r"(?:多|增加|做到)\s*(\d+)\s*单", raw)
    if m and ("午餐" in raw or "今天" in raw or "一天" in raw) and "一小时" not in raw:
        return CompiledIntent(
            kind="goal",
            raw_text=raw,
            ready=True,
            suggested_write_tool="create_goal",
            metric="orders",
            target_value=float(m.group(1)),
            deadline=date.today(),
            object_name="订单目标",
        )
    return None


def _extract_dish(raw: str) -> str | None:
    m = re.search(r"([\u4e00-\u9fff]{2,12}(?:饭|面|套餐|餐|粉|粥))", raw)
    return m.group(1) if m else None


def _compile_action(raw: str) -> CompiledIntent | None:
    dish = _extract_dish(raw) or ""
    budget = None
    bm = re.search(r"(\d+(?:\.\d+)?)\s*(?:块|元)", raw)
    if bm and re.search(r"(广告|投流|预算|花)", raw):
        budget = float(bm.group(1))

    if re.search(r"(换主图|改主图|主图.*(换|改|优化))", raw):
        return _action(
            raw,
            "change_main_image",
            dish or "招牌菜主图",
            "draft",
            "product",
            ready=True,
            detail=f"生成{dish or '招牌菜'}主图方案，先出可落地稿",
        )
    if re.search(r"(改标题|换标题|标题优化)", raw):
        return _action(raw, "change_title", dish or "商品标题", "writeback", "product", ready=True)
    if re.search(r"(回差评|差评回复|差评怎么回|批量回复)", raw):
        return _action(raw, "batch_reply_negative_reviews", "差评回复", "writeback", "service", ready=True)
    if re.search(r"(上套餐|做套餐|29元套餐|推出套餐)", raw):
        name = "29元套餐" if "29" in raw else (dish or "价值套餐")
        return _action(raw, "add_set_meal", name, "confirm", "menu", ready=True)
    if re.search(r"(参加活动|报活动|上满减|对冲竞品活动)", raw):
        intent = _action(raw, "join_lunch_campaign", "平台活动", "confirm", "promo", ready=not (budget is None and "花" in raw))
        intent.budget = budget
        if budget is None:
            intent.missing_slots = [{"slot": "budget", "question": "你打算投入多少预算？（如 500 元/天）"}]
            intent.should_ask = True
            intent.ready = False
        return intent
    if re.search(r"(投流|投广告|广告费|帮我花).{0,12}(花|投|推)", raw) or re.search(r"(花掉|投放).{0,8}(广告|投流)", raw):
        intent = _action(raw, "boost_hero_item_ads", dish or "午餐投流", "confirm", "ads", ready=budget is not None)
        intent.budget = budget
        intent.metric = "orders"
        if budget is None:
            intent.missing_slots = [{"slot": "budget", "question": "你打算投入多少预算？（如 500 元/天）"}]
            intent.should_ask = True
        else:
            intent.detail = f"预算¥{budget:g}，主投{dish or '招牌菜'}"
            intent.ready = True
        return intent
    if re.search(r"(连接|对接|授权).{0,6}(美团|饿了么|平台)", raw):
        platform = "eleme" if "饿" in raw else "meituan"
        return CompiledIntent(
            kind="action",
            raw_text=raw,
            ready=True,
            suggested_write_tool="connect_platform",
            action_type="connect_platform",
            object_name=platform,
            slots={"platform": platform},
            execution_tier="confirm",
        )
    return None


def _action(
    raw: str,
    action_type: str,
    object_name: str,
    tier: ExecutionTier,
    agent: str,
    *,
    ready: bool,
    detail: str = "",
) -> CompiledIntent:
    if action_type in _LOW_RISK_WRITEBACK and tier == "writeback":
        pass
    elif action_type in _SPEND_ACTIONS:
        tier = "confirm"
    return CompiledIntent(
        kind="action",
        raw_text=raw,
        ready=ready,
        suggested_write_tool="prepare_action",
        suggested_agent=agent,
        suggested_query_tool=_AGENT_TO_QUERY.get(agent, "query_growth"),
        action_type=action_type,
        object_name=object_name,
        detail=detail or raw,
        execution_tier=tier,
        metric="orders" if action_type in _SPEND_ACTIONS else "ctr",
    )


def _compile_ask(raw: str) -> CompiledIntent:
    agent = _classify_agent(raw)
    from app.services.skill_registry import select_skills_for_question

    skills = select_skills_for_question(raw)
    query = _AGENT_TO_QUERY.get(agent) or _SKILL_TO_QUERY.get(skills[0] if skills else "product", "query_growth")
    return CompiledIntent(
        kind="ask",
        raw_text=raw,
        ready=False,
        should_ask=False,
        suggested_agent=agent,
        suggested_query_tool=query,
        object_name=raw[:40],
        detail=raw,
        execution_tier="draft",
    )


def first_query_tool_for(compiled: CompiledIntent) -> str:
    return compiled.suggested_query_tool or "query_growth"
