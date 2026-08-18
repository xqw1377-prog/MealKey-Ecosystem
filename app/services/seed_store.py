"""种子客户门店测试策略。

1 平台 × 1 授权店 × READ_ONLY × 7 天 × 最小 PII × 禁止写回。
不扩真实 fetch：AuthorizedSessionConnector 保持 UNAVAILABLE。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Store
from app.models.settings import PlatformConnection
from app.schemas.data_acquisition import (
    FACT_KEY_ALIASES,
    POC_MINIMAL_FACT_KEYS,
    Day0Verdict,
    FetchRequest,
    MetricDefinitionVersion,
)
from app.services.authorized_session_connector import AuthorizedSessionConnector

DAY0_READY: Day0Verdict = "DAY0_READY"
DAY0_PASS: Day0Verdict = "DAY0_PASS"
DAY0_PASS_WITH_LIMITS: Day0Verdict = "DAY0_PASS_WITH_LIMITS"
DAY0_BLOCKED: Day0Verdict = "DAY0_BLOCKED"

SEED_MODE = "READ_ONLY"
SEED_DURATION_DAYS = 7
SEED_PII_SCOPE = "MINIMUM"
SEED_WRITEBACK = "DISABLED"
SEED_ALLOWED_FACTS = (
    "order_count",
    "gross_gmv",
    "merchant_revenue",
    "refund_amount",
)
WRITEBACK_DISABLED = "WRITEBACK_DISABLED"
SEED_PLATFORM = "meituan"


class SeedStoreError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
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


def _connection(db: Session, store_id: str, platform: str = SEED_PLATFORM) -> PlatformConnection | None:
    return db.execute(
        select(PlatformConnection).where(
            PlatformConnection.store_id == store_id,
            PlatformConnection.platform == platform,
        )
    ).scalar_one_or_none()


def seed_policy(db: Session, store_id: str) -> dict[str, Any] | None:
    row = _connection(db, store_id)
    if row is None:
        return None
    policy = _loads(row.meta_json).get("seed_store")
    if not isinstance(policy, dict) or not policy.get("enabled"):
        return None
    return policy


def is_seed_store(db: Session, store_id: str) -> bool:
    return seed_policy(db, store_id) is not None


def assert_writeback_allowed(db: Session, store_id: str) -> None:
    """种子店与冻结策略：禁止任何平台写回，包括 human_paste 假装已改。"""
    if is_seed_store(db, store_id):
        raise SeedStoreError(
            WRITEBACK_DISABLED,
            "种子店测试只读，禁止写回平台。Growth Writeback = DISABLED。",
        )


def open_seed_store(
    db: Session,
    store: Store,
    *,
    authorizer: str,
    authorization_note: str = "",
    duration_days: int = SEED_DURATION_DAYS,
    session_handle_ref: str = "",
) -> dict[str, Any]:
    """把已有门店登记为种子测试店。不连 Mock，不写回，不伪造采集。"""
    name = str(authorizer or "").strip()
    if not name:
        raise SeedStoreError("AUTHORIZATION_REQUIRED", "必须记录店主/经营主体的明确授权人。")
    if any(token in name.lower() for token in ("password", "cookie", "token", "secret")):
        raise SeedStoreError("PII_DENIED", "授权记录不得包含密码或明文凭据。")
    if session_handle_ref and any(
        token in session_handle_ref.lower() for token in ("password", "cookie", " ", "=")
    ):
        raise SeedStoreError("PII_DENIED", "session_handle_ref 只能是凭据库句柄，不能是明文。")

    platform = (store.platform or SEED_PLATFORM).strip().lower() or SEED_PLATFORM
    if platform != SEED_PLATFORM:
        raise SeedStoreError("PLATFORM_LOCKED", "种子店测试只开放美团一家授权店。")
    store.platform = SEED_PLATFORM

    now = _utcnow()
    expires = now + timedelta(days=max(1, int(duration_days or SEED_DURATION_DAYS)))
    policy = {
        "enabled": True,
        "mode": SEED_MODE,
        "duration_days": SEED_DURATION_DAYS,
        "pii_scope": SEED_PII_SCOPE,
        "writeback": SEED_WRITEBACK,
        "allowed_facts": list(SEED_ALLOWED_FACTS),
        "authorization_id": f"auth-{uuid.uuid4().hex[:12]}",
        "authorizer": name,
        "authorization_note": str(authorization_note or "").strip(),
        "authorized_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "session_handle_ref": str(session_handle_ref or "").strip(),
    }

    row = _connection(db, store.id, SEED_PLATFORM)
    if row is None:
        row = PlatformConnection(
            store_id=store.id,
            platform=SEED_PLATFORM,
            status="seed_ready",
            connector_mode="human_paste",
            external_store_id=store.platform_store_key,
        )
        db.add(row)
    row.connector_mode = "human_paste"
    row.status = "seed_ready"
    row.last_error = None
    meta = _loads(row.meta_json)
    meta["seed_store"] = policy
    meta["synthetic"] = False
    row.meta_json = json.dumps(meta, ensure_ascii=False)
    db.add(row)
    db.add(store)
    db.flush()
    return seed_store_readiness(db, store.id)


def _gate_authority() -> dict[str, Any]:
    from app.core.security import AuthPrincipal

    empty = AuthPrincipal(
        subject="seed-check",
        role="operator",
        tenant_id="t",
        store_ids=(),
        auth_mode="jwt",
    )
    denied = empty.can_access_store("any-store") is False
    return {
        "status": "PASS" if denied else "FAIL",
        "empty_operator_denied": denied,
    }


def _gate_execution() -> dict[str, Any]:
    import inspect

    from app.services.action_pipeline import commit_recommendation_executed

    params = inspect.signature(commit_recommendation_executed).parameters
    verified = "verified" in params
    return {
        "status": "PASS" if verified else "FAIL",
        "verified_required": verified,
        "choke_point": "commit_recommendation_executed",
    }


def _gate_truth(db: Session, store_id: str) -> dict[str, Any]:
    from app.services.truth_resolution import is_production_truth_source

    hidden = (
        is_production_truth_source(None) is False
        and is_production_truth_source("") is False
        and is_production_truth_source("synthetic") is False
        and is_production_truth_source("mock") is False
    )
    rows = list(db.execute(select(PlatformConnection).where(PlatformConnection.store_id == store_id)).scalars())
    mock_links = [
        row.id
        for row in rows
        if str(row.connector_mode or "").strip().lower() in {"mock", "fixture", "sandbox"}
        and str(row.status or "") != "disabled"
    ]
    return {
        "status": "PASS" if hidden and not mock_links else "FAIL",
        "unprovenanced_invisible": hidden,
        "active_mock_connectors": mock_links,
    }


def _official_fact_value(row: dict[str, Any], fact_key: str) -> Any:
    for alias in FACT_KEY_ALIASES.get(fact_key, (fact_key,)):
        if row.get(alias) is not None and str(row.get(alias)).strip() != "":
            return row.get(alias)
    return "UNKNOWN"


def official_facts_from_rows(rows: list[dict[str, Any]], *, report_date: str | None = None) -> dict[str, Any]:
    chosen: dict[str, Any] = {}
    if report_date:
        chosen = next((row for row in rows if str(row.get("day") or "")[:10] == str(report_date)[:10]), {})
    if not chosen and rows:
        chosen = rows[0]
    return {key: _official_fact_value(chosen, key) for key in POC_MINIMAL_FACT_KEYS}


def normalize_metric_definitions(raw: list[dict[str, Any]] | None) -> dict[str, Any]:
    by_metric: dict[str, Any] = {key: "UNKNOWN" for key in POC_MINIMAL_FACT_KEYS}
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").strip()
        if metric not in POC_MINIMAL_FACT_KEYS:
            continue
        version = str(item.get("definition_version") or item.get("version") or "").strip()
        time_basis = str(item.get("time_basis") or "").strip()
        if not version and not time_basis:
            by_metric[metric] = "UNKNOWN"
            continue
        by_metric[metric] = MetricDefinitionVersion(
            metric=metric,  # type: ignore[arg-type]
            definition_version=version or "v1",
            time_basis=time_basis or "UNKNOWN",
            included_statuses=list(item.get("included_statuses") or []),
            excluded_statuses=list(item.get("excluded_statuses") or []),
            refund_policy=list(item.get("refund_policy") or []),
            fee_policy=list(item.get("fee_policy") or []),
        ).model_dump()
    return by_metric


def classify_day0(
    *,
    policy: dict[str, Any] | None,
    facts: dict[str, Any],
    definitions: dict[str, Any],
    report_date: str | None,
    official_rows: list[dict[str, Any]] | None = None,
) -> Day0Verdict:
    if policy is None or not str(policy.get("authorizer") or "").strip():
        return DAY0_BLOCKED
    if not official_rows and not report_date:
        return DAY0_READY
    if not report_date:
        return DAY0_BLOCKED
    known = [key for key, value in facts.items() if value != "UNKNOWN"]
    defined = [key for key, value in definitions.items() if value != "UNKNOWN"]
    if len(known) == 4 and len(defined) == 4:
        return DAY0_PASS
    if known:
        return DAY0_PASS_WITH_LIMITS
    return DAY0_BLOCKED


def build_day0_audit(
    *,
    store_id: str,
    platform: str,
    policy: dict[str, Any] | None,
    official_rows: list[dict[str, Any]],
    report_date: str | None = None,
    raw_report_ref: str | None = None,
    metric_definitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    day = str(report_date or "").strip() or (str((official_rows[0] or {}).get("day") or "")[:10] if official_rows else "")
    facts = official_facts_from_rows(official_rows, report_date=day or None)
    definitions = normalize_metric_definitions(metric_definitions)
    payload = json.dumps(official_rows, ensure_ascii=False, sort_keys=True, default=str)
    raw_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest() if official_rows else None
    verdict = classify_day0(
        policy=policy,
        facts=facts,
        definitions=definitions,
        report_date=day or None,
        official_rows=official_rows,
    )
    unknown = [key for key, value in facts.items() if value == "UNKNOWN"]
    unknown.extend(f"definition:{key}" for key, value in definitions.items() if value == "UNKNOWN")
    return {
        "store_id": store_id,
        "authorization": {
            "authorization_id": (policy or {}).get("authorization_id"),
            "authorizer": (policy or {}).get("authorizer"),
            "mode": (policy or {}).get("mode"),
            "writeback": (policy or {}).get("writeback"),
            "expires_at": (policy or {}).get("expires_at"),
        },
        "platform": platform,
        "report_date": day or None,
        "raw_report_ref": str(raw_report_ref or "").strip() or None,
        "raw_report_hash": raw_hash,
        "order_count": facts["order_count"],
        "gross_gmv": facts["gross_gmv"],
        "merchant_revenue": facts["merchant_revenue"],
        "refund_amount": facts["refund_amount"],
        "MetricDefinitionVersion": definitions,
        "reconciliation_status": "UNCHECKED",
        "day0_verdict": verdict,
        "unknown_fields": unknown,
        "entered_storestate": False,
    }


def seed_store_readiness(db: Session, store_id: str) -> dict[str, Any]:
    store = db.execute(select(Store).where(Store.id == store_id)).scalar_one_or_none()
    if store is None:
        raise SeedStoreError("STORE_NOT_FOUND", "store not found")

    policy = seed_policy(db, store_id)
    authority = _gate_authority()
    execution = _gate_execution()
    truth = _gate_truth(db, store_id)
    fetch = AuthorizedSessionConnector().fetch(FetchRequest(store_id=store_id, platform=SEED_PLATFORM))
    from app.models.data_acquisition import CollectorRunRecord, ReconciliationRecord
    from app.models.entities import ShopFunnelDaily

    day0_runs = list(
        db.execute(
            select(CollectorRunRecord)
            .where(CollectorRunRecord.store_id == store_id)
            .order_by(CollectorRunRecord.started_at.desc())
        ).scalars()
    )
    day0_audit = None
    for run in day0_runs:
        notes = _loads(run.notes)
        if notes.get("day0_verdict"):
            day0_audit = notes
            break
    day0_verdict: Day0Verdict = (
        day0_audit.get("day0_verdict")
        if day0_audit
        else (DAY0_READY if policy else DAY0_BLOCKED)
    )
    recon_rows = list(
        db.execute(select(ReconciliationRecord).where(ReconciliationRecord.store_id == store_id)).scalars()
    )
    production_facts = list(
        db.execute(
            select(ShopFunnelDaily).where(
                ShopFunnelDaily.store_id == store_id,
                ShopFunnelDaily.data_source.isnot(None),
                ShopFunnelDaily.data_source != "",
            )
        ).scalars()
    )
    gates_pass = (
        authority["status"] == "PASS"
        and execution["status"] == "PASS"
        and truth["status"] == "PASS"
        and policy is not None
        and not truth["active_mock_connectors"]
    )
    return {
        "store_id": store.id,
        "store_name": store.name,
        "platform": store.platform or SEED_PLATFORM,
        "seed_store": bool(policy),
        "constraints": policy
        or {
            "mode": SEED_MODE,
            "duration_days": SEED_DURATION_DAYS,
            "pii_scope": SEED_PII_SCOPE,
            "writeback": SEED_WRITEBACK,
            "allowed_facts": list(SEED_ALLOWED_FACTS),
            "enabled": False,
        },
        "authority": authority,
        "execution": execution,
        "truth": truth,
        "data_as_01": {
            "status": "READY_FOR_DAY0" if gates_pass else "BLOCKED",
            "connector": fetch.health.status,
            "real_fetch": False,
            "envelopes": len(fetch.envelopes),
            "day0_runs": len(day0_runs),
            "reconciliation_rows": len(recon_rows),
            "production_funnel_rows": len(production_facts),
        },
        "day0_verdict": day0_verdict,
        "day0_audit": day0_audit,
        "writeback": SEED_WRITEBACK,
        "can_start_day0": gates_pass and day0_verdict == DAY0_READY,
        "can_promote_truth": False,
        "blocked_external": fetch.health.status == "UNAVAILABLE",
        "next": (
            "店已到位后只做这一家店的授权 Session 接线，不要重开通用 Connector。"
            if day0_verdict in {DAY0_PASS, DAY0_PASS_WITH_LIMITS}
            else "上传官方报表，记录四指标口径。缺的标 UNKNOWN，不要补。"
            if gates_pass
            else "先登记种子店授权，并确认 READ_ONLY / NO MOCK / NO WRITEBACK。"
        ),
    }
