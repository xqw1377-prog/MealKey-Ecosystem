"""Action Registry + ActionSpec builder for Closed Loop V1."""

from __future__ import annotations

from typing import Any

from app.services.copy_humanize import humanize_operator_text


ACTION_REGISTRY: dict[str, dict[str, Any]] = {
    "change_main_image": {
        "action_type": "CHANGE_PRODUCT_IMAGE",
        "subject_type": "sku",
        "risk_level": "LOW",
        "requires_approval": True,
        "execution_method": "human_execute",
        "rollback_method": "restore_previous_image",
        "success_metric": "ctr",
        "default_observation_window": 48,
        "required_context": ["product_name", "image_asset"],
        "input_schema": ["object_name", "copy_text", "steps"],
    },
    "change_title": {
        "action_type": "CHANGE_PRODUCT_TITLE",
        "subject_type": "sku",
        "risk_level": "LOW",
        "requires_approval": True,
        "execution_method": "platform_or_human",
        "rollback_method": "restore_previous_title",
        "success_metric": "ctr",
        "default_observation_window": 48,
        "required_context": ["product_name"],
        "input_schema": ["object_name", "suggested_title", "copy_text"],
    },
    "batch_reply_negative_reviews": {
        "action_type": "REPLY_REVIEW",
        "subject_type": "review_batch",
        "risk_level": "MEDIUM",
        "requires_approval": True,
        "execution_method": "human_execute",
        "rollback_method": "manual_follow_up",
        "success_metric": "rating",
        "default_observation_window": 48,
        "required_context": ["review_theme", "reply_copy"],
        "input_schema": ["copy_text", "steps"],
    },
    "reply_ordinary_reviews": {
        "action_type": "REPLY_REVIEW",
        "subject_type": "review",
        "risk_level": "LOW",
        "requires_approval": True,
        "execution_method": "platform_or_human",
        "rollback_method": "manual_follow_up",
        "success_metric": "review_backlog",
        "default_observation_window": 48,
        "required_context": ["reply_copy"],
        "input_schema": ["reply_text", "copy_text", "steps"],
    },
    "appeal_pack": {
        "action_type": "SUBMIT_REVIEW_APPEAL",
        "subject_type": "review_appeal",
        "risk_level": "LOW",
        "requires_approval": True,
        "execution_method": "platform_or_human",
        "rollback_method": "manual_follow_up",
        "success_metric": "appeal_submitted",
        "default_observation_window": 48,
        "required_context": ["appeal_reason", "evidence_bundle"],
        "input_schema": ["appeal_template", "evidence_needed", "copy_text", "steps"],
    },
    "ops_hint": {
        "action_type": "OPS_HINT",
        "subject_type": "store",
        "risk_level": "LOW",
        "requires_approval": True,
        "execution_method": "human_execute",
        "rollback_method": "manual_follow_up",
        "success_metric": "ops_outcome",
        "default_observation_window": 48,
        "required_context": ["title"],
        "input_schema": ["copy_text", "steps"],
    },
}


def get_action_definition(action_type: str) -> dict[str, Any]:
    kind = str(action_type or "").strip()
    return ACTION_REGISTRY.get(kind, ACTION_REGISTRY["ops_hint"])


def build_action_spec(
    action_type: str,
    *,
    object_name: str = "",
    title: str = "",
    pack: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    definition = get_action_definition(action_type)
    payload = pack if isinstance(pack, dict) else {}
    subject_name = humanize_operator_text(object_name or payload.get("object_name") or title or "当前对象")
    success_label = humanize_operator_text(payload.get("success_metric") or "点击率")
    target = str(payload.get("success_target") or "").strip()
    execution_package = {
        "brief": humanize_operator_text(payload.get("current_problem") or payload.get("goal") or ""),
        "copy_text": humanize_operator_text(payload.get("copy_text") or ""),
        "instructions": [humanize_operator_text(step) for step in (payload.get("steps") or []) if step],
        "how_to_use": humanize_operator_text(payload.get("how_to_use") or ""),
        "watch": humanize_operator_text(payload.get("watch") or ""),
    }
    return {
        "version": "clv1",
        "registry_key": str(action_type or "").strip() or "ops_hint",
        "type": definition["action_type"],
        "title": humanize_operator_text(payload.get("title") or title or subject_name),
        "subject": {
            "type": definition["subject_type"],
            "name": subject_name,
        },
        "reason": humanize_operator_text(reason or payload.get("current_problem") or payload.get("goal") or ""),
        "execution_package": execution_package,
        "risk_level": definition["risk_level"],
        "requires_approval": bool(definition["requires_approval"]),
        "execution_method": definition["execution_method"],
        "rollback_method": definition["rollback_method"],
        "required_context": list(definition["required_context"]),
        "input_schema": list(definition["input_schema"]),
        "success_metric": {
            "metric": definition["success_metric"],
            "label": success_label,
            "target": target,
        },
        "guardrails": {
            "text": humanize_operator_text(payload.get("guardrail") or "不要叠改其他变量"),
        },
        "observation_window_hours": int(
            payload.get("observe_hours") or definition["default_observation_window"] or 48
        ),
        "executor_modes": ["human", "platform"]
        if definition["execution_method"] == "platform_or_human"
        else ["human"],
    }
