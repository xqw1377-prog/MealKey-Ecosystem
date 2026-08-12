"""菜单经营诊断 12 引擎 — 从主仓 menu-diagnosis-engine 迁移（TypeScript→Python）。

确定性规则 + 统计计算优先，LLM 仅做解释。
每个引擎返回 DiagnosisFinding[]，数据不足时降级输出。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.schemas.menu_diagnosis import (
    ConfidenceCard,
    DiagnosisContext,
    DiagnosisFinding,
    DiagnosisRunResult,
    EvidenceItem,
    MenuItemInput,
)

_finding_seq = 0


def _next_id(prefix: str) -> str:
    global _finding_seq
    _finding_seq += 1
    return f"{prefix}-{_finding_seq}"


def _reset_seq() -> None:
    global _finding_seq
    _finding_seq = 0


def _confidence(ctx: DiagnosisContext, level: str, reason: str, sample_size: int) -> ConfidenceCard:
    return ConfidenceCard(
        level=level,  # type: ignore
        data_level=ctx.data_level,
        field_coverage=0.8 if ctx.menu_items else 0.3,
        sample_size=sample_size,
        timeliness=0.8 if ctx.feedbacks else 0.3,
        consistency=0.7,
        model_uncertainty={"high": 0.1, "medium": 0.3, "low": 0.6}.get(level, 0.3),
        rule_hits=1,
        reason=reason,
    )


def _evidence(ctx: DiagnosisContext, source: str, value: str) -> EvidenceItem:
    return EvidenceItem(
        source=source,
        data_level=ctx.data_level,
        sample_size=len(ctx.feedbacks) or None,
        value=value,
    )


# ═══════════════════════════════════════════════════════════
# 引擎 1: 菜单结构与价格带
# ═══════════════════════════════════════════════════════════


def diagnose_menu_structure(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    items = ctx.menu_items
    if not items:
        return findings

    categories: dict[str, list[MenuItemInput]] = {}
    for item in items:
        cat = item.category or "未分类"
        categories.setdefault(cat, []).append(item)

    # 菜品数量压力
    if len(items) > 80:
        findings.append(DiagnosisFinding(
            id=_next_id("struct"), engine_id="menu_structure", severity="warning",
            title=f"菜品总数过多（{len(items)}道），选择压力大",
            description=f"菜单共 {len(items)} 道菜品，超过 80 道阈值。顾客点单决策时间增加，后厨备料压力增大。",
            evidence=[_evidence(ctx, "menu_items", f"共 {len(items)} 道菜，{len(categories)} 个分类")],
            impact="点单效率下降 → 翻台率降低 → 营业额受限",
            confidence=_confidence(ctx, "high", "菜品数量为确定性事实", len(items)),
            suggested_actions=["精简低销量菜品", "按场景分时段菜单", "合并相似菜品"],
        ))

    # 招牌菜标记
    has_signature = any(i.is_signature or i.role == "signature" for i in items)
    if not has_signature:
        findings.append(DiagnosisFinding(
            id=_next_id("struct"), engine_id="menu_structure", severity="warning",
            title="缺少招牌菜标记",
            description="菜单中未标记招牌菜，顾客缺少记忆锚点和推荐起点。",
            evidence=[_evidence(ctx, "menu_items", "无 isSignature=true 的菜品")],
            impact="品牌记忆度低 → 复购驱动力弱",
            confidence=_confidence(ctx, "medium", "可能未标记而非不存在", len(items)),
            suggested_actions=["确认 1-2 道招牌菜并标记", "在菜牌第一视觉区突出展示"],
        ))

    # 价格带断档
    prices = sorted([i.price for i in items if i.price > 0])
    if len(prices) >= 5:
        gaps = []
        for i in range(1, len(prices)):
            gap = prices[i] - prices[i - 1]
            if gap > 50 and prices[i - 1] > 20:
                gaps.append(f"¥{prices[i-1]} → ¥{prices[i]}")
        if gaps:
            findings.append(DiagnosisFinding(
                id=_next_id("struct"), engine_id="menu_structure", severity="info",
                title="价格带存在断档",
                description=f"价格跳跃超过 ¥50 的位置：{'、'.join(gaps[:3])}。可能导致中间预算顾客无从选择。",
                evidence=[_evidence(ctx, "price_analysis", f"断档: {'; '.join(gaps)}")],
                impact="中间预算客群流失 → 客单价分化",
                confidence=_confidence(ctx, "medium", "价格断档为统计事实", len(prices)),
                suggested_actions=["在断档区间补充 1-2 道过渡菜品", "或设计套餐覆盖中间预算"],
            ))

    # 分类过多
    if len(categories) > 12:
        findings.append(DiagnosisFinding(
            id=_next_id("struct"), engine_id="menu_structure", severity="info",
            title=f"分类过多（{len(categories)}个）",
            description=f"共 {len(categories)} 个分类，超出 12 个建议上限，可能增加浏览成本。",
            evidence=[_evidence(ctx, "category_count", f"{len(categories)} 个分类")],
            impact="浏览效率下降 → 点单时间增加",
            confidence=_confidence(ctx, "medium", "分类数为事实", len(categories)),
            suggested_actions=["合并低频分类", "使用二级分类折叠"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 2: 成本卡与盈利
# ═══════════════════════════════════════════════════════════


def diagnose_cost_profit(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    items_with_cost = [i for i in ctx.menu_items if i.standard_cost is not None and i.price > 0]
    if not items_with_cost:
        findings.append(DiagnosisFinding(
            id=_next_id("cost"), engine_id="cost_profit", severity="info",
            title="缺少成本卡数据",
            description="未录入标准成本，无法计算精确毛利。",
            evidence=[_evidence(ctx, "cost_card", "0 条成本记录")],
            impact="无法识别亏损菜和低毛利菜",
            confidence=_confidence(ctx, "low", "无成本数据", 0),
            suggested_actions=["优先录入销量 TOP20 菜品的成本"],
        ))
        return findings

    loss_items: list[str] = []
    low_margin_items: list[str] = []
    for item in items_with_cost:
        margin = ((item.price - (item.standard_cost or 0)) / item.price) * 100
        if margin <= 0:
            loss_items.append(f"{item.name}(毛利{margin:.1f}%)")
        elif margin < 40:
            low_margin_items.append(f"{item.name}({margin:.1f}%)")

    if loss_items:
        findings.append(DiagnosisFinding(
            id=_next_id("cost"), engine_id="cost_profit", severity="critical",
            title=f"发现 {len(loss_items)} 道亏损菜",
            description=f"以下菜品售价低于标准成本：{'、'.join(loss_items)}。每售出一份即产生亏损。",
            evidence=[_evidence(ctx, "cost_card", f"亏损菜: {'; '.join(loss_items)}")],
            impact="销量越高亏损越大 → 侵蚀整体利润",
            confidence=_confidence(ctx, "high", "基于标准成本卡确定性计算", len(items_with_cost)),
            suggested_actions=["立即调价或下架", "检查配方用量是否准确", "确认采购价是否过期"],
        ))

    if len(low_margin_items) > 3:
        findings.append(DiagnosisFinding(
            id=_next_id("cost"), engine_id="cost_profit", severity="warning",
            title=f"{len(low_margin_items)} 道菜品毛利率低于 40%",
            description=f"低毛利菜品：{'、'.join(low_margin_items[:5])}{' 等' if len(low_margin_items) > 5 else ''}",
            evidence=[_evidence(ctx, "cost_card", f"{len(low_margin_items)} 道菜毛利 < 40%")],
            impact="综合毛利率被拉低 → 盈利能力受限",
            confidence=_confidence(ctx, "high", "基于成本卡计算", len(items_with_cost)),
            suggested_actions=["优化配方降低食材成本", "调整份量或售价", "检查是否为引流定位"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 3: 食材网络与供应链（简化版，无独立食材表时降级）
# ═══════════════════════════════════════════════════════════


def diagnose_ingredient_supply(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    """外卖场景通常无食材明细，降级为基于菜品的采购复杂度估算。"""
    findings: list[DiagnosisFinding] = []
    items = ctx.menu_items
    if len(items) < 5:
        return findings

    # 用分类多样性代理食材复用率（分类越多→食材越多→采购越复杂）
    categories = set(i.category for i in items if i.category)
    if len(categories) > 8 and len(items) > 30:
        findings.append(DiagnosisFinding(
            id=_next_id("ingr"), engine_id="ingredient_supply", severity="warning",
            title=f"菜品跨 {len(categories)} 个分类，采购复杂度偏高",
            description=f"{len(items)} 道菜覆盖 {len(categories)} 个分类，食材种类可能过多，增加采购和库存管理难度。",
            evidence=[_evidence(ctx, "category_analysis", f"{len(items)}道菜/{len(categories)}分类")],
            impact="采购批量小 → 单价高 → 库存损耗增加",
            confidence=_confidence(ctx, "medium", "基于分类代理推断", len(items)),
            suggested_actions=["合并使用相近食材的菜品", "评估是否每个分类都是必要的"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 4: 味型与辣度
# ═══════════════════════════════════════════════════════════


def diagnose_flavor_spice(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    items_with_spice = [i for i in ctx.menu_items if i.spice_level is not None]
    items_with_flavor = [i for i in ctx.menu_items if i.flavor_primary]

    if not items_with_spice and not items_with_flavor:
        findings.append(DiagnosisFinding(
            id=_next_id("flavor"), engine_id="flavor_spice", severity="info",
            title="缺少味型/辣度标签数据",
            description="菜品未录入味型/辣度标签，无法进行味觉节奏分析。",
            evidence=[_evidence(ctx, "menu_items", "0 道菜有味型标签")],
            impact="无法评估味型覆盖和辣度分布",
            confidence=_confidence(ctx, "low", "无标签数据", 0),
            suggested_actions=["研发评审确认主辅味型", "标注辣度等级和可调性"],
        ))
        return findings

    # 辣度分布
    if items_with_spice:
        not_spicy = sum(1 for i in items_with_spice if i.spice_level == 0)
        not_spicy_rate = (not_spicy / len(items_with_spice)) * 100
        if not_spicy_rate < 20:
            findings.append(DiagnosisFinding(
                id=_next_id("flavor"), engine_id="flavor_spice", severity="warning",
                title=f"不辣菜品占比过低（{not_spicy_rate:.0f}%）",
                description=f"仅 {not_spicy_rate:.0f}% 菜品为不辣（{not_spicy}/{len(items_with_spice)}），不吃辣的顾客选择空间小。",
                evidence=[_evidence(ctx, "flavor_tags", f"不辣 {not_spicy}/{len(items_with_spice)}")],
                impact="不吃辣客群体验差 → 复购下降",
                confidence=_confidence(ctx, "high", "基于标签统计", len(items_with_spice)),
                suggested_actions=["增加 2-3 道不辣精品菜", "标记可降辣菜品"],
            ))

    # 味型单一
    if items_with_flavor:
        flavor_counts: dict[str, int] = {}
        for item in items_with_flavor:
            flavor_counts[item.flavor_primary] = flavor_counts.get(item.flavor_primary, 0) + 1
        top_flavor = max(flavor_counts.items(), key=lambda x: x[1])
        if top_flavor[1] / len(items_with_flavor) > 0.5:
            pct = (top_flavor[1] / len(items_with_flavor)) * 100
            findings.append(DiagnosisFinding(
                id=_next_id("flavor"), engine_id="flavor_spice", severity="warning",
                title=f"味型过于集中（{top_flavor[0]}占 {pct:.0f}%）",
                description=f"超过半数菜品主味型为「{top_flavor[0]}」，整桌味觉节奏单调。",
                evidence=[_evidence(ctx, "flavor_tags", f"{top_flavor[0]}: {top_flavor[1]}/{len(items_with_flavor)}")],
                impact="味觉疲劳 → 菜品记忆度低 → 复购驱动力弱",
                confidence=_confidence(ctx, "high", "基于标签统计", len(items_with_flavor)),
                suggested_actions=["引入 2-3 种差异化味型", "设计味觉节奏推荐组合"],
            ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 5: 荤素与饮食限制
# ═══════════════════════════════════════════════════════════


def diagnose_diet_nutrition(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    items_with_diet = [i for i in ctx.menu_items if i.diet_type]
    if not items_with_diet:
        return findings

    pure_veg = [i for i in items_with_diet if i.diet_type in ("pure_veg", "vegan")]
    veg_rate = (len(pure_veg) / len(items_with_diet)) * 100
    if veg_rate < 15:
        findings.append(DiagnosisFinding(
            id=_next_id("diet"), engine_id="diet_nutrition", severity="warning",
            title=f"纯素菜品占比仅 {veg_rate:.0f}%",
            description=f"{len(pure_veg)}/{len(items_with_diet)} 道为纯素，素食者选择空间有限。",
            evidence=[_evidence(ctx, "diet_tags", f"纯素 {len(pure_veg)}/{len(items_with_diet)}")],
            impact="素食/轻食客群流失",
            confidence=_confidence(ctx, "medium", "基于标签", len(items_with_diet)),
            suggested_actions=["增加 2-3 道有特色的纯素菜", "标注含动物油/肉汤的素菜"],
        ))

    # 过敏原标注
    items_with_allergens = [i for i in ctx.menu_items if i.allergens]
    if len(items_with_allergens) < len(ctx.menu_items) * 0.3 and len(ctx.menu_items) > 10:
        coverage = (len(items_with_allergens) / len(ctx.menu_items)) * 100
        findings.append(DiagnosisFinding(
            id=_next_id("diet"), engine_id="diet_nutrition", severity="warning",
            title="过敏原标注覆盖率不足",
            description=f"仅 {len(items_with_allergens)}/{len(ctx.menu_items)} 道菜品标注了过敏原信息（{coverage:.0f}%）。",
            evidence=[_evidence(ctx, "allergen_tags", f"覆盖率 {coverage:.0f}%")],
            impact="食品安全风险 → 合规隐患",
            confidence=_confidence(ctx, "high", "标注率为确定性事实", len(ctx.menu_items)),
            suggested_actions=["优先标注含常见过敏原的菜品", "在菜牌上提示顾客"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 6: 上菜速度与厨房产能（外卖版：用出餐时间/CVR 代理）
# ═══════════════════════════════════════════════════════════


def diagnose_speed_capacity(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    """外卖场景无 KDS 数据时，用 CVR + 订单量代理厨房压力。"""
    findings: list[DiagnosisFinding] = []
    items = [i for i in ctx.menu_items if i.order_count > 0]
    if not items:
        return findings

    # 高频菜品集中度 → 厨房压力
    total_orders = sum(i.order_count for i in items)
    if total_orders > 0:
        sorted_items = sorted(items, key=lambda x: x.order_count, reverse=True)
        top5_share = sum(i.order_count for i in sorted_items[:5]) / total_orders * 100
        if top5_share > 70 and len(items) > 10:
            findings.append(DiagnosisFinding(
                id=_next_id("speed"), engine_id="speed_capacity", severity="warning",
                title=f"TOP5 菜品贡献 {top5_share:.0f}% 订单，厨房负荷集中",
                description=f"销量最高的 5 道菜（{'、'.join(i.name for i in sorted_items[:3])}）占总订单 {top5_share:.0f}%，午高峰可能出餐瓶颈。",
                evidence=[_evidence(ctx, "order_analysis", f"TOP5占比 {top5_share:.0f}%")],
                impact="峰值时段出餐拥堵 → 等待时间增加 → 差评",
                confidence=_confidence(ctx, "medium", "基于订单分布", len(items)),
                suggested_actions=["评估预制流程优化", "设计错峰推荐组合", "考虑分流热门菜到不同档口"],
            ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 7: 菜牌阅读与点单决策（外卖版：用标题/描述完整度代理）
# ═══════════════════════════════════════════════════════════


def diagnose_menu_reading(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    items = ctx.menu_items
    if not items:
        return findings

    # 缺描述
    no_desc = [i for i in items if not i.description or len(i.description.strip()) < 5]
    if len(no_desc) > len(items) * 0.3 and len(items) > 5:
        findings.append(DiagnosisFinding(
            id=_next_id("read"), engine_id="menu_reading", severity="info",
            title=f"{len(no_desc)} 道菜品缺少描述",
            description=f"{len(no_desc)}/{len(items)} 道菜品文字描述不足 5 字，影响顾客决策。",
            evidence=[_evidence(ctx, "menu_items", f"{len(no_desc)} 道菜缺描述")],
            impact="顾客不敢点 → 客单价受限",
            confidence=_confidence(ctx, "medium", "描述完整度为事实", len(items)),
            suggested_actions=["为招牌菜补充份量/食材/口味描述", "标注辣度和过敏原"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 8: 菜品颜值与图实一致
# ═══════════════════════════════════════════════════════════


def diagnose_visual_appearance(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    items = ctx.menu_items
    items_with_image = [i for i in items if i.image_url]
    if not items:
        return findings

    coverage = (len(items_with_image) / len(items)) * 100 if items else 0
    if coverage < 50:
        findings.append(DiagnosisFinding(
            id=_next_id("visual"), engine_id="visual_appearance", severity="info",
            title=f"菜品图片覆盖率不足（{coverage:.0f}%）",
            description=f"仅 {len(items_with_image)}/{len(items)} 道菜品有图片。",
            evidence=[_evidence(ctx, "image_assets", f"图片覆盖率 {coverage:.0f}%")],
            impact="无图菜品点击率显著低于有图菜品",
            confidence=_confidence(ctx, "low", "缺少标准图对比", len(items)),
            suggested_actions=["为招牌菜拍摄标准图", "确保图实一致"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 9: 复购驱动力/菜品记忆度（用好评数据代理）
# ═══════════════════════════════════════════════════════════


def diagnose_repurchase_memory(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    if not ctx.feedbacks:
        return findings

    # 从反馈中提取高好评菜品
    positive_mentions: dict[str, int] = {}
    for fb in ctx.feedbacks:
        if fb.get("rating", 0) >= 4 and fb.get("menu_item_name"):
            name = fb["menu_item_name"]
            positive_mentions[name] = positive_mentions.get(name, 0) + 1

    top_mentioned = sorted(positive_mentions.items(), key=lambda x: x[1], reverse=True)[:3]
    if top_mentioned:
        findings.append(DiagnosisFinding(
            id=_next_id("repurchase"), engine_id="repurchase_memory", severity="positive",
            title="高好评菜品（潜在记忆菜）",
            description=f"好评提及最多：{'、'.join(f'{n}({c}次)' for n, c in top_mentioned)}。建议作为品牌记忆点强化。",
            evidence=[_evidence(ctx, "feedback", f"好评 TOP: {', '.join(n for n, _ in top_mentioned)}")],
            impact="记忆菜 → 复购驱动力 → 品牌独占性",
            confidence=_confidence(ctx, "medium", "基于评论语义", len(ctx.feedbacks)),
            suggested_actions=["强化招牌菜出品稳定性", "在菜牌和推荐中突出展示"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 10: 顾客完整旅程（用差评标签聚类代理）
# ═══════════════════════════════════════════════════════════


def diagnose_customer_journey(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    if not ctx.feedbacks:
        return findings

    negative_tags: dict[str, int] = {}
    for fb in ctx.feedbacks:
        if fb.get("rating", 5) <= 2:
            for tag in fb.get("tags", []):
                negative_tags[tag] = negative_tags.get(tag, 0) + 1

    top_negative = sorted(negative_tags.items(), key=lambda x: x[1], reverse=True)[:3]
    if top_negative and top_negative[0][1] >= 3:
        findings.append(DiagnosisFinding(
            id=_next_id("journey"), engine_id="customer_journey", severity="warning",
            title=f"顾客负面反馈集中：{top_negative[0][0]}",
            description=f"差评标签 TOP: {'、'.join(f'{t}({c})' for t, c in top_negative)}。需绑定到具体菜品和时段分析。",
            evidence=[_evidence(ctx, "feedback", f"差评标签: {', '.join(f'{t}:{c}' for t, c in top_negative)}")],
            impact="体验断裂 → 复购下降 → 口碑损失",
            confidence=_confidence(ctx, "medium", "基于评论标签聚类", len(ctx.feedbacks)),
            suggested_actions=["定位具体菜品和门店", "制定改善方案并跟踪"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 11: 菜品角色与联合诊断
# ═══════════════════════════════════════════════════════════


def diagnose_dish_role_joint(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    """跨维度矛盾：高销量但低 CVR → 可能有体验问题。"""
    findings: list[DiagnosisFinding] = []
    items_with_data = [i for i in ctx.menu_items if i.order_count > 0 and i.cvr is not None]
    if len(items_with_data) < 5:
        return findings

    # 高曝光低转化：很多人看但不下单
    low_cvr_high_traffic = [
        i for i in items_with_data
        if i.cvr is not None and i.cvr < 0.08 and i.order_share_pct is not None and i.order_share_pct > 5
    ]
    if low_cvr_high_traffic:
        names = "、".join(i.name for i in low_cvr_high_traffic[:3])
        findings.append(DiagnosisFinding(
            id=_next_id("role"), engine_id="dish_role_joint", severity="warning",
            title=f"{len(low_cvr_high_traffic)} 道菜品高曝光但低转化",
            description=f"{names} 有一定流量但转化率偏低（<8%），可能是价格感知、图片或描述问题。",
            evidence=[_evidence(ctx, "funnel_analysis", f"{len(low_cvr_high_traffic)}道菜 CVR<8% 且 share>5%")],
            impact="流量浪费 → ROI 下降",
            confidence=_confidence(ctx, "medium", "基于漏斗数据", len(items_with_data)),
            suggested_actions=["优化主图和标题", "调整价格感知", "检查是否需要套餐搭配"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 引擎 12: 合规与风险
# ═══════════════════════════════════════════════════════════


def diagnose_compliance_risk(ctx: DiagnosisContext) -> list[DiagnosisFinding]:
    findings: list[DiagnosisFinding] = []
    items = ctx.menu_items

    # 有图无描述
    items_with_image_no_desc = [
        i for i in items if i.image_url and (not i.description or len(i.description.strip()) < 5)
    ]
    if len(items_with_image_no_desc) > 5:
        findings.append(DiagnosisFinding(
            id=_next_id("comply"), engine_id="compliance_risk", severity="info",
            title=f"{len(items_with_image_no_desc)} 道菜品图片缺少配套描述",
            description=f"有图片但缺少文字描述，可能存在图文不符风险。",
            evidence=[_evidence(ctx, "menu_items", f"{len(items_with_image_no_desc)} 道菜有图无描述")],
            impact="图实不符投诉风险 → 广告合规隐患",
            confidence=_confidence(ctx, "medium", "需人工确认", len(items_with_image_no_desc)),
            suggested_actions=["补充菜品描述（份量、食材）", "标注'图片仅供参考'"],
        ))

    # 过敏原严重缺失
    items_missing_allergen = [i for i in items if not i.allergens]
    if len(items_missing_allergen) > len(items) * 0.7 and len(items) > 10:
        findings.append(DiagnosisFinding(
            id=_next_id("comply"), engine_id="compliance_risk", severity="warning",
            title="过敏原信息严重缺失",
            description=f"{len(items_missing_allergen)}/{len(items)} 道菜品未标注过敏原，存在食品安全和合规风险。",
            evidence=[_evidence(ctx, "allergen_audit", f"缺失率 {(len(items_missing_allergen)/len(items)*100):.0f}%")],
            impact="食品安全事故风险 → 法律责任",
            confidence=_confidence(ctx, "high", "过敏原标注为合规要求", len(items)),
            suggested_actions=["立即补充过敏原标注", "高风险菜品必须专业人员确认"],
        ))

    return findings


# ═══════════════════════════════════════════════════════════
# 统一调度
# ═══════════════════════════════════════════════════════════

ENGINE_MAP = {
    "menu_structure": diagnose_menu_structure,
    "cost_profit": diagnose_cost_profit,
    "ingredient_supply": diagnose_ingredient_supply,
    "flavor_spice": diagnose_flavor_spice,
    "diet_nutrition": diagnose_diet_nutrition,
    "speed_capacity": diagnose_speed_capacity,
    "menu_reading": diagnose_menu_reading,
    "visual_appearance": diagnose_visual_appearance,
    "repurchase_memory": diagnose_repurchase_memory,
    "customer_journey": diagnose_customer_journey,
    "dish_role_joint": diagnose_dish_role_joint,
    "compliance_risk": diagnose_compliance_risk,
}


def run_diagnosis_engines(ctx: DiagnosisContext) -> DiagnosisRunResult:
    """运行全部 12 诊断引擎，返回汇总结果。"""
    _reset_seq()
    all_findings: list[DiagnosisFinding] = []
    for engine_id, engine_fn in ENGINE_MAP.items():
        try:
            all_findings.extend(engine_fn(ctx))
        except Exception:  # noqa: BLE001 — 单引擎失败不阻断其他引擎
            pass

    # 按严重度排序
    severity_rank = {"critical": 0, "warning": 1, "positive": 2, "info": 3}
    all_findings.sort(key=lambda f: severity_rank.get(f.severity, 9))

    # 统计
    by_severity: dict[str, int] = {}
    for f in all_findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1

    critical = by_severity.get("critical", 0)
    warning = by_severity.get("warning", 0)
    if critical:
        summary = f"发现 {critical} 个严重问题、{warning} 个警告，建议优先处理严重项。"
    elif warning:
        summary = f"发现 {warning} 个警告，建议关注但非紧急。"
    elif all_findings:
        summary = f"菜单整体健康，发现 {len(all_findings)} 条优化建议。"
    else:
        summary = "菜单诊断未发现问题。"

    return DiagnosisRunResult(
        store_id=ctx.store_id,
        data_level=ctx.data_level,
        findings=all_findings,
        finding_count_by_severity=by_severity,
        summary=summary,
    )
