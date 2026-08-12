from __future__ import annotations
from typing import Any
from app.models.ohre import Experiment, Recommendation
from app.schemas.agents import AgentWorkflowItem

from .types import _AgentContext
from .helpers import (
    _json_loads_dict,
    _json_loads_list,
    _normalize_text,
    _recommendation_title,
)

def _workflow_generated_content(rec: Recommendation, object_name: str) -> dict[str, Any]:
    from .menu import _menu_action_observe_focus, _menu_action_review_note
    payload = _json_loads_dict(rec.content_json)
    base = {
        "change_main_image": {
            "visual_brief": f"{object_name} 使用干净近景主图，突出肉量、热气和真实分量，不加营销贴纸。",
            "caption": f"{object_name}｜现炒现出锅，第一眼就让人知道值不值得点",
        },
        "change_title": {
            "title_candidate": f"{object_name}｜现炒热卖·分量更稳",
            "subtitle_candidate": "先把用户点进来，再看是否需要动价格。",
        },
        "add_set_meal": {
            "bundle_name": f"{object_name} 双人套餐",
            "bundle_logic": "主推 SKU + 一份小食/饮品，优先解决犹豫用户的选择障碍。",
        },
        "store_discount": {
            "campaign_name": "午餐时段限时折扣",
            "campaign_note": "只作为最后顺位测试，不建议和低风险动作同时上。",
        },
    }.get(rec.action_type, {})
    if rec.action_type in {"menu_patch", "menu_cleanup", "add_set_meal"}:
        review_note = payload.get("review_note") or _menu_action_review_note(rec.action_type, payload)
        observe_focus = payload.get("observe_focus") or _menu_action_observe_focus(rec.action_type, payload)
        if review_note:
            payload["review_note"] = review_note
        if observe_focus:
            payload["observe_focus"] = observe_focus
    if isinstance(payload.get("feedback_history"), list) and payload["feedback_history"]:
        payload["feedback_count"] = len(payload["feedback_history"])
    return {**base, **payload}

def _workflow_next_decision(rec: Recommendation, experiment: Experiment | None) -> str:
    from .menu import _menu_action_observe_focus
    payload = _json_loads_dict(rec.content_json)
    if rec.status == "proposed":
        return "先确认是否采纳，再进入执行。"
    if rec.status == "adopted":
        return "建议尽快执行，并锁定观察窗。"
    if rec.status == "archived":
        return "本轮已忽略，除非证据变化否则不再优先推进。"
    if experiment is None:
        focus = _menu_action_observe_focus(rec.action_type, payload)
        return focus[0] if focus else "动作已执行，等待生成实验记录。"
    if experiment.result == "positive":
        return "效果为正，可以继续放大或沉淀为标准动作。"
    if experiment.result == "negative":
        return "效果为负，按回滚规则处理。"
    if experiment.result == "neutral":
        return "效果不明显，回到低风险单变量测试。"
    focus = _menu_action_observe_focus(rec.action_type, payload)
    return focus[0] if focus else "继续等待观察窗完成。"

def _workflow_phase(rec: Recommendation, experiment: Experiment | None) -> tuple[str, str]:
    if rec.status == "proposed":
        return "execute_now", "建议先确认采纳并尽快执行。"
    if rec.status == "adopted":
        return "execute_now", "动作已采纳，当前应进入执行。"
    if rec.status == "archived":
        return "archived", "本轮已归档，除非证据变化否则不再推进。"
    if experiment is None:
        return "observe", "动作已执行，当前先等实验记录和观察窗。"
    if experiment.result in {None, "pending"}:
        return "observe", "动作已执行，当前先盯观察指标，不要追加同类动作。"
    if experiment.result == "positive":
        return "review", "效果为正，当前更适合复盘后再决定是否放大。"
    if experiment.result == "negative":
        return "review", "效果为负，当前应先处理回滚或复盘。"
    if experiment.result == "neutral":
        return "review", "效果一般，当前先复盘再决定是否继续。"
    return "observe", "继续等待观察窗完成。"

def _workflow_item(
    rec: Recommendation,
    experiment_map: dict[str, Experiment],
    item_names: dict[str, str],
) -> AgentWorkflowItem:
    payload = _json_loads_dict(rec.content_json)
    if rec.object_ref.startswith("item:"):
        object_name = item_names.get(rec.object_ref.split(":", 1)[1], "当前主推商品")
        menu_patch = payload.get("menu_patch")
        menu_cleanup = payload.get("menu_cleanup")
        if object_name == "当前主推商品" and isinstance(menu_patch, dict) and menu_patch.get("item_name"):
            object_name = str(menu_patch["item_name"])
        if object_name == "当前主推商品" and isinstance(menu_cleanup, dict) and menu_cleanup.get("name"):
            object_name = str(menu_cleanup["name"])
    else:
        object_name = "门店整体"
    experiment = experiment_map.get(rec.id)
    execution_phase, phase_reason = _workflow_phase(rec, experiment)
    return AgentWorkflowItem(
        recommendation_id=rec.id,
        title=_recommendation_title(rec.action_type),
        action_type=rec.action_type,
        object_ref=rec.object_ref,
        object_name=object_name,
        status=rec.status,
        execution_phase=execution_phase,
        phase_reason=phase_reason,
        expected_metric=rec.expected_metric,
        window_hours=rec.window_hours,
        confidence=float(rec.confidence),
        rollback_rule=rec.rollback_rule,
        evidence=_json_loads_list(rec.evidence_json)[:4],
        generated_content=_workflow_generated_content(rec, object_name),
        experiment_id=experiment.id if experiment else None,
        experiment_result=experiment.result if experiment else None,
        experiment_lift_pct=experiment.lift_pct if experiment else None,
        experiment_notes=experiment.notes if experiment else None,
        next_decision=_workflow_next_decision(rec, experiment),
    )

def _experiment_map(ctx: _AgentContext) -> dict[str, Experiment]:
    return {exp.recommendation_id: exp for exp in ctx.experiments}

def _workflow_phase_rank(item: AgentWorkflowItem) -> tuple[int, int, float]:
    phase_rank = {
        "execute_now": 0,
        "review": 1,
        "observe": 2,
        "deferred": 3,
        "archived": 4,
    }.get(item.execution_phase, 2)
    status_rank = {
        "adopted": 0,
        "proposed": 1,
        "executed": 2,
        "archived": 3,
    }.get(item.status, 4)
    return phase_rank, status_rank, -float(item.confidence)

def _workflow_phase_summary(item: AgentWorkflowItem) -> str:
    if item.execution_phase == "execute_now":
        return f"当前主动作是 {item.title}，建议现在执行。"
    if item.execution_phase == "observe":
        return f"当前先观察 {item.object_name}，不要马上叠加第二个同类动作。"
    if item.execution_phase == "review":
        return f"当前先复盘 {item.object_name} 这条动作，再决定是否继续放大。"
    return f"{item.title} 当前已归档，除非证据变化否则不再推进。"

def _current_action(queue: list[AgentWorkflowItem]) -> AgentWorkflowItem | None:
    if not queue:
        return None
    return sorted(queue, key=_workflow_phase_rank)[0]

def _dedupe_workflow_items(queue: list[AgentWorkflowItem]) -> list[AgentWorkflowItem]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[AgentWorkflowItem] = []
    for item in queue:
        key = (
            item.action_type,
            _normalize_text(item.title),
            _normalize_text(item.object_name),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
