from __future__ import annotations

import json
from typing import Any

from app.services.llm_engine.gateway import call_llm, is_llm_configured


def _compact_dashboard_context(dashboard: dict[str, Any]) -> str:
    store = dashboard.get("store") or {}
    brief = dashboard.get("daily_brief") or {}
    hypothesis = dashboard.get("hypothesis") or {}
    competition = dashboard.get("competition") or {}
    today = dashboard.get("today_action") or {}
    payload = {
        "store": {
            "name": store.get("name"),
            "city": store.get("city"),
            "area": store.get("area"),
            "category": store.get("category"),
        },
        "health_score": dashboard.get("health_score"),
        "daily_brief": {
            "yesterday_change": brief.get("yesterday_change"),
            "reason": brief.get("reason"),
            "verify_metric": brief.get("verify_metric"),
        },
        "hypothesis": {
            "root_cause": hypothesis.get("root_cause"),
            "confidence": hypothesis.get("confidence"),
        },
        "competition": {
            "strategy": competition.get("strategy") or competition.get("conclusion"),
            "nearby_total": competition.get("nearby_total"),
        },
        "today_action": {
            "title": today.get("title"),
            "status": today.get("status"),
            "expected_metric": today.get("expected_metric"),
        },
        "metrics": [
            {
                "key": row.get("key"),
                "value": row.get("value"),
                "delta_pct": row.get("delta_pct"),
            }
            for row in (dashboard.get("metrics") or [])[:6]
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def answer_with_llm(question: str, dashboard: dict[str, Any]) -> dict[str, Any] | None:
    if not is_llm_configured("general.consulting"):
        return None

    system = (
        "你是 MealKey 餐启的 AI 店长，服务中国外卖门店老板。"
        "只用给定经营事实回答，不要编造未提供的数据。"
        "回答要短、可执行：先给结论，再给 1-3 条依据，再给今天可做的 1-2 个动作。"
        "输出纯中文，不要用 Markdown 标题。"
    )
    user = (
        f"老板问题：{question}\n\n"
        f"门店经营事实 JSON：\n{_compact_dashboard_context(dashboard)}\n\n"
        "请直接给经营建议。"
    )
    result = call_llm(
        purpose="general.consulting",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.35,
        max_tokens=900,
    )
    if not result.ok or not result.content:
        return None

    lines = [line.strip() for line in result.content.splitlines() if line.strip()]
    conclusion = lines[0] if lines else result.content
    actions = [line.lstrip("-• ").strip() for line in lines[1:] if "做" in line or "先" in line][:3]
    if not actions and len(lines) > 1:
        actions = lines[1:3]

    return {
        "question": question,
        "question_type": "llm_consulting",
        "conclusion": conclusion,
        "reasons": lines[1:4] if len(lines) > 1 else [f"由 {result.provider}/{result.model} 基于当前看板生成"],
        "actions": actions or ["先确认今日主动作并执行"],
        "expected": "先做完主动作，再按验证指标复盘。",
        "confidence": "high",
        "answer": result.content,
        "llm": {
            "provider": result.provider,
            "model": result.model,
            "model_slug": result.model_slug,
            "latency_ms": result.latency_ms,
            "failover_used": result.failover_used,
            "tokens": result.total_tokens,
        },
    }
