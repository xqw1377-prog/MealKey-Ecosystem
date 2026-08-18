"""Execution choke point.

Recommendation → ActionSpec → PREPARE → VALIDATE → CAPABILITY CHECK
→ AUTHORIZE → EXECUTE → VERIFY → COMMIT

只有 COMMIT 可以把 Recommendation 写成 executed。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ohre import Recommendation
from app.services.action_capability import ActionCapabilityError, assert_action_executable
from app.services.action_registry import build_action_spec

BLOCKED_NOT_IMPLEMENTED = "BLOCKED_NOT_IMPLEMENTED"
NEED_APPROVAL = "NEED_APPROVAL"
PLATFORM_UNAVAILABLE = "PLATFORM_UNAVAILABLE"
AWAITING_PLATFORM = "AWAITING_PLATFORM"
EXECUTE_NOT_APPLIED = "EXECUTE_NOT_APPLIED"
PIPELINE_COMMIT_BY = "action_pipeline"


class ActionPipelineError(Exception):
    def __init__(self, code: str, message: str, stage: str, payload: dict[str, Any] | None = None):
        self.code = code
        self.stage = stage
        self.payload = payload or {}
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def commit_recommendation_executed(
    rec: Recommendation,
    *,
    now: datetime | None = None,
    domain: dict[str, Any] | None = None,
    actor: str = "pipeline",
) -> Recommendation:
    """唯一允许把 Recommendation 写成 executed 的函数。"""
    stamp = now or _utcnow()
    if rec.status != "executed":
        rec.status = "executed"
    rec.executed_at = rec.executed_at or stamp
    rec.adopted_at = rec.adopted_at or stamp
    content = _loads(rec.content_json)
    content["execution_commit"] = {
        "by": PIPELINE_COMMIT_BY,
        "actor": actor,
        "at": stamp.isoformat(),
        "domain": domain or {},
    }
    rec.content_json = json.dumps(content, ensure_ascii=False)
    return rec


def _platform_unavailable(store_id: str | None) -> bool:
    if settings.is_dev:
        return False
    connector = str(settings.platform_connector_url or "").strip()
    return not connector


def run_recommendation_pipeline(
    db: Session,
    rec: Recommendation,
    *,
    actor: str = "owner",
    approved: bool = False,
) -> dict[str, Any]:
    stages: list[str] = []

    stages.append("PREPARE")
    action_type = rec.action_type or "ops_hint"
    spec = build_action_spec(action_type, title=rec.object_ref or "", reason="")

    stages.append("VALIDATE")
    if not str(action_type).strip():
        raise ActionPipelineError("INVALID_ACTION", "缺少 action_type，不能进入执行。", "VALIDATE")

    stages.append("CAPABILITY CHECK")
    try:
        assert_action_executable(action_type)
    except ActionCapabilityError as exc:
        raise ActionPipelineError(
            exc.code,
            f"{action_type} 不能执行：{exc.code}",
            "CAPABILITY CHECK",
            {"action_type": action_type, "capability": exc.capability},
        ) from exc

    stages.append("AUTHORIZE")
    if spec.get("requires_approval") and not approved:
        raise ActionPipelineError(
            NEED_APPROVAL,
            "这条动作需要审批后才能进入执行。",
            "AUTHORIZE",
            {"action_type": action_type},
        )

    stages.append("EXECUTE")
    from app.services.recommendation_executor import execute_recommendation_domain

    domain = execute_recommendation_domain(db, rec)

    stages.append("VERIFY")
    mode = str(domain.get("mode") or "")
    if mode == "awaiting_platform":
        code = PLATFORM_UNAVAILABLE if _platform_unavailable(rec.store_id) else AWAITING_PLATFORM
        raise ActionPipelineError(
            code,
            domain.get("detail") or "平台侧尚未确认，不能记为已执行。",
            "VERIFY",
            {"domain": domain},
        )
    if not domain.get("applied"):
        raise ActionPipelineError(
            EXECUTE_NOT_APPLIED,
            domain.get("detail") or domain.get("reason") or "执行未落地，不能记为已执行。",
            "VERIFY",
            {"domain": domain},
        )

    stages.append("COMMIT")
    commit_recommendation_executed(rec, domain=domain, actor=actor)
    return {
        "ok": True,
        "executed": True,
        "code": "COMMITTED",
        "status": rec.status,
        "action_type": action_type,
        "execution_capability": spec.get("execution_capability"),
        "domain_execution": domain,
        "stages": stages,
        "spec": {"type": spec.get("type"), "execution_method": spec.get("execution_method")},
    }
