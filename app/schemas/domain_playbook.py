"""Domain Playbook Schema — 四个核心经营域的统一接口（Runtime V1 §二十二）。

Product / Traffic / Profit / Competition 四个 Domain 都遵守同一个接口：
analyze() → findings / diagnosis / evidence / candidate_actions / dependencies

Domain Skill = 专家；Decision Engine = 总经理；POIE = 决定现在到底做不做。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

DomainKey = Literal["product", "traffic", "profit", "competition"]


class ProductReadiness(BaseModel):
    """商品准备度（材料 §二）——Traffic 投钱前必须检查。

    6 个维度 + 综合分。低于阈值的不允许放大流量。
    """

    sku_id: str = ""
    sku_name: str = ""
    role: str = ""  # HERO/PROFIT/TRAFFIC/COMBO/BASIC
    lifecycle: str = ""  # GROWTH/MATURE/DECLINE

    visibility: float = 0.5  # 曝光可得性
    clickability: float = 0.5  # 点击竞争力（CTR）
    conversion: float = 0.5  # 转化能力（CVR）
    rating: float = 0.5  # 评分健康
    availability: float = 0.5  # 在售稳定性
    price_competitiveness: float = 0.5  # 价格竞争力

    overall: float = 0.5
    ready: bool = False  # overall >= 0.65 才算 ready


class TrafficReadiness(BaseModel):
    """流量准备度（材料 §六）——聚合 Product + Conversion + Profit + Capacity + Goal。"""

    product_ready: bool = False
    conversion_healthy: bool = False
    profit_safe: bool = False
    capacity_available: bool = True  # V1 默认有产能
    goal_relevant: bool = True

    product_readiness_score: float = 0.0
    conversion_score: float = 0.0
    profit_score: float = 0.0
    capacity_score: float = 0.8
    goal_score: float = 0.7

    overall: float = 0.0
    ready: bool = False  # overall >= 0.6 才允许放量


class DomainFinding(BaseModel):
    """一个 Domain 的诊断发现。"""
    code: str  # HERO_SKU_CTR_DROP / HIGH_ROI_UNDERSPEND / TAKE_HOME_RATE_DROP ...
    severity: str = "medium"  # critical / high / medium / low / positive
    title: str
    description: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.7


class DomainDiagnosis(BaseModel):
    """Domain 的诊断结论。"""
    primary: str = ""
    alternatives: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class CandidateAction(BaseModel):
    """Domain 产出的候选动作（不是最终决策，必须经过 ODO → POIE）。"""
    action_type: str  # CHANGE_PRODUCT_IMAGE / ADJUST_DAILY_BUDGET / CHANGE_PRICE ...
    title: str
    detail: str = ""
    expected_incremental_orders: Optional[float] = None
    expected_incremental_profit: Optional[float] = None
    max_loss: Optional[float] = None
    observation_window_hours: int = 48
    risk_level: str = "medium"
    primary_variable: str = ""  # 单变量实验约束（材料 §五）


class DomainSkillResult(BaseModel):
    """统一 Domain Skill 输出（材料 §二十二）。"""

    domain: DomainKey
    findings: list[DomainFinding] = Field(default_factory=list)
    diagnosis: DomainDiagnosis = Field(default_factory=DomainDiagnosis)
    evidence: list[str] = Field(default_factory=list)
    context_gaps: list[str] = Field(default_factory=list)
    candidate_actions: list[CandidateAction] = Field(default_factory=list)
    dependencies: list[DomainKey] = Field(default_factory=list)  # 需要哪些其他 Domain 验证
    recommended_next_step: str = ""

    # Domain 特定附件
    product_readiness: Optional[ProductReadiness] = None
    traffic_readiness: Optional[TrafficReadiness] = None


# ═══════════════════════════════════════════════════════════
# Domain Dependency Graph（材料 §二十一）
# ═══════════════════════════════════════════════════════════

# 硬约束：某 Domain 执行某类 Action 前必须检查的其他 Domain
DOMAIN_DEPENDENCIES: dict[str, dict[str, list[DomainKey]]] = {
    "traffic": {
        # Traffic 放量前必须检查 Product + Profit
        "ADJUST_DAILY_BUDGET": ["product", "profit"],
        "CREATE_CAMPAIGN": ["product", "profit"],
        "JOIN_PLATFORM_CAMPAIGN": ["profit"],
        "CHANGE_PROMOTED_SKU": ["product"],
    },
    "product": {
        # Product 调价前必须检查 Profit + Competition
        "CHANGE_PRICE": ["profit", "competition"],
        "CREATE_BUNDLE": ["profit"],
    },
    "competition": {
        # Competition 发现变化后不能直接执行经营动作
        # 只产出 findings + dependencies，不产 candidate_actions
    },
    "profit": {
        # Profit 可以 veto 任何违反底线的动作（veto 在 ProfitGate 实现）
    },
}


def check_domain_dependency(
    domain: DomainKey,
    action_type: str,
    other_domains: dict[DomainKey, DomainSkillResult],
) -> tuple[bool, list[str]]:
    """检查某个 Domain 的动作是否满足依赖约束。

    返回 (allowed, blocking_reasons)。
    """
    deps = DOMAIN_DEPENDENCIES.get(domain, {}).get(action_type, [])
    if not deps:
        return True, []

    blockers: list[str] = []
    for dep_domain in deps:
        dep_result = other_domains.get(dep_domain)
        if dep_result is None:
            blockers.append(f"缺少 {dep_domain} 域的验证")
            continue

        # 特定检查
        if dep_domain == "product":
            if dep_result.product_readiness and not dep_result.product_readiness.ready:
                blockers.append(f"商品准备度不足（{dep_result.product_readiness.overall:.0%}），不能放量")
        elif dep_domain == "profit":
            # Profit veto：检查是否有 critical 的利润 finding
            critical = [f for f in dep_result.findings if f.severity == "critical"]
            if critical:
                blockers.append(f"利润域拦截：{critical[0].title}")
        elif dep_domain == "competition":
            # Competition 发现变化但不直接阻止——只是提供信息
            pass

    return (len(blockers) == 0, blockers)
