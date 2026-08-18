"""Execution choke point.

Recommendation → ActionSpec → PREPARE → VALIDATE → CAPABILITY CHECK
→ AUTHORIZE → EXECUTE → VERIFY → COMMIT

只有 COMMIT 可以把 Recommendation 写成 executed。
HTTP 200 / Tool success / Platform write accepted ≠ EXECUTED。
"""

from __future__ import annotations

import contextvars
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import NEVER_SET, NO_VALUE

from app.core.config import settings
from app.models.ohre import Recommendation
from app.services.action_capability import ActionCapabilityError, assert_action_executable
from app.services.action_registry import build_action_spec

_PIPELINE_COMMIT = contextvars.ContextVar("mealkey_pipeline_commit", default=False)
_LISTENER_INSTALLED = False

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
    verified: bool,
) -> Recommendation:
    """唯一允许把 Recommendation 写成 executed 的函数。未 Verify 不得 Commit。"""
    if not verified:
        raise ActionPipelineError(
            "VERIFY_REQUIRED",
            "Read Back / Verify 通过后才能 Commit。HTTP 200、Tool success、写回受理都不是 Executed。",
            "VERIFY",
        )
    stamp = now or _utcnow()
    token = _PIPELINE_COMMIT.set(True)
    try:
        rec.status = "executed"
    finally:
        _PIPELINE_COMMIT.reset(token)
    rec.executed_at = rec.executed_at or stamp
    rec.adopted_at = rec.adopted_at or stamp
    content = _loads(rec.content_json)
    content["execution_commit"] = {
        "by": PIPELINE_COMMIT_BY,
        "actor": actor,
        "at": stamp.isoformat(),
        "verified": True,
        "domain": domain or {},
    }
    rec.content_json = json.dumps(content, ensure_ascii=False)
    return rec


def _forbid_direct_executed(target: Recommendation, value: Any, oldvalue: Any, _initiator: Any) -> None:
    if str(value or "") != "executed":
        return
    if oldvalue in (NEVER_SET, NO_VALUE):
        return
    if oldvalue == "executed":
        return
    if _PIPELINE_COMMIT.get():
        return
    raise RuntimeError(
        "Execution choke point: only commit_recommendation_executed may transition to executed"
    )


def install_execution_choke_point() -> None:
    global _LISTENER_INSTALLED
    if _LISTENER_INSTALLED:
        return
    event.listen(Recommendation.status, "set", _forbid_direct_executed)
    _LISTENER_INSTALLED = True


install_execution_choke_point()


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
    commit_recommendation_executed(rec, domain=domain, actor=actor, verified=True)
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
