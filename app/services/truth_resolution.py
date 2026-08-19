"""Truth Resolution V1 — 多个 Evidence，只有一个可进入生产 State。

No Provenance = No Truth。
禁止把空 data_source 猜成 platform / platform_export。
"""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import and_

NEVER_PRODUCTION_TRUTH = frozenset(
    {
        "synthetic",
        "mock",
        "fixture",
        "sandbox",
        "legacy_unknown_source",
        "invalid_reconciliation",
        "test_only",
        "external_daily_report_test",
    }
)
LEGACY_UNKNOWN_SOURCE = "legacy_unknown_source"

SOURCE_PRIORITY: dict[str, int] = {
    "official_api": 90,
    "official_api_reconciled": 90,
    "service_provider_api": 85,
    "authorized_session": 80,
    "platform_sync": 50,
    "file_import": 40,
    "platform_export": 40,
    "screenshot": 30,
    "merchant_confirmation": 20,
    "legacy_unknown_source": 0,
    "synthetic": 0,
    "mock": 0,
    "fixture": 0,
    "sandbox": 0,
    "invalid_reconciliation": 0,
    "test_only": 0,
    "external_daily_report_test": 0,
}

SOURCE_CONFIDENCE: dict[str, float] = {
    "official_api": 0.90,
    "official_api_reconciled": 0.90,
    "service_provider_api": 0.85,
    "authorized_session": 0.70,
    "platform_sync": 0.65,
    "file_import": 0.55,
    "platform_export": 0.55,
    "screenshot": 0.40,
    "merchant_confirmation": 0.35,
    "legacy_unknown_source": 0.0,
    "synthetic": 0.0,
    "mock": 0.0,
    "fixture": 0.0,
    "sandbox": 0.0,
    "invalid_reconciliation": 0.0,
    "test_only": 0.0,
    "external_daily_report_test": 0.0,
}


def normalize_source(raw: Optional[str]) -> str:
    key = str(raw or "").strip().lower()
    aliases = {
        "authorized_session": "authorized_session",
        "official_api": "official_api",
        "service_provider_api": "service_provider_api",
        "platform_sync": "platform_sync",
        "platform_export": "platform_export",
        "file_import": "file_import",
        "screenshot": "screenshot",
        "merchant_confirmation": "merchant_confirmation",
        "legacy_unknown_source": LEGACY_UNKNOWN_SOURCE,
        "synthetic": "synthetic",
        "mock": "mock",
        "fixture": "fixture",
        "sandbox": "sandbox",
        "invalid_reconciliation": "invalid_reconciliation",
        "test_only": "test_only",
        "external_daily_report_test": "external_daily_report_test",
    }
    if not key:
        return LEGACY_UNKNOWN_SOURCE
    return aliases.get(key, key)


def is_production_truth_source(raw: Optional[str]) -> bool:
    return normalize_source(raw) not in NEVER_PRODUCTION_TRUTH


def excluded_from_production_truth(raw: Optional[str]) -> bool:
    return not is_production_truth_source(raw)


def source_priority(raw: Optional[str]) -> int:
    return SOURCE_PRIORITY.get(normalize_source(raw), 10)


def may_write_funnel_truth(existing_source: Optional[str], incoming_source: Optional[str]) -> bool:
    """同日同店：低优先级 / synthetic / 无来源 不得覆盖更高优先级的生产事实。"""
    incoming = normalize_source(incoming_source)
    if existing_source is None or str(existing_source).strip() == "":
        return True
    existing = normalize_source(existing_source)
    if incoming in NEVER_PRODUCTION_TRUTH and existing not in NEVER_PRODUCTION_TRUTH:
        return False
    return source_priority(incoming) >= source_priority(existing)


def confidence_for_sources(sources: Iterable[Optional[str]]) -> float:
    production = [normalize_source(s) for s in sources if is_production_truth_source(s)]
    if not production:
        return 0.0
    return min(SOURCE_CONFIDENCE.get(s, 0.50) for s in production)


def production_funnel_clause(column):
    """SQLAlchemy：NULL / 空串 / unknown / synthetic 一律排除出生产 Truth。"""
    return and_(
        column.isnot(None),
        column != "",
        ~column.in_(tuple(NEVER_PRODUCTION_TRUTH)),
    )
