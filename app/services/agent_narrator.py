"""Agent Narrator: 把规则引擎算出的结构化结果，用 LLM 重写成更自然的中文总结。

设计原则（沿用 storefront_ai 的成熟模式）：
1. 规则引擎继续负责"算分、定优先级、给证据"——这部分必须确定性、可审计；
2. LLM 只负责"把数字和列表讲成人话"——这是它的强项；
3. 无 LLM 配置或调用失败时，自动回退到规则引擎原本的 conclusion，零行为变化。

接入点：diagnosis / review / menu / product / growth。
不接入：competition（事实型，已有足够 narrative）、矩阵 agent（阈值化结论，LLM 收益低）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from app.services.llm_engine.gateway import call_llm, is_llm_configured

logger = logging.getLogger(__name__)

# 统一长度上限，避免 narrative 把整页撑爆
_MAX_TOKENS = 600


def _agent_llm_enabled() -> bool:
    """Agent narrative LLM 总开关。

    默认关闭（"0"/未设置）：narrator 直接回退到规则引擎的 conclusion，
    保证测试稳定、且新功能默认不影响现有行为。
    显式设置 MEALKY_AGENT_LLM=1 后才会真正调用 LLM。
    生产环境想启用时，在 .env / 环境变量里设置即可。
    """
    return os.getenv("MEALKY_AGENT_LLM", "0").strip() in {"1", "true", "yes", "on"}


def _safe_json_extract(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # 去掉 ```json ... ``` 包裹
    import re

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


def _call_for_narrative(
    *,
    system: str,
    context: dict[str, Any],
    purpose: str = "general.consulting",
    temperature: float = 0.5,
) -> Optional[str]:
    """统一的 LLM 调用 + fallback。返回 narrative 字符串，或 None（调用方用原 conclusion）。"""
    if not _agent_llm_enabled() or not is_llm_configured(purpose):
        return None
    try:
        result = call_llm(
            purpose=purpose,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"诊断事实：\n{json.dumps(context, ensure_ascii=False)}"},
            ],
            temperature=temperature,
            max_tokens=_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_narrator LLM call failed: %s", exc)
        return None
    if not result.ok:
        return None
    parsed = _safe_json_extract(result.content)
    if parsed and isinstance(parsed.get("narrative"), str) and parsed["narrative"].strip():
        return parsed["narrative"].strip()
    # 模型没按 JSON 格式返回时，整段内容作为 narrative（只要不太长）
    content = (result.content or "").strip()
    return content[:400] if content else None


# ---------------------------------------------------------------------------
# 各 agent 的专用 narrator
# ---------------------------------------------------------------------------


def narrate_diagnosis(
    *,
    store_name: str,
    diagnosis_score: int,
    primary_problem: str,
    daily_summary: str,
    root_causes: list[dict[str, Any]],
    metric_signals: list[dict[str, Any]],
    next_actions: list[str],
    fallback_summary: str,
) -> Optional[str]:
    """经营诊断 Agent 的自然语言总结。LLM 未启用/失败时返回 None，调用方回退到 fallback_summary。"""
    system = (
        "你是 MealKey 的外卖经营诊断顾问。"
        "根据规则引擎算出的诊断事实，写一段给老板看的经营总结。"
        "要求：口语化、不堆术语、先讲核心问题再讲下一步、不超过 150 字。"
        "只输出 JSON：{\"narrative\": \"...\"}。不要 Markdown。"
    )
    context = {
        "store_name": store_name,
        "diagnosis_score": diagnosis_score,
        "primary_problem": primary_problem,
        "daily_summary": daily_summary,
        "root_causes": [
            {"title": r.get("title"), "explanation": r.get("explanation"), "confidence": r.get("confidence")}
            for r in root_causes[:2]
        ],
        "key_metrics": [
            {"metric": m.get("label") or m.get("metric"), "delta_pct": m.get("delta_pct")}
            for m in metric_signals
            if m.get("delta_pct") is not None
        ][:4],
        "next_actions": next_actions[:2],
    }
    return _call_for_narrative(system=system, context=context)


def narrate_review(
    *,
    store_name: str,
    avg_rating: Optional[float],
    top_themes: list[dict[str, Any]],
    pending_replies: int,
    fallback_conclusion: str,
) -> Optional[str]:
    """评分评价 Agent 的自然语言总结。LLM 未启用/失败时返回 None。"""
    if not top_themes and avg_rating is None:
        return None
    system = (
        "你是外卖店铺评价分析顾问。"
        "根据评价主题分布，写一段给老板看的评价总结：点出最该先治理的问题、给出明确动作方向。"
        "口语化、不堆数据、不超过 120 字。"
        "只输出 JSON：{\"narrative\": \"...\"}。"
    )
    context = {
        "store_name": store_name,
        "avg_rating": avg_rating,
        "top_themes": [
            {"label": t.get("label"), "share_pct": t.get("share_pct"), "sample": t.get("sample")}
            for t in top_themes[:3]
        ],
        "pending_replies": pending_replies,
    }
    return _call_for_narrative(system=system, context=context)


def narrate_menu(
    *,
    store_name: str,
    menu_health_score: int,
    role_distribution: dict[str, int],
    structural_gaps: list[str],
    suggested_patches: list[dict[str, Any]],
    cleanup_candidates: list[dict[str, Any]],
    fallback_summary: Optional[str],
) -> Optional[str]:
    """菜单 Agent 的自然语言总结。LLM 未启用/失败时返回 None。"""
    if not structural_gaps and not suggested_patches and not cleanup_candidates:
        return None
    role_labels = {
        "Hero Product": "主推款",
        "Traffic Product": "引流款",
        "Basket Builder": "搭配品",
        "Profit Product": "利润款",
        "Zombie SKU": "低效SKU",
    }
    system = (
        "你是外卖店铺菜单结构顾问。"
        "根据菜单角色分布和结构缺口，写一段给老板看的菜单优化总结：先讲结构问题、再讲今天先做什么。"
        "口语化、不堆 SKU 名字、不超过 130 字。"
        "只输出 JSON：{\"narrative\": \"...\"}。"
    )
    context = {
        "store_name": store_name,
        "menu_health_score": menu_health_score,
        "role_distribution": {role_labels.get(k, k): v for k, v in role_distribution.items()},
        "structural_gaps": structural_gaps[:3],
        "suggested_first_patch": (
            {
                "item_name": suggested_patches[0].get("item_name"),
                "target_role": role_labels.get(
                    suggested_patches[0].get("target_role", ""),
                    suggested_patches[0].get("target_role"),
                ),
                "reason": suggested_patches[0].get("reason"),
            }
            if suggested_patches
            else None
        ),
        "cleanup_count": len(cleanup_candidates),
    }
    return _call_for_narrative(system=system, context=context)


def narrate_growth(
    *,
    store_name: str,
    selected_title: Optional[str],
    weekly_goal: str,
    experiments_summary: dict[str, int],
    learning_summary: str,
    do_not_do: list[str],
    fallback_reason: str,
) -> Optional[str]:
    """增长 Agent 的自然语言总结。LLM 未启用/失败时返回 None。"""
    system = (
        "你是外卖店铺增长策略顾问。"
        "根据本周选定的唯一主动作和历史实验结果，写一段给老板看的本周增长指引。"
        "强调'今天先做什么'和'不要做什么'，口语化、不超过 140 字。"
        "只输出 JSON：{\"narrative\": \"...\"}。"
    )
    context = {
        "store_name": store_name,
        "selected_action": selected_title,
        "weekly_goal": weekly_goal,
        "experiments": experiments_summary,
        "learning": learning_summary,
        "do_not_do": do_not_do[:2],
    }
    return _call_for_narrative(system=system, context=context)
