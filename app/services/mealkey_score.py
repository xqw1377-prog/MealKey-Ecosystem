"""MealKey Score 计算引擎。

把 13 个 agent 各自的 health_score 按 5 维加权，得到首页核心数字。

权重（对齐产品文档）：
  商品表现 30% / 菜单结构 20% / 竞争能力 20% / 经营趋势 20% / 评价表现 10%

各维度来源 agent：
  product   → StoreAgentsResponse.product.health_score
  menu      → menu.menu_health_score
  competition → competition.competition_score
  trend     → diagnosis.diagnosis_score（经营趋势由诊断 agent 代表）
  review    → review.health_score
"""

from __future__ import annotations

from app.schemas.agents import StoreAgentsResponse
from app.schemas.mealkey_score import MealKeyScore, OperationDimension, OperationScore, ScoreDimension
from app.schemas.store_state import PlatformHealthState

# 文档承诺的 5 维权重
_DIMENSION_WEIGHTS: dict[str, tuple[str, str, float]] = {
    # key: (label, 取分字段名, weight)
    "product": ("商品表现", "product", 0.30),
    "menu": ("菜单结构", "menu", 0.20),
    "competition": ("竞争能力", "competition", 0.20),
    "trend": ("经营趋势", "_trend", 0.20),  # 改用真实趋势分而非 diagnosis_score
    "review": ("评价表现", "review", 0.10),
}

# 各 agent 结果里健康分的字段名（命名不统一，这里做映射）
_AGENT_SCORE_FIELDS: dict[str, str] = {
    "product": "health_score",
    "menu": "menu_health_score",
    "competition": "competition_score",
    "diagnosis": "diagnosis_score",
    "review": "health_score",
}


def _compute_trend_score(agents: StoreAgentsResponse) -> int:
    """真正的经营趋势分：基于 orders/gmv/ctr/cvr 的 delta_pct 方向和幅度。

    不再用 diagnosis_score（那是异常诊断打分，不反映趋势方向）。
    """
    state = agents.store_state
    score = 72  # 中性基线
    weights = {"orders": 0.9, "gmv": 0.7, "ctr": 0.5, "cvr": 0.5}
    for metric, weight in weights.items():
        kpi = state.kpis.get(metric)
        if kpi and kpi.delta_pct is not None:
            # delta_pct 正=变好，负=变差；单边 clamp [-18, +12]
            delta = max(-18, min(12, kpi.delta_pct))
            score += int(delta * weight)
    return max(30, min(98, score))


def _get_agent_score(agents: StoreAgentsResponse, agent_name: str) -> int:
    """从 StoreAgentsResponse 取某个 agent 的健康分，统一处理命名差异。"""
    agent_result = getattr(agents, agent_name, None)
    if agent_result is None:
        return 72  # 缺失时给中性基线
    field = _AGENT_SCORE_FIELDS.get(agent_name, "health_score")
    score = getattr(agent_result, field, None)
    if score is None:
        # 回退到通用 health_score
        score = getattr(agent_result, "health_score", 72)
    return int(score)


def _build_judgment(total: int, dimensions: list[ScoreDimension]) -> str:
    """根据总分和最弱维度生成一句话定性。"""
    if total >= 80:
        base = "经营基本盘健康"
    elif total >= 65:
        base = "经营基本盘尚可，有改进空间"
    elif total >= 50:
        base = "经营基本盘偏弱"
    else:
        base = "经营基本盘承压，需优先处理"
    # 找最弱维度
    if dimensions:
        weakest = min(dimensions, key=lambda d: d.score)
        if weakest.score < 60:
            return f"{base}，主要拖累在{weakest.label}（{weakest.score}分）。"
    return base + "。"


def compute_mealkey_score(agents: StoreAgentsResponse) -> MealKeyScore:
    """计算 MealKey Score 统一健康分。"""
    dimensions: list[ScoreDimension] = []
    total = 0.0

    for key, (label, agent_name, weight) in _DIMENSION_WEIGHTS.items():
        if agent_name == "_trend":
            score = _compute_trend_score(agents)
        else:
            score = _get_agent_score(agents, agent_name)
        weighted = round(score * weight, 1)
        total += weighted
        dimensions.append(
            ScoreDimension(
                key=key,
                label=label,
                score=score,
                weight=weight,
                weighted_score=weighted,
                source_agent=agent_name if agent_name != "_trend" else "store_state",
            )
        )

    total_int = round(total)
    return MealKeyScore(
        total=total_int,
        dimensions=dimensions,
        judgment=_build_judgment(total_int, dimensions),
    )


# ---------------------------------------------------------------------------
# Operation Score（运营基本功分，步骤 7）
# ---------------------------------------------------------------------------

# 各运营指标的阈值（低于 watch 线扣分，低于 risk 线重扣）
_OP_THRESHOLDS = {
    "meal_prep_rate": {"watch": 0.92, "risk": 0.85, "weight": 20, "label": "出餐率"},
    "im_reply_rate": {"watch": 0.80, "risk": 0.60, "weight": 15, "label": "IM回复率"},
    "on_time_delivery_rate": {"watch": 0.90, "risk": 0.80, "weight": 15, "label": "配送准时率"},
    "merchant_cancel_rate": {"watch": 0.03, "risk": 0.05, "weight": 15, "label": "商责取消率", "invert": True},
    "hero_sku_in_stock_rate": {"watch": 0.95, "risk": 0.90, "weight": 20, "label": "核心商品在售率"},
    "decoration_completeness": {"watch": 0.80, "risk": 0.60, "weight": 10, "label": "装修完整度"},
}


def _score_metric(value: float | None, watch: float, risk: float, invert: bool = False) -> tuple[int | None, str]:
    """把一个运营指标值映射为 0-100 分 + 状态。None → (None, unknown)。"""
    if value is None:
        return None, "unknown"
    if invert:
        # 取消率：越低越好
        if value <= risk:
            return 90, "ok"
        if value <= watch:
            return 65, "watch"
        return 35, "risk"
    else:
        if value >= watch:
            return 90, "ok"
        if value >= risk:
            return 65, "watch"
        return 35, "risk"


def compute_operation_score(platform: PlatformHealthState) -> OperationScore:
    """计算运营基本功分。

    基于出餐率/回复率/准时率/取消率/核心SKU在售率/装修完整度 + 营业状态。
    数据未接入时维度为 None，data_coverage 标注降级。
    """
    dimensions: list[OperationDimension] = []
    available_weight = 0
    weighted_sum = 0.0
    has_any_data = False

    for key, cfg in _OP_THRESHOLDS.items():
        value = getattr(platform, key, None)
        score, status = _score_metric(
            value, cfg["watch"], cfg["risk"], invert=cfg.get("invert", False)
        )
        dimensions.append(
            OperationDimension(
                key=key,
                label=cfg["label"],
                score=score,
                status=status,
                note=f"{cfg['label']}={value:.0%}" if value is not None else "待平台运营指标接入",
            )
        )
        if score is not None:
            available_weight += cfg["weight"]
            weighted_sum += score * cfg["weight"]
            has_any_data = True

    # 营业状态（特殊处理：闭店直接重扣）
    open_score = 90 if platform.open_status == "open" else (30 if platform.open_status == "closed" else None)
    dimensions.append(
        OperationDimension(
            key="open_status",
            label="营业状态",
            score=open_score,
            status="ok" if open_score and open_score >= 70 else ("risk" if open_score else "unknown"),
            note=f"营业状态={platform.open_status}",
        )
    )
    if open_score is not None:
        available_weight += 5
        weighted_sum += open_score * 5
        has_any_data = True

    # 活动有效状态
    activity_score = None
    if platform.activity_valid is True:
        activity_score = 90
    elif platform.activity_valid is False:
        activity_score = 50
    dimensions.append(
        OperationDimension(
            key="activity",
            label="活动有效",
            score=activity_score,
            status="ok" if activity_score and activity_score >= 70 else ("watch" if activity_score else "unknown"),
            note="活动有效" if platform.activity_valid else ("活动失效" if platform.activity_valid is False else "未知"),
        )
    )
    if activity_score is not None:
        available_weight += 5
        weighted_sum += activity_score * 5
        has_any_data = True

    # 总分：基于可用维度的加权平均
    total = round(weighted_sum / available_weight) if available_weight > 0 else None
    coverage = "full" if available_weight >= 80 else ("partial" if available_weight >= 30 else "none")

    # judgment
    judgment = None
    if total is not None:
        if total >= 80:
            judgment = "运营基本功扎实，无明显风险。"
        elif total >= 65:
            judgment = "运营基本功尚可，部分指标需关注。"
        elif total >= 50:
            judgment = "运营基本功偏弱，风险正在积累。"
        else:
            judgment = "运营基本功承压，需优先修复基础指标。"
        # 找最弱维度
        weakest = min(
            (d for d in dimensions if d.score is not None),
            key=lambda d: d.score,
            default=None,
        )
        if weakest and weakest.score < 60:
            judgment = f"{judgment}主要拖累在{weakest.label}。"

    return OperationScore(
        total=total,
        dimensions=dimensions,
        data_coverage=coverage,
        judgment=judgment,
    )
