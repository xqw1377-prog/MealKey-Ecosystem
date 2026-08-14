"""动作执行器：稿 / 确认 / 写回 三档。

- draft：生成可落地文案或方案，不改平台
- confirm：写入 Recommendation，进入「现在需要你」
- writeback：低风险动作生成可直接使用的稿（回复/标题），标记可自动用
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.ohre import Recommendation
from app.services.intent_compiler import CompiledIntent, _LOW_RISK_WRITEBACK, _SPEND_ACTIONS
from app.services.mos_engine import is_action_allowed_in_safe_mode
from app.services.strategy_memory import load_strategy_memory


def memory_veto_reason(db: Session, store_id: str, action_type: str) -> str | None:
    snapshot = load_strategy_memory(db, store_id, limit=20)
    for item in snapshot.items:
        if item.action_type == action_type and item.result == "negative":
            return item.avoid_when or item.lesson or "上次同类动作效果为负，先不重复。"
    return None


def resolve_execution_tier(compiled: CompiledIntent, *, system_mode: str, low_risk_ok: bool | None) -> str:
    action_type = compiled.action_type
    if action_type in _SPEND_ACTIONS:
        return "confirm"
    if system_mode == "safe" and not is_action_allowed_in_safe_mode(action_type):
        return "confirm"
    if action_type in _LOW_RISK_WRITEBACK and low_risk_ok:
        return "writeback"
    if compiled.execution_tier == "draft":
        return "draft"
    return compiled.execution_tier or "confirm"


def build_action_draft(compiled: CompiledIntent) -> str:
    name = compiled.object_name or "当前对象"
    if compiled.action_type == "change_main_image":
        return (
            f"{name}主图方案：用实拍餐品、浅色背景、价格锚点放右下；"
            "避免文字堆叠。先出 1 张对比图给老板确认后再换。"
        )
    if compiled.action_type == "change_title":
        return f"{name}标题稿：保留品类词 + 一份量/口感卖点，控制在 20 字内，避免极限词。"
    if compiled.action_type == "batch_reply_negative_reviews":
        return (
            "差评回复稿：先致歉、复述问题、给具体补偿或改进，不辩解。"
            "份量/口味类用「已反馈后厨并加一份」模板。"
        )
    if compiled.action_type == "reply_ordinary_reviews":
        return "普通好评回复稿：感谢认可，保持口味和出餐速度，不套用差评致歉模板。"
    if compiled.action_type == "add_set_meal":
        return f"套餐方案：以{name}做主菜，配一饮品或小食，价位锚定竞品低 1–2 元。"
    if compiled.action_type == "boost_hero_item_ads":
        budget = compiled.budget
        budget_txt = f"¥{budget:g}" if budget is not None else "先确认预算"
        return f"投流方案：{budget_txt}，时段对准午高峰，主投{name}，观察点击率/转化率 48 小时。"
    return compiled.detail or compiled.raw_text


def execute_compiled_action(
    db: Session,
    store_id: str,
    compiled: CompiledIntent,
    *,
    system_mode: str = "operating",
    low_risk_ok: bool | None = None,
) -> dict[str, Any]:
    """把编译好的动作落到三档执行。"""
    veto = memory_veto_reason(db, store_id, compiled.action_type)
    if veto and compiled.action_type in _SPEND_ACTIONS:
        return {
            "conclusion": "这个动作上次效果不好，我先不重复做。",
            "actions": [veto, "如果仍要做，请明确说「仍然要做」"],
            "expected": "避免重复踩坑",
            "confidence": "high",
            "answer": f"这个动作我记得上次效果不好。{veto}\n如果你仍然要做，请再说一次并带上预算。",
            "intent": "memory_veto",
            "mode": "action_executor",
            "question": compiled.raw_text,
            "decision": compiled.to_decision(),
        }

    if compiled.missing_slots or compiled.should_ask and not compiled.ready:
        questions = [s["question"] for s in compiled.missing_slots] or [compiled.ask_question]
        msg = "在动手之前我需要确认：" + " ".join(questions)
        return {
            "conclusion": msg,
            "actions": questions,
            "answer": msg,
            "intent": "clarification",
            "mode": "action_executor",
            "question": compiled.raw_text,
            "clarification": {"missing_slots": compiled.missing_slots, "message": msg},
            "decision": compiled.to_decision(),
        }

    tier = resolve_execution_tier(compiled, system_mode=system_mode, low_risk_ok=low_risk_ok)
    draft = build_action_draft(compiled)
    pack = None
    try:
        from app.services.execution_pack import build_execution_pack

        pack = build_execution_pack(
            compiled.action_type,
            object_name=compiled.object_name or "",
            title=compiled.object_name or compiled.raw_text,
        )
        if pack and pack.get("copy_text"):
            draft = pack["copy_text"]
    except Exception:  # noqa: BLE001
        pack = None
    rec = Recommendation(
        store_id=store_id,
        scope="store",
        object_ref=f"store:{store_id}",
        action_type=compiled.action_type or "custom",
        expected_metric=compiled.metric or "orders",
        window_hours=48,
        confidence=0.78,
        status="proposed",
        content_json=json.dumps(
            {
                "source": "intent_compiler",
                "title": compiled.object_name,
                "detail": draft,
                "object_name": compiled.object_name,
                "execution_tier": tier,
                "budget": compiled.budget,
                "raw_text": compiled.raw_text,
                "execution_pack": pack,
            },
            ensure_ascii=False,
        ),
    )
    db.add(rec)
    db.flush()

    # 绑定 work_thread_id
    from app.services.thread_engine import ensure_thread_for_action
    thread = ensure_thread_for_action(db, store_id, compiled.object_name or "经营优化")
    rec.work_thread_id = thread.id
    db.commit()
    db.refresh(rec)

    if tier == "draft":
        conclusion = f"我先把「{compiled.object_name}」的方案写好了，你看过再说换不换。"
        expected = "确认后我按这个稿执行"
    elif tier == "writeback":
        conclusion = f"「{compiled.object_name}」稿已备好，低风险可直接用。"
        expected = "你点用，或授权后我自动套用"
    else:
        conclusion = f"已准备「{compiled.object_name}」，放在现在需要你，确认后执行。"
        expected = "确认后进入 48 小时观察窗"

    decision = compiled.to_decision()
    decision["execution_tier"] = tier
    decision["action"] = draft
    decision["recommendation_id"] = rec.id
    if pack:
        decision["execution_pack"] = pack
    return {
        "conclusion": conclusion,
        "actions": [draft],
        "expected": expected,
        "confidence": "high",
        "answer": f"{conclusion}\n\n{draft}",
        "intent": "action",
        "mode": "action_executor",
        "question": compiled.raw_text,
        "recommendation_id": rec.id,
        "execution_pack": pack,
        "decision": decision,
    }
