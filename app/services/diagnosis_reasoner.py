"""LLM Diagnosis Reasoner — 把诊断从 if-else 模板升级为 LLM 推理。

核心原则：
- 规则负责筛信号（确定性、可审计）：CTR delta <= -5% → 触发诊断
- LLM 负责推理根因（智能、上下文感知）：结合竞品/评价/活动/价格综合判断

降级链：
1. LLM 可用 → LLM 推理根因 + 候选动作
2. LLM 不可用/失败 → 回退到规则模板（保证可用性）
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from app.services.llm_engine.gateway import call_llm, is_llm_configured

logger = logging.getLogger(__name__)


def _diagnosis_llm_enabled() -> bool:
    """LLM 诊断推理器开关。

    默认关闭（"0"）：diagnosis_reasoner 直接回退到规则模板。
    显式设置 MEALKY_DIAGNOSIS_LLM=1 后才会真正调用 LLM 推理。
    """
    return os.getenv("MEALKY_DIAGNOSIS_LLM", "0").strip() in {"1", "true", "yes", "on"}


def _build_diagnosis_context(
    *,
    metric: str,
    delta_pct: float | None,
    store_name: str = "",
    item_name: str = "",
    kpis: dict[str, Any] | None = None,
    competition_changes: list[Any] | None = None,
    recent_reviews: list[dict] | None = None,
    active_campaigns: list[str] | None = None,
    price_vs_market: float | None = None,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建给 LLM 的诊断上下文。"""
    ctx: dict[str, Any] = {
        "metric": metric,
        "delta_pct": delta_pct,
        "store": store_name,
        "item": item_name,
    }
    if kpis:
        ctx["kpis"] = {
            k: {
                "value": getattr(v, "observed_value", None) if hasattr(v, "observed_value") else v,
                "delta_pct": getattr(v, "delta_pct", None) if hasattr(v, "delta_pct") else None,
            }
            for k, v in list(kpis.items())[:8]
        }
    if competition_changes:
        ctx["competition"] = [
            getattr(c, "summary", str(c))[:80]
            for c in competition_changes[:3]
        ]
    if recent_reviews:
        ctx["recent_reviews"] = [
            {"rating": r.get("rating"), "text": (r.get("text") or "")[:60]}
            for r in recent_reviews[:3]
        ]
    if active_campaigns:
        ctx["active_campaigns"] = active_campaigns
    if price_vs_market is not None:
        ctx["price_vs_market_ratio"] = round(price_vs_market, 2)
    if extra_context:
        ctx.update(extra_context)
    return ctx


def llm_diagnose_root_cause(
    *,
    metric: str,
    delta_pct: float | None,
    store_name: str = "",
    item_name: str = "",
    kpis: dict[str, Any] | None = None,
    competition_changes: list[Any] | None = None,
    recent_reviews: list[dict] | None = None,
    active_campaigns: list[str] | None = None,
    price_vs_market: float | None = None,
    fallback_root_cause: str = "",
    fallback_funnel_stage: str = "",
) -> dict[str, Any]:
    """LLM 推理根因——把规则筛出的信号交给 LLM 做上下文感知的诊断。

    返回：
    {
        "root_cause": "...",           # LLM 推理的根因
        "funnel_stage": "ctr/cvr/...",  # 漏斗定位
        "competing_causes": [...],     # 竞争性假说
        "evidence": [...],             # 证据链
        "confidence": 0.0-1.0,
        "candidate_actions": [...],    # 候选动作
        "source": "llm" / "rule_fallback"
    }
    """
    # 规则模板降级
    rule_result = _rule_diagnose(metric, delta_pct, fallback_root_cause, fallback_funnel_stage)

    if not _diagnosis_llm_enabled() or not is_llm_configured("general.consulting"):
        return {**rule_result, "source": "rule_fallback"}

    context = _build_diagnosis_context(
        metric=metric,
        delta_pct=delta_pct,
        store_name=store_name,
        item_name=item_name,
        kpis=kpis,
        competition_changes=competition_changes,
        recent_reviews=recent_reviews,
        active_campaigns=active_campaigns,
        price_vs_market=price_vs_market,
    )

    system = (
        "你是 MealKey AI 店长的诊断引擎。你的任务是根据经营数据推理根因。\n"
        "规则引擎已经检测到信号（如 CTR 下降），但根因需要你结合上下文推理。\n"
        "要求：\n"
        "1. 给出最可能的根因（primary），列出 1-2 个竞争性假说（alternatives）\n"
        "2. 每个判断要有证据支撑\n"
        "3. 给出 1-2 个候选动作（单变量测试原则）\n"
        "4. 只输出 JSON，不要 Markdown\n"
        "输出格式：\n"
        '{"root_cause":"","funnel_stage":"","competing_causes":[],"evidence":[],"confidence":0.0,"candidate_actions":[{"action":"","primary_variable":"","risk":""}]}'
    )

    try:
        result = call_llm(
            purpose="general.consulting",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"诊断上下文：\n{json.dumps(context, ensure_ascii=False, default=str)}"},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        if not result.ok or not result.content:
            return {**rule_result, "source": "rule_fallback", "llm_error": result.reason}

        # 解析 LLM 输出
        parsed = _safe_parse_json(result.content)
        if parsed and "root_cause" in parsed:
            return {
                "root_cause": parsed.get("root_cause", rule_result["root_cause"]),
                "funnel_stage": parsed.get("funnel_stage", rule_result["funnel_stage"]),
                "competing_causes": parsed.get("competing_causes", [])[:3],
                "evidence": parsed.get("evidence", [])[:5],
                "confidence": min(0.95, max(0.3, float(parsed.get("confidence", 0.7)))),
                "candidate_actions": parsed.get("candidate_actions", [])[:3],
                "source": "llm",
                "llm": {
                    "provider": result.provider,
                    "model": result.model,
                    "tokens": result.total_tokens,
                },
            }
        # JSON 解析失败，用原始内容当 root_cause
        return {
            **rule_result,
            "root_cause": result.content[:200],
            "source": "llm_raw",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM diagnose failed: %s", exc)
        return {**rule_result, "source": "rule_fallback", "error": str(exc)[:100]}


def llm_diagnose_product_issue(
    *,
    item_name: str,
    item_role: str = "",
    ctr: float | None = None,
    ctr_baseline: float | None = None,
    ctr_delta: float | None = None,
    cvr: float | None = None,
    cvr_baseline: float | None = None,
    cvr_delta: float | None = None,
    orders: int | None = None,
    order_share: float | None = None,
    rating: float | None = None,
    price: float | None = None,
    market_avg_price: float | None = None,
    competition_summary: list[str] | None = None,
    review_themes: list[str] | None = None,
) -> dict[str, Any]:
    """LLM 推理单品问题——比规则 if-else 更精准。

    例如：不只是"CTR 下降 → 换主图"，
    而是"CTR 下降 15%，但竞品 2 家也换了图，且你的评分稳定 → 判断为主图竞争力相对下降，建议强调份量感"。
    """
    if not _diagnosis_llm_enabled() or not is_llm_configured("general.consulting"):
        return _rule_product_diagnose(ctr_delta, cvr_delta, item_name)

    context = {
        "item": item_name,
        "role": item_role,
        "ctr": ctr,
        "ctr_baseline": ctr_baseline,
        "ctr_delta_pct": ctr_delta,
        "cvr": cvr,
        "cvr_baseline": cvr_baseline,
        "cvr_delta_pct": cvr_delta,
        "orders": orders,
        "order_share_pct": order_share,
        "rating": rating,
        "price": price,
        "market_avg_price": market_avg_price,
        "price_ratio": round(price / market_avg_price, 2) if price and market_avg_price else None,
        "competition": competition_summary[:3] if competition_summary else [],
        "review_themes": review_themes[:3] if review_themes else [],
    }

    system = (
        "你是外卖商品诊断专家。根据商品漏斗数据推理问题根因，给出单变量测试建议。\n"
        "铁律：一次实验只改一个主要变量。\n"
        "只输出 JSON：\n"
        '{"diagnosis":"","root_cause":"","confidence":0.0,"evidence":[],"candidate_actions":[{"action":"","primary_variable":"","expected_window_hours":48,"risk":"low"}],"dependencies":[]}'
    )

    try:
        result = call_llm(
            purpose="general.consulting",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"商品数据：\n{json.dumps(context, ensure_ascii=False, default=str)}"},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        if not result.ok or not result.content:
            return _rule_product_diagnose(ctr_delta, cvr_delta, item_name)

        parsed = _safe_parse_json(result.content)
        if parsed and "diagnosis" in parsed:
            parsed["source"] = "llm"
            parsed["llm"] = {"provider": result.provider, "model": result.model, "tokens": result.total_tokens}
            return parsed
        return {**_rule_product_diagnose(ctr_delta, cvr_delta, item_name), "source": "llm_raw", "raw": result.content[:200]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM product diagnose failed: %s", exc)
        return _rule_product_diagnose(ctr_delta, cvr_delta, item_name)


# ═══════════════════════════════════════════════════════════
# 规则降级（保证 LLM 不可用时仍有诊断）
# ═══════════════════════════════════════════════════════════


def _rule_diagnose(
    metric: str,
    delta_pct: float | None,
    fallback_root_cause: str,
    fallback_funnel_stage: str,
) -> dict[str, Any]:
    """规则模板降级（保持原有逻辑不变）。"""
    if delta_pct is None:
        return {
            "root_cause": fallback_root_cause or "数据不足，暂无法判断主要原因",
            "funnel_stage": fallback_funnel_stage,
            "competing_causes": [],
            "evidence": [],
            "confidence": 0.5,
            "candidate_actions": [],
            "source": "rule",
        }

    if metric == "ctr":
        return {
            "root_cause": fallback_root_cause or "主推商品的第一眼竞争力下降（主图/标题/价格感知）",
            "funnel_stage": "ctr",
            "competing_causes": ["竞品近期换图/改标题", "价格带出现缺口"],
            "evidence": [f"CTR delta = {delta_pct:.1f}%"],
            "confidence": 0.75,
            "candidate_actions": [
                {"action": "测试新主图", "primary_variable": "image", "risk": "low"},
            ],
            "source": "rule",
        }
    if metric == "cvr":
        return {
            "root_cause": fallback_root_cause or "用户愿意点进来但不下单（价格/套餐/评价/配送预期）",
            "funnel_stage": "cvr",
            "competing_causes": ["差评主题上升", "套餐结构不足"],
            "evidence": [f"CVR delta = {delta_pct:.1f}%"],
            "confidence": 0.72,
            "candidate_actions": [
                {"action": "补充套餐", "primary_variable": "bundle", "risk": "medium"},
            ],
            "source": "rule",
        }
    return {
        "root_cause": fallback_root_cause or "订单下滑，优先排查 CTR/CVR 与核心 SKU 表现",
        "funnel_stage": fallback_funnel_stage or "orders",
        "competing_causes": [],
        "evidence": [f"{metric} delta = {delta_pct:.1f}%"],
        "confidence": 0.65,
        "candidate_actions": [],
        "source": "rule",
    }


def _rule_product_diagnose(
    ctr_delta: float | None,
    cvr_delta: float | None,
    item_name: str,
) -> dict[str, Any]:
    """单品规则降级。"""
    if ctr_delta is not None and ctr_delta <= -5:
        return {
            "diagnosis": f"{item_name} CTR 下降 {ctr_delta:.1f}%",
            "root_cause": "主图/标题竞争力下降",
            "confidence": 0.78,
            "evidence": [f"CTR delta = {ctr_delta:.1f}%"],
            "candidate_actions": [{"action": "测试新主图", "primary_variable": "image", "expected_window_hours": 48, "risk": "low"}],
            "dependencies": ["competition"],
            "source": "rule",
        }
    if cvr_delta is not None and cvr_delta <= -5:
        return {
            "diagnosis": f"{item_name} CVR 下降 {cvr_delta:.1f}%",
            "root_cause": "价格/套餐/评价导致转化下降",
            "confidence": 0.75,
            "evidence": [f"CVR delta = {cvr_delta:.1f}%"],
            "candidate_actions": [{"action": "补充套餐", "primary_variable": "bundle", "expected_window_hours": 72, "risk": "medium"}],
            "dependencies": ["profit"],
            "source": "rule",
        }
    return {
        "diagnosis": f"{item_name} 状态正常",
        "root_cause": "",
        "confidence": 0.7,
        "evidence": [],
        "candidate_actions": [],
        "dependencies": [],
        "source": "rule",
    }


def _safe_parse_json(text: str) -> dict[str, Any] | None:
    """安全解析 LLM 输出的 JSON（兼容 ```json 包裹和前后多余文本）。"""
    import re

    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
    return None
