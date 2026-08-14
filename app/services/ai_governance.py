"""AI 治理层 — 需求 #181-185。

让老板能问 AI:
- "为什么这个判断?" (#182)
- "用了哪些数据,缺哪些?" (#183)
- "你有多大把握?" (#184)
- "不做最坏损失多少?" (#185)
- "为什么昨天没提醒我?" (#181)

这些不是新功能,是把已有 ActionTrace/MoneyItem/ProfitState 的 provenance 信息组织成可解释的答案。
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_trace import ActionTrace
from app.models.ohre import Recommendation
from app.models.strategy_memory import StrategyMemoryRecord
from app.models.thread import OperatingThread


def explain_judgment(db: Session, store_id: str, *, recommendation_id: str = "", question: str = "") -> dict[str, Any]:
    """解释 AI 的判断依据。需求 #182。

    返回:
    - primary_reason: 为什么做这个判断
    - evidence: 用了哪些数据
    - missing_data: 还缺哪些数据
    - confidence: 把握有多大
    - alternatives: 其他可能但未选的方案
    """
    result: dict[str, Any] = {
        "primary_reason": "",
        "evidence": [],
        "missing_data": [],
        "confidence": 0.0,
        "alternatives": [],
    }

    # 如果有 recommendation_id, 从 ActionTrace 找依据
    if recommendation_id:
        traces = list(
            db.execute(
                select(ActionTrace)
                .where(ActionTrace.recommendation_id == recommendation_id)
                .order_by(ActionTrace.created_at.desc())
                .limit(3)
            ).scalars()
        )
        for trace in traces:
            if trace.diagnosis_summary:
                result["primary_reason"] = trace.diagnosis_summary
            if trace.confidence:
                result["confidence"] = max(result["confidence"], trace.confidence)
            if trace.evidence_json:
                import json
                try:
                    ev = json.loads(trace.evidence_json)
                    if isinstance(ev, list):
                        result["evidence"].extend(ev[:3])
                except Exception:  # noqa: BLE001
                    pass

    # 如果问题包含"为什么"
    if question and not result["primary_reason"]:
        result["primary_reason"] = _rule_explain(question, store_id, db)

    return result


def explain_data_provenance(db: Session, store_id: str) -> dict[str, Any]:
    """解释这次判断用了哪些数据,缺哪些。需求 #183。"""
    from app.services.business_import import get_data_coverage

    coverage = get_data_coverage(db, store_id)

    used: list[str] = []
    missing: list[str] = []

    if coverage.get("funnel_days", 0) > 0:
        used.append(f"经营数据({coverage['funnel_days']}天)")
    else:
        missing.append("经营数据(曝光/订单/GMV)")

    if coverage.get("ads_days", 0) > 0:
        used.append(f"投流数据({coverage['ads_days']}天)")
    else:
        missing.append("投流数据(CPC/ROAS)")

    if coverage.get("reviews", 0) > 0:
        used.append(f"评价数据({coverage['reviews']}条)")
    else:
        missing.append("评价数据")

    if coverage.get("cost_coverage_pct", 0) > 50:
        used.append(f"成本数据({coverage['cost_coverage_pct']:.0f}%覆盖)")
    else:
        missing.append(f"成本数据(当前仅{coverage['cost_coverage_pct']:.0f}%覆盖)")

    return {
        "data_used": used,
        "data_missing": missing,
        "confidence_impact": "数据缺失会降低诊断可信度,建议补齐" if missing else "数据较完整,诊断可信",
    }


def confidence_display(confidence: float | None) -> dict[str, Any]:
    """把置信度数值转化为人类可读的把握度。需求 #184。"""
    if confidence is None:
        return {"level": "unknown", "label": "暂无足够数据判断", "pct": 0}

    pct = round(confidence * 100)
    if confidence >= 0.85:
        level = "high"
        label = "高把握"
    elif confidence >= 0.65:
        level = "medium"
        label = "中等把握"
    elif confidence >= 0.4:
        level = "low"
        label = "把握不高,建议进一步确认"
    else:
        level = "very_low"
        label = "数据不足,仅供参考"

    return {"level": level, "label": label, "pct": pct}


def worst_case_if_nothing(store_id: str, db: Session) -> dict[str, Any]:
    """如果什么都不做,最坏可能损失多少。需求 #185。"""
    from app.services.store_state import build_store_state

    state = build_store_state(db, store_id, days=7)
    if not state:
        return {"estimated_daily_loss": 0, "reason": "无法获取门店状态"}

    profit = state.profit
    reasons: list[str] = []

    # 检查利润趋势
    if profit.contribution_profit_delta_pct is not None and profit.contribution_profit_delta_pct < -5:
        daily_profit = profit.contribution_profit or 0
        daily_loss = abs(daily_profit * profit.contribution_profit_delta_pct / 100)
        reasons.append(f"利润下降 {profit.contribution_profit_delta_pct:.1f}%,如不干预可能持续每日损失 ¥{daily_loss:.0f}")

    # 检查 CTR 趋势
    ctr_delta = state.kpis.get("ctr")
    if ctr_delta and ctr_delta.delta_pct is not None and ctr_delta.delta_pct < -10:
        reasons.append(f"CTR 下降 {ctr_delta.delta_pct:.1f}%,持续恶化会导致曝光进一步缩减")

    # 检查差评
    if state.feedback.bad_review_rate and state.feedback.bad_review_rate > 0.2:
        reasons.append(f"差评率 {state.feedback.bad_review_rate:.0%},持续会降低排名和转化")

    # 检查投流效率
    if state.ads_summary.avg_roas and state.ads_summary.avg_roas < 2.0:
        daily_ads = state.ads_summary.avg_daily_cost or 0
        reasons.append(f"ROAS 仅 {state.ads_summary.avg_roas:.1f},每日投流 ¥{daily_ads:.0f} 可能亏损")

    if not reasons:
        return {"estimated_daily_loss": 0, "reason": "当前没有明显的恶化趋势,维持现状风险较低"}

    return {
        "estimated_daily_loss": None,
        "reasons": reasons,
        "recommendation": "建议尽快处理上述问题",
    }


def _rule_explain(question: str, store_id: str, db: Session) -> str:
    """规则模板:从问题推断解释方向。"""
    q = question.lower()
    if "为什么" in q and ("订单" in q or "单" in q):
        return "订单变化通常由曝光、CTR、CVR、客单价、活动、竞品、差评、退款等因素共同决定。"
    if "为什么" in q and "利润" in q:
        return "利润变化需要拆解 GMV、佣金、补贴、成本、推广费、退款等因子才能定位。"
    if "为什么" in q and ("提醒" in q or "没说" in q):
        return "系统会按优先级推送最重要的事情。如果昨天没有提醒,可能是因为信号未达到触发阈值。"
    return "这个判断基于当前可获取的经营数据。如果数据不完整,判断可信度会受影响。"
