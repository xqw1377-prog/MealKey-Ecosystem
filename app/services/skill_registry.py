"""Skill Registry — Domain Skills 的声明式注册（Runtime Bridge Skills 理念）。

每个 Domain Skill 声明自己的能力边界、触发条件、依赖约束。
Lead Agent（chief_agent）按需加载——不是所有能力一次性塞进上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.services.domain_skills import (
    analyze_competition,
    analyze_product,
    analyze_profit,
    analyze_traffic,
)


@dataclass
class SkillManifest:
    """Skill 能力声明——对应 Runtime Bridge SKILL.md。"""

    key: str  # product / traffic / profit / competition
    name: str  # 商品经营 / 流量经营 / 利润经营 / 竞争经营
    description: str  # 一句话能力描述
    triggers: list[str]  # 什么 Event 触发这个 Skill
    dependencies: list[str]  # 执行前置依赖（其他 Skill）
    can_produce_actions: bool  # 是否能产出候选动作
    analyze_fn: Callable  # 实际分析函数
    keywords: list[str] = field(default_factory=list)  # 关键词匹配（渐进加载用）


# Skill 注册表
_SKILL_REGISTRY: dict[str, SkillManifest] = {
    "product": SkillManifest(
        key="product",
        name="商品经营",
        description="诊断商品为什么能卖/卖不动，评估线上货架承接力",
        triggers=["HERO_SKU_CTR_DROP", "SKU_CVR_DROP", "HERO_SKU_SOLD_OUT", "MENU_STRUCTURE_GAP", "ZOMBIE_SKU_DETECTED"],
        dependencies=["competition", "profit"],
        can_produce_actions=True,
        analyze_fn=analyze_product,
        keywords=["商品", "主图", "标题", "CTR", "CVR", "销量", "菜单", "套餐", "SKU", "牛肉饭", "爆品"],
    ),
    "traffic": SkillManifest(
        key="traffic",
        name="流量经营",
        description="把有效商品放大，把无效商品拦住",
        triggers=["HIGH_ROI_UNDERSPEND", "LOW_ROI_OVERSPEND", "BUDGET_EXHAUST_BEFORE_PEAK", "TRAFFIC_SATURATION"],
        dependencies=["product", "profit"],
        can_produce_actions=True,
        analyze_fn=analyze_traffic,
        keywords=["投流", "广告", "CPC", "预算", "流量", "曝光", "排名", "ROI", "推广"],
    ),
    "profit": SkillManifest(
        key="profit",
        name="利润经营",
        description="Gatekeeper——贡献利润守门，可以 veto 任何违反底线的动作",
        triggers=["TAKE_HOME_RATE_DROP", "GMV_UP_PROFIT_DOWN", "CAMPAIGN_MARGIN_BREACH", "PRICE_INCREASE_OPPORTUNITY"],
        dependencies=[],  # Profit 不依赖其他域
        can_produce_actions=True,
        analyze_fn=analyze_profit,
        keywords=["利润", "到手率", "成本", "毛利", "贡献利润", "实收", "补贴"],
    ),
    "competition": SkillManifest(
        key="competition",
        name="竞争经营",
        description="谁在抢生意 + 做了什么改变，不直接执行经营动作",
        triggers=["COMPETITOR_PRICE_DROP", "COMPETITOR_NEW_PRODUCT", "COMPETITOR_NEW_BUNDLE", "COMPETITOR_PROMOTION_ENDED"],
        dependencies=["product", "profit"],
        can_produce_actions=False,  # 只产出 findings，不产动作
        analyze_fn=analyze_competition,
        keywords=["竞品", "竞争", "商圈", "附近", "对手", "排名", "市场份额"],
    ),
}


def get_skill(key: str) -> SkillManifest | None:
    """获取 Skill 声明。"""
    return _SKILL_REGISTRY.get(key)


def select_skills_for_question(question: str) -> list[str]:
    """根据老板的问题关键词，选择需要加载的 Skills（渐进加载）。

    不是所有 4 个 Skill 都加载——只加载和问题相关的。
    """
    text = question.lower()
    matched: list[str] = []
    for key, manifest in _SKILL_REGISTRY.items():
        if any(kw in text for kw in manifest.keywords):
            matched.append(key)
    # 如果没匹配到任何关键词，默认加载 product + profit（最通用的两个）
    if not matched:
        matched = ["product", "profit"]
    return matched


def select_skills_for_event(event_code: str) -> list[str]:
    """根据 Event Code 选择需要加载的 Skills。"""
    matched: list[str] = []
    for key, manifest in _SKILL_REGISTRY.items():
        if event_code in manifest.triggers:
            matched.append(key)
    # 加上依赖
    for key in list(matched):
        manifest = _SKILL_REGISTRY.get(key)
        if manifest:
            for dep in manifest.dependencies:
                if dep not in matched:
                    matched.append(dep)
    return matched


# ═══════════════════════════════════════════════════════════
# Guardrails 双层（Runtime Bridge 理念 §10）
# ═══════════════════════════════════════════════════════════


def pre_tool_authorization(
    action_type: str,
    *,
    operating_budget: Any = None,
    system_mode: str = "operating",
) -> dict[str, Any]:
    """第一层：工具层权限检查（Runtime Bridge pre-tool-call authorization）。

    回答：这个动作类型在当前权限下允许调用吗？
    """
    # Safe Mode 拦截
    if system_mode == "safe":
        from app.services.mos_engine import is_action_allowed_in_safe_mode

        if not is_action_allowed_in_safe_mode(action_type):
            return {
                "allowed": False,
                "layer": "safe_mode",
                "reason": f"Safe Mode：{action_type} 不允许自动执行",
            }

    # OperatingBudget 检查
    if operating_budget and hasattr(operating_budget, "can_auto_execute"):
        can_auto = operating_budget.can_auto_execute(action_type)
        return {
            "allowed": can_auto,
            "layer": "operating_budget",
            "reason": "在老板授权范围内" if can_auto else f"{action_type} 超出 AI 自主执行权限",
        }

    # 默认：需要确认
    return {
        "allowed": False,
        "layer": "default",
        "reason": "默认需要老板确认",
    }


def business_guardrail_check(
    action_type: str,
    *,
    take_home_rate: float | None = None,
    profit_floor: float | None = None,
    expected_lift: float | None = None,
    risk_level: str = "medium",
    reversibility: str = "medium",
) -> dict[str, Any]:
    """第二层：业务层 Guardrail（MealKey 自己的 Profit Gate + Risk Gate）。

    回答：这个动作从业务角度看安全吗？
    """
    blockers: list[str] = []

    # Profit Gate
    if take_home_rate is not None and profit_floor is not None:
        if take_home_rate < profit_floor and action_type in {
            "ADJUST_DAILY_BUDGET", "JOIN_PLATFORM_CAMPAIGN", "CREATE_CAMPAIGN", "CHANGE_PRICE",
        }:
            blockers.append(f"到手率 {take_home_rate:.0%} 低于底线 {profit_floor:.0%}")

    # Risk Gate
    if risk_level == "high" and reversibility == "hard":
        blockers.append("高风险 + 不可逆，必须老板确认")

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "layer": "business_guardrail",
    }


# ═══════════════════════════════════════════════════════════
# Memory 分层（Runtime Bridge 理念 §5）
# ═══════════════════════════════════════════════════════════


@dataclass
class UserLongTermFact:
    """人的长期记忆——老板是谁、怎么决策、偏好什么。

    对应 Runtime Bridge Memory 的 long-term descriptive facts。
    绝对不放业务数字（到hr率/排名/成本）——那些放 StoreState/MerchantContext。
    """

    key: str
    value: str
    source: str = "inferred"  # inferred / user_stated / behavioral
    confidence: float = 0.6
    durability: str = "long"  # long / session / ephemeral


# 预设的长期事实模板（从交互中逐步填充）
_LONG_TERM_FACT_TEMPLATES: dict[str, str] = {
    "decision_style": "老板偏向 {style} 决策",  # 稳健 / 激进 / 数据驱动 / 直觉
    "preferred_communication": "老板偏好 {style} 沟通",  # 简洁 / 详细 / 口语 / 正式
    "trust_level": "信任度 {level}",  # 低 / 中 / 高 / 完全授权
    "growth_appetite": "增长偏好 {appetite}",  # 保守 / 平衡 / 激进
    "time_preference": "活跃时段 {time}",  # 上午 / 下午 / 晚上
    "pain_tolerance": "对数字波动的容忍度 {level}",  # 低 / 中 / 高
}


def extract_user_facts_from_interaction(
    question: str,
    existing_facts: list[UserLongTermFact],
) -> list[UserLongTermFact]:
    """从老板的交互中提取长期事实（简化版——V2 可接 LLM）。"""
    text = question.lower()
    new_facts: list[UserLongTermFact] = []
    existing_keys = {f.key for f in existing_facts}

    # 利润优先 → 增长偏好保守
    if any(kw in text for kw in ("利润优先", "先赚钱", "别瞎冲", "宁愿少点单")):
        if "growth_appetite" not in existing_keys:
            new_facts.append(UserLongTermFact(
                key="growth_appetite",
                value="保守——利润优先于规模",
                source="user_stated",
                confidence=0.9,
            ))

    # 冲量 → 增长偏好激进
    if any(kw in text for kw in ("冲量", "多拿单", "放量", "冲到")):
        if "growth_appetite" not in existing_keys:
            new_facts.append(UserLongTermFact(
                key="growth_appetite",
                value="激进——愿意为增长投入",
                source="user_stated",
                confidence=0.85,
            ))

    # 信任授权
    if any(kw in text for kw in ("你自己看着办", "你决定", "交给你", "以后你自己")):
        new_facts.append(UserLongTermFact(
            key="trust_level",
            value="高——已授权 AI 自主决策部分事务",
            source="user_stated",
            confidence=0.9,
        ))

    return new_facts
