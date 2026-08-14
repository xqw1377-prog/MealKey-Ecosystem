"""P0 规则源 AUTO-DIFF：只对已启用的 F 级公开页做哈希差异检测。"""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.operating_case import SourceRegistryRecord
from app.services.oci.ingest import sync_source_registry
from app.services.oci.whitelist import rule_sources
from app.services.platform_intel import IntelFetchError, default_fetch

FetchFn = Callable[[str], tuple[int, str, str, str]]


def diff_enabled_rule_sources(db: Session, *, fetch: FetchFn | None = None) -> dict[str, Any]:
    sync_source_registry(db)
    fetch_fn = fetch or default_fetch
    results: list[dict[str, Any]] = []
    for source in rule_sources(enabled_only=True):
        row = db.execute(
            select(SourceRegistryRecord).where(SourceRegistryRecord.source_id == source.source_id)
        ).scalar_one_or_none()
        if row is None or not source.canonical_url:
            results.append({"source_id": source.source_id, "status": "skipped", "reason": "no_url"})
            continue
        try:
            status, _, body, _final = fetch_fn(source.canonical_url)
            if status >= 400:
                raise IntelFetchError(f"HTTP {status}")
            digest = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()
            changed = bool(row.raw_content_hash and row.raw_content_hash != digest)
            row.raw_content_hash = digest
            row.last_checked_at = utc_now()
            row.last_error = None
            if changed:
                version = str(int(row.source_version or "1") + 1)
                row.source_version = version
            results.append(
                {
                    "source_id": source.source_id,
                    "status": "changed" if changed else "unchanged",
                    "source_version": row.source_version,
                }
            )
        except IntelFetchError as exc:
            if row:
                row.last_checked_at = utc_now()
                row.last_error = str(exc)
            results.append({"source_id": source.source_id, "status": "failed", "error": str(exc)})
    db.commit()
    return {
        "checked": len(results),
        "changed": sum(1 for item in results if item.get("status") == "changed"),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "results": results,
    }
