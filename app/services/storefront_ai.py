"""
AI 协助线上装修 & 图片优化

独立部署：优先走本仓 llm_engine；无 Key 时回退规则模板，保证页面始终可用。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.services.llm_engine.gateway import call_llm, is_llm_configured
from app.schemas.agents import StorefrontAgentResult


def _parse_json_block(text: str) -> dict[str, Any] | None:
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


def _heuristic_decorate(storefront: StorefrontAgentResult, store_name: str, category: str | None) -> dict[str, Any]:
    top_issue = storefront.issues[0] if storefront.issues else None
    top_action = storefront.priority_actions[0] if storefront.priority_actions else None
    steps = []
    for index, action in enumerate(storefront.priority_actions[:3], start=1):
        brief = action.generated_content or {}
        tip = (
            brief.get("visual_brief")
            or brief.get("ia_brief")
            or brief.get("bundle_brief")
            or brief.get("trust_brief")
            or action.detail
        )
        steps.append(
            {
                "order": index,
                "title": action.title,
                "why": action.detail,
                "how": tip,
                "verify": f"上线后观察 {action.expected_metric.upper()} {int(action.window_hours)} 小时",
                "action_type": action.action_type,
            }
        )
    if not steps:
        steps = [
            {
                "order": 1,
                "title": "先补主推近景主图",
                "why": "第一眼决定点击",
                "how": "45°近景，主菜占画面 70%，突出分量与热气，无贴纸。",
                "verify": "观察 CTR 24 小时",
                "action_type": "refresh_hero_image",
            }
        ]
    return {
        "mode": "heuristic",
        "title": f"{store_name} 线上装修协助方案",
        "summary": storefront.conclusion
        or f"当前优先处理：{top_issue.title if top_issue else '维持主图与套餐观察'}。",
        "sales_focus": (storefront.sales_impact.narrative if storefront.sales_impact else storefront.expected_impact),
        "steps": steps,
        "do_not_do": [
            "不要一次改主图+标题+价格，无法归因。",
            "不要用过度美颜导致图实不符。",
            "不要堆满促销贴纸挡住菜品。",
        ],
        "next_action": top_action.title if top_action else "先生成一条装修动作并采纳",
        "copy_pack": {
            "store_tagline": f"{category or '本店'}招牌，分量足、出餐稳",
            "signature_title": "招牌必点 · 真实分量",
            "set_meal_title": "超值单人餐 · 少选择更省心",
        },
    }


def _heuristic_image_optimize(
    *,
    item_name: str,
    category: str | None,
    storefront: StorefrontAgentResult,
    problem: str | None,
) -> dict[str, Any]:
    weak_hero = any(i.code in {"weak_hero_visual", "signature_ctr_slide"} for i in storefront.issues)
    return {
        "mode": "heuristic",
        "title": f"「{item_name}」主图优化方案",
        "goal": "提升第一眼点击（CTR），同时避免图实不符伤害转化",
        "problem": problem or ("主图竞争力偏弱" if weak_hero else "主图可继续强化卖点"),
        "shot_list": [
            "45°俯侧拍，主菜居中占画面 65%-75%",
            "自然光或暖光，突出热气/酱汁反光",
            "干净浅色或木纹背景，桌面不杂乱",
            "可加一双筷子/小碟衬托分量，不加文字贴纸",
        ],
        "prompt_zh": (
            f"外卖菜品摄影，{category or '中式'}「{item_name}」，真实分量，"
            "近景45度，热气与酱汁清晰，食欲感强，无文字无贴纸，商业美食摄影"
        ),
        "prompt_en": (
            f"food photography of {item_name}, generous real portion, 45-degree close-up, "
            "steam and glossy sauce, appetizing, no text overlay, commercial restaurant style"
        ),
        "checklist": [
            "主菜是否一眼可识别",
            "是否看得出分量足",
            "是否有热气/质感",
            "是否无促销字/水印",
            "是否与出餐实物一致",
        ],
        "before_after_tips": [
            "Before：远景、偏暗、贴纸多 → After：近景、提亮、去贴纸",
            "Before：盘子太空 → After：主菜填满视觉中心并露出配菜层次",
        ],
        "risk": "过度修图会导致差评“和实物不符”，优先真实分量表达。",
    }


def assist_storefront_decorate(
    *,
    storefront: StorefrontAgentResult,
    store_name: str,
    category: str | None = None,
    city: str | None = None,
    audience: str | None = None,
) -> dict[str, Any]:
    fallback = _heuristic_decorate(storefront, store_name, category)
    if not is_llm_configured("general.consulting"):
        return fallback

    context = {
        "store": {"name": store_name, "category": category, "city": city, "audience": audience},
        "health_score": storefront.health_score,
        "conclusion": storefront.conclusion,
        "sales_impact": storefront.sales_impact.model_dump() if storefront.sales_impact else None,
        "issues": [i.model_dump() for i in storefront.issues[:4]],
        "dimensions": [d.model_dump() for d in storefront.dimensions],
        "priority_actions": [a.model_dump() for a in storefront.priority_actions[:4]],
    }
    system = (
        "你是 MealKey 餐启的外卖店页装修顾问。"
        "根据诊断 JSON，输出可执行的线上装修协助方案。"
        "只输出 JSON，不要 Markdown。"
        "字段：title,summary,sales_focus,steps([{order,title,why,how,verify,action_type}]),"
        "do_not_do([str]),next_action,copy_pack({store_tagline,signature_title,set_meal_title})。"
        "steps 最多 3 条；文案短、老板能立刻执行；面向中国外卖平台店页。"
    )
    result = call_llm(
        purpose="general.consulting",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"诊断事实：\n{json.dumps(context, ensure_ascii=False)}"},
        ],
        temperature=0.4,
        max_tokens=1200,
    )
    if not result.ok:
        fallback["mode"] = "heuristic_fallback"
        fallback["llm_error"] = result.reason
        return fallback
    parsed = _parse_json_block(result.content)
    if not parsed:
        fallback["mode"] = "heuristic_fallback"
        fallback["llm_raw"] = result.content[:500]
        return fallback
    parsed["mode"] = "llm"
    parsed["llm"] = {
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "failover_used": result.failover_used,
    }
    # 保底字段
    for key, value in fallback.items():
        parsed.setdefault(key, value)
    return parsed


def assist_image_optimize(
    *,
    storefront: StorefrontAgentResult,
    item_name: str,
    category: str | None = None,
    store_name: str | None = None,
    has_image: bool = False,
    ctr_delta_pct: float | None = None,
    problem: str | None = None,
) -> dict[str, Any]:
    fallback = _heuristic_image_optimize(
        item_name=item_name,
        category=category,
        storefront=storefront,
        problem=problem,
    )

    if not is_llm_configured("brand.structured_output") and not is_llm_configured("general.consulting"):
        return fallback

    purpose = "brand.structured_output" if is_llm_configured("brand.structured_output") else "general.consulting"
    context = {
        "store_name": store_name,
        "item_name": item_name,
        "category": category,
        "has_image": has_image,
        "ctr_delta_pct": ctr_delta_pct,
        "problem": problem,
        "storefront_health_score": storefront.health_score,
        "related_issues": [i.model_dump() for i in storefront.issues if i.dimension_key in {"hero_image", "signature_display"}][:3],
    }
    system = (
        "你是外卖菜品主图优化顾问，服务中国美团/饿了么商家。"
        "输出可拍摄执行的主图优化方案，只输出 JSON。"
        "字段：title,goal,problem,shot_list([str]),prompt_zh,prompt_en,"
        "checklist([str]),before_after_tips([str]),risk。"
        "要求真实分量、食欲感、无文字贴纸；提示词可给设计师或AI绘图使用。"
    )
    result = call_llm(
        purpose=purpose,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"优化对象：\n{json.dumps(context, ensure_ascii=False)}"},
        ],
        temperature=0.45,
        max_tokens=1000,
    )
    if not result.ok:
        fallback["mode"] = "heuristic_fallback"
        fallback["llm_error"] = result.reason
        return fallback
    parsed = _parse_json_block(result.content)
    if not parsed:
        fallback["mode"] = "heuristic_fallback"
        fallback["llm_raw"] = result.content[:500]
        return fallback
    parsed["mode"] = "llm"
    parsed["llm"] = {
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "failover_used": result.failover_used,
    }
    for key, value in fallback.items():
        parsed.setdefault(key, value)
    return parsed


def enrich_action_with_ai(
    *,
    action: dict[str, Any],
    storefront: StorefrontAgentResult,
    store_name: str,
    category: str | None = None,
) -> dict[str, Any]:
    """给单条装修动作补充 AI 执行说明书 / 主图提示词。"""
    action_type = action.get("action_type") or ""
    if action_type in {"refresh_hero_image", "refresh_signature_card"}:
        image = assist_image_optimize(
            storefront=storefront,
            item_name=action.get("object_name") or "招牌主推",
            category=category,
            store_name=store_name,
            problem=action.get("detail"),
        )
        content = dict(action.get("generated_content") or {})
        content["visual_brief"] = image.get("shot_list", [content.get("visual_brief")])[0] if image.get("shot_list") else content.get("visual_brief")
        content["image_prompt_zh"] = image.get("prompt_zh")
        content["image_prompt_en"] = image.get("prompt_en")
        content["shoot_checklist"] = image.get("checklist") or []
        content["ai_image_plan"] = image
        return {**action, "generated_content": content, "ai_enriched": True, "ai_mode": image.get("mode")}

    decorate = assist_storefront_decorate(
        storefront=storefront,
        store_name=store_name,
        category=category,
    )
    matched = next((s for s in decorate.get("steps") or [] if s.get("action_type") == action_type), None)
    content = dict(action.get("generated_content") or {})
    if matched:
        content["execution_brief"] = matched.get("how")
        content["verify_plan"] = matched.get("verify")
    content["ai_decorate_plan"] = {
        "summary": decorate.get("summary"),
        "copy_pack": decorate.get("copy_pack"),
        "next_action": decorate.get("next_action"),
    }
    return {**action, "generated_content": content, "ai_enriched": True, "ai_mode": decorate.get("mode")}
