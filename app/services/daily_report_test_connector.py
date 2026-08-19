"""TEST-ADAPTER-01 — DEV/TEST daily-report fixture.

Not DATA-AS-01. Not a production Connector. Never promotable to Production Truth.
Never wire this into AuthorizedSessionConnector. Never name it MeituanConnector.

Path: fetch_records → normalize → Partial PlatformSnapshot / Facts
      → StoreState(test) → POIE → ODO

Canonical MealKey facts stay UNKNOWN / UNAVAILABLE. Ratio-only source fields
must not be reverse-engineered into impressions / visits / orders / gmv.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.core.config import settings
from app.schemas.store_state import (
    CustomerState,
    DataCoverage,
    DeltaMetric,
    FeedbackInfo,
    MarketInfo,
    ProfitState,
    StoreInfo,
    StoreState,
    WindowInfo,
)
from app.services.action_capability import BLOCKED_NOT_IMPLEMENTED, blocked_payload
from app.services.connector_mode import (
    CONFIGURATION_ERROR,
    ConnectorModeError,
    TEST_ONLY_MODES,
    allows_mock,
    assert_mode_allowed,
)
from app.services.platform_connectors import PlatformSnapshot
from app.services.sensing import build_business_state, build_platform_health_state
from app.services.truth_resolution import (
    NEVER_PRODUCTION_TRUTH,
    excluded_from_production_truth,
    is_production_truth_source,
    normalize_source,
)

ADAPTER_ID = "TEST-ADAPTER-01"
CONNECTOR_KEY = "daily_report_test"
SOURCE_CONNECTOR = "daily_report_test"
SOURCE_NAME = "external_daily_report_test"
PROVENANCE = "TEST_ONLY"
ENVIRONMENT = "test"
WRITEBACK_DISABLED = "disabled"

UNKNOWN = "UNKNOWN"
UNAVAILABLE = "UNAVAILABLE"

CANONICAL_UNKNOWN_FACTS = ("impressions", "visits", "orders", "gmv")
CANONICAL_UNAVAILABLE_FACTS = ("menu_items", "reviews", "competitors")

# Absolute visits only — never rates, never exposure * entry_rate.
_EXPLICIT_VISITS_KEYS = ("visits", "visit_count", "absolute_visits")
# Source-level extras only. Even if present, canonical orders/gmv stay UNKNOWN.
_EXPLICIT_ORDER_EXTRA_KEYS = ("orders", "order_count", "absolute_orders")
_EXPLICIT_GMV_EXTRA_KEYS = ("gmv", "gross_gmv", "absolute_gmv")

# Rate / score extras that may be retained as non-canonical test inputs.
_EXTRA_KEYS = (
    "entry_rate",
    "visit_rate",
    "order_rate",
    "conversion_rate",
    "avg_order_value",
    "aov",
    "exposure",
    "promotion_fee",
    "store_rating",
    "store_score",
    "region_rank",
    "repurchase_rate",
    "bad_review_count",
    "bad_review_rate",
    "main_issues",
    "record_date",
    "source",
)

HttpGetter = Callable[[str], dict[str, Any]]


class DailyReportTestError(ConnectorModeError):
    """Fail-closed errors for the test-only daily-report adapter."""


def assert_daily_report_test_allowed() -> None:
    """Unauthenticated /api/records is never a legal production datasource."""
    if not allows_mock() or not settings.is_dev:
        raise DailyReportTestError(
            CONFIGURATION_ERROR,
            "生产环境禁止未认证日报测试源（TEST-ADAPTER-01），且绝不能 fallback。",
        )
    if not settings.daily_report_test_enabled:
        raise DailyReportTestError(
            CONFIGURATION_ERROR,
            "TEST-ADAPTER-01 默认关闭。DEV/TEST 须显式设置 DAILY_REPORT_TEST_ENABLED=1。",
        )
    assert_mode_allowed(CONNECTOR_KEY, explicit=True)


def _as_float(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _as_int(raw: Any) -> Optional[int]:
    value = _as_float(raw)
    if value is None:
        return None
    return int(value)


def _as_date(raw: Any) -> Optional[date]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _map_platform(raw: Any) -> str:
    """Never claim official meituan / eleme / authorized session."""
    key = str(raw or "").strip().lower()
    if key in {"meituan_like", "external_test"}:
        return key
    if key == "meituan":
        return "meituan_like"
    return "external_test"


def _unknown_fact() -> dict[str, Any]:
    return {"status": UNKNOWN, "value": None}


def _unavailable_fact() -> dict[str, Any]:
    return {"status": UNAVAILABLE, "value": None}


def _canonical_facts(*, visits_value: Optional[float] = None) -> dict[str, dict[str, Any]]:
    facts = {name: _unknown_fact() for name in CANONICAL_UNKNOWN_FACTS}
    facts.update({name: _unavailable_fact() for name in CANONICAL_UNAVAILABLE_FACTS})
    if visits_value is not None:
        facts["visits"] = {"status": "OBSERVED", "value": visits_value}
    return facts


def _extract_explicit_visits(record: dict[str, Any]) -> Optional[float]:
    for key in _EXPLICIT_VISITS_KEYS:
        if key not in record:
            continue
        value = _as_float(record.get(key))
        if value is not None:
            return value
    return None


def _collect_extras(record: dict[str, Any]) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for key in _EXTRA_KEYS:
        if key in record and record.get(key) is not None:
            extras[key] = record[key]
    for group in (_EXPLICIT_ORDER_EXTRA_KEYS, _EXPLICIT_GMV_EXTRA_KEYS, _EXPLICIT_VISITS_KEYS):
        for key in group:
            if key in record and record.get(key) is not None:
                extras[key] = record[key]
    return extras


@dataclass
class PartialPlatformSnapshot:
    """Partial PlatformSnapshot: hard lock fields + UNKNOWN canonical facts."""

    platform: str = "meituan_like"
    external_store_id: str = ""
    store_name: Optional[str] = None
    source: str = SOURCE_NAME
    environment: str = ENVIRONMENT
    truth_eligible: bool = False
    writeback: str = WRITEBACK_DISABLED
    provenance: str = PROVENANCE
    facts: dict[str, dict[str, Any]] = field(default_factory=_canonical_facts)
    extras: dict[str, Any] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = True

    def fact_status(self, name: str) -> str:
        row = self.facts.get(name) or {}
        return str(row.get("status") or UNKNOWN)

    def fact_value(self, name: str) -> Any:
        row = self.facts.get(name) or {}
        return row.get("value")

    def to_platform_snapshot(self) -> PlatformSnapshot:
        """Empty collections / no invented daily metrics. Incomplete is correct."""
        return PlatformSnapshot(
            platform=self.platform,
            external_store_id=self.external_store_id or "external_test_store",
            store_name=self.store_name,
            menu_items=[],
            daily_metrics=[],
            reviews=[],
            raw=dict(self.raw),
            synthetic=True,
        )


class DailyReportTestConnector:
    """DEV/TEST fixture connector. Not Meituan. Not authorized-session."""

    acquisition_mode = PROVENANCE
    source_connector = SOURCE_CONNECTOR
    source_version = "test-adapter-01"
    connector_key = CONNECTOR_KEY

    def __init__(self, *, http_get: HttpGetter | None = None, base_url: str | None = None):
        self._http_get = http_get
        self._base_url = (base_url if base_url is not None else settings.daily_report_test_base_url).strip()

    def assert_allowed(self) -> None:
        assert_daily_report_test_allowed()

    def capabilities(self, store_id: str, platform: str) -> list[dict[str, Any]]:
        del store_id, platform
        keys = ("ORDERS", "PRODUCT_SALES", "REFUNDS", "FULFILLMENT", "FINANCE", "PRODUCTS", "REVIEWS")
        return [
            {
                "capability": key,
                "status": UNAVAILABLE,
                "notes": "TEST-ADAPTER-01: canonical facts UNKNOWN; not a production capability",
            }
            for key in keys
        ]

    def health_check(self, store_id: str, platform: str) -> dict[str, Any]:
        allowed = False
        detail = "TEST-ADAPTER-01 disabled or forbidden"
        try:
            self.assert_allowed()
            allowed = True
            detail = "TEST-ADAPTER-01 fixture ready (truth_eligible=false, writeback disabled)"
        except ConnectorModeError as exc:
            detail = str(exc)
        return {
            "status": "TEST_ONLY" if allowed else "UNAVAILABLE",
            "platform": _map_platform(platform),
            "store_id": store_id,
            "acquisition_mode": PROVENANCE,
            "source_connector": self.source_connector,
            "truth_eligible": False,
            "writeback": WRITEBACK_DISABLED,
            "provenance": PROVENANCE,
            "environment": ENVIRONMENT,
            "detail": detail,
        }

    def writeback(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        payload = blocked_payload("daily_report_test_writeback", tool=ADAPTER_ID)
        payload.update(
            {
                "writeback": WRITEBACK_DISABLED,
                "truth_eligible": False,
                "provenance": PROVENANCE,
                "code": BLOCKED_NOT_IMPLEMENTED,
                "message": "TEST-ADAPTER-01 writeback is disabled and not implementable.",
            }
        )
        return payload

    def fetch_records(
        self,
        *,
        page_size: int = 20,
        store_id: Optional[str] = None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        self.assert_allowed()
        payload = self._get_payload(page_size=page_size, store_id=store_id, page=page)
        records = payload.get("records")
        if not isinstance(records, list):
            return []
        return [row for row in records if isinstance(row, dict)]

    def normalize(self, records: list[dict[str, Any]] | dict[str, Any] | None) -> PartialPlatformSnapshot:
        """Map source rows to a partial snapshot. Never infer absolutes from rates."""
        rows = _coerce_records(records)
        primary = rows[0] if rows else {}
        visits = _extract_explicit_visits(primary)
        extras = _collect_extras(primary)
        snapshot = PartialPlatformSnapshot(
            platform=_map_platform(primary.get("platform")),
            external_store_id=str(primary.get("store_id") or primary.get("store_code") or "external_test_store"),
            store_name=str(primary.get("store_name") or "") or None,
            facts=_canonical_facts(visits_value=visits),
            extras=extras,
            records=rows,
            raw={
                "source": SOURCE_NAME,
                "environment": ENVIRONMENT,
                "truth_eligible": False,
                "writeback": WRITEBACK_DISABLED,
                "provenance": PROVENANCE,
                "platform": _map_platform(primary.get("platform")),
                "adapter": ADAPTER_ID,
                "record_count": len(rows),
                "extras": extras,
            },
            synthetic=True,
        )
        return snapshot

    def fetch(self, request: Any = None) -> dict[str, Any]:
        """Read path used by the test fixture. Does not emit promotable FactEnvelopes."""
        self.assert_allowed()
        store_id = getattr(request, "store_id", None) if request is not None else None
        records = self.fetch_records(store_id=store_id)
        snapshot = self.normalize(records)
        return {
            "health": self.health_check(str(store_id or ""), getattr(request, "platform", "external_test") if request else "external_test"),
            "snapshot": snapshot,
            "envelopes": [],
            "unavailable_capabilities": [row["capability"] for row in self.capabilities(str(store_id or ""), "external_test")],
            "truth_eligible": False,
            "production_truth": False,
        }

    def project_store_state(
        self,
        snapshot: PartialPlatformSnapshot,
        *,
        store_id: str,
        days: int = 7,
    ) -> StoreState:
        """StoreState(test): consume partial snapshot. UNKNOWN orders/gmv stay None, not 0."""
        unknown = DeltaMetric(
            delta_pct=None,
            confidence=0.0,
            value=None,
            baseline_value=None,
            observed_value=None,
        )
        kpis: dict[str, DeltaMetric] = {
            "gmv": unknown.model_copy(),
            "orders": unknown.model_copy(),
            "impressions": unknown.model_copy(),
            "ctr": unknown.model_copy(),
            "cvr": unknown.model_copy(),
            "aov": unknown.model_copy(),
        }
        rating = _as_float(snapshot.extras.get("store_rating"))
        if rating is not None:
            kpis["rating"] = DeltaMetric(
                delta_pct=None,
                confidence=0.0,
                value=rating,
                baseline_value=None,
                observed_value=rating,
            )
        bad_rate = _as_float(snapshot.extras.get("bad_review_rate"))
        if bad_rate is not None and bad_rate > 1:
            bad_rate = bad_rate / 100.0
        platform_health = build_platform_health_state(
            store_rating=rating,
            mid_bad_review_rate=bad_rate,
            decoration_completeness=None,
            hero_sku_in_stock_rate=None,
            activity_valid=None,
            open_status="unknown",
        )
        business = build_business_state(kpis)
        window = _test_window(days)
        repurchase = _as_float(snapshot.extras.get("repurchase_rate"))
        if repurchase is not None and repurchase > 1:
            repurchase = repurchase / 100.0
        feedback = FeedbackInfo(
            recent_bad_review_count=int(_as_int(snapshot.extras.get("bad_review_count")) or 0),
            bad_review_rate=bad_rate,
        )
        return StoreState(
            store=StoreInfo(
                store_id=store_id,
                name=snapshot.store_name or store_id,
            ),
            market=MarketInfo(),
            window=WindowInfo(
                from_day=window[0],
                to_day=window[1],
                compare_from_day=window[2],
                compare_to_day=window[3],
            ),
            kpis=kpis,
            core_items=[],
            competition_changes=[],
            feedback=feedback,
            business=business,
            platform_health=platform_health,
            profit=ProfitState(data_quality="missing", judgment="TEST-ADAPTER-01: gmv/orders UNKNOWN，利润不可算。"),
            customer=CustomerState(repurchase_rate=repurchase),
            data_coverage=DataCoverage(
                funnel_days=0,
                ads_days=0,
                reviews=0,
                order_rows=0,
                items_with_cost=0,
                synthetic_item_funnel=False,
                ads_source="missing",
                ads_observed=False,
                orders_observed=False,
            ),
            generated_at=datetime.now(timezone.utc),
        )

    def run(
        self,
        *,
        store_id: str,
        records: list[dict[str, Any]] | dict[str, Any] | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        """Full fixture path: records → normalize → StoreState(test) → POIE → ODO."""
        self.assert_allowed()
        rows = _coerce_records(records) if records is not None else self.fetch_records(store_id=store_id)
        snapshot = self.normalize(rows)
        state = self.project_store_state(snapshot, store_id=store_id, days=days)
        from app.services.event_engine import build_operating_events
        from app.services.manager_brief import build_manager_home_brief
        from app.services.operating_demands.runner import facts_from_store_state, run_demand
        from app.services.poie import run_poie

        events = build_operating_events(state)
        brief = build_manager_home_brief(state, events=events, store_id=store_id)
        poie = run_poie(brief, store_id=store_id, events=events)
        odo_facts = facts_from_store_state(state)
        odo = None
        if (state.feedback.recent_bad_review_count or 0) > 0 or state.platform_health.store_rating is not None:
            odo = run_demand("URGENT_REVIEWS", odo_facts).as_dict()
        return {
            "adapter": ADAPTER_ID,
            "source": snapshot.source,
            "environment": snapshot.environment,
            "truth_eligible": False,
            "production_truth": False,
            "writeback": WRITEBACK_DISABLED,
            "provenance": snapshot.provenance,
            "platform": snapshot.platform,
            "snapshot": snapshot,
            "store_state": state,
            "events": events,
            "poie": poie,
            "odo_facts": odo_facts,
            "odo": odo,
        }

    def _get_payload(self, *, page_size: int, store_id: Optional[str], page: int) -> dict[str, Any]:
        if self._http_get is not None:
            url = self._build_url(page_size=page_size, store_id=store_id, page=page)
            payload = self._http_get(url)
            if not isinstance(payload, dict):
                raise DailyReportTestError(CONFIGURATION_ERROR, "测试日报源返回格式无效")
            return payload
        if not self._base_url:
            raise DailyReportTestError(
                CONFIGURATION_ERROR,
                "TEST-ADAPTER-01 已启用但未配置 DAILY_REPORT_TEST_BASE_URL。",
            )
        url = self._build_url(page_size=page_size, store_id=store_id, page=page)
        request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise DailyReportTestError(CONFIGURATION_ERROR, f"测试日报源返回 {exc.code}: {detail[:240]}") from exc
        except urllib.error.URLError as exc:
            raise DailyReportTestError(CONFIGURATION_ERROR, f"无法访问测试日报源：{exc.reason}") from exc
        if not isinstance(payload, dict):
            raise DailyReportTestError(CONFIGURATION_ERROR, "测试日报源返回格式无效")
        return payload

    def _build_url(self, *, page_size: int, store_id: Optional[str], page: int) -> str:
        base = (self._base_url or "http://daily-report-test.local").rstrip("/")
        url = f"{base}/api/records?page={page}&page_size={int(page_size)}"
        if store_id:
            url += f"&store_id={store_id}"
        return url


def _coerce_records(records: list[dict[str, Any]] | dict[str, Any] | None) -> list[dict[str, Any]]:
    if records is None:
        return []
    if isinstance(records, dict):
        inner = records.get("records")
        if isinstance(inner, list):
            return [row for row in inner if isinstance(row, dict)]
        return [records]
    return [row for row in records if isinstance(row, dict)]


def _test_window(days: int) -> tuple[date, date, date, date]:
    span = max(1, int(days))
    today = date.today()
    observe_to = today - timedelta(days=1)
    observe_from = observe_to - timedelta(days=span - 1)
    baseline_to = observe_from - timedelta(days=1)
    baseline_from = baseline_to - timedelta(days=span - 1)
    return observe_from, observe_to, baseline_from, baseline_to


def is_registered_production_connector() -> bool:
    from app.services.platform_connectors import SUPPORTED_PLATFORMS

    keys = {row["key"] for row in SUPPORTED_PLATFORMS}
    return CONNECTOR_KEY in keys or SOURCE_CONNECTOR in keys or SOURCE_NAME in keys


def snapshot_source_is_production_truth(snapshot: PartialPlatformSnapshot) -> bool:
    if snapshot.truth_eligible:
        return False
    return is_production_truth_source(snapshot.source) or is_production_truth_source(snapshot.provenance)


def incoming_funnel_source_for_snapshot(snapshot: PlatformSnapshot) -> str:
    raw = snapshot.raw if isinstance(snapshot.raw, dict) else {}
    raw_source = normalize_source(str(raw.get("source") or "").strip() or None)
    if raw.get("truth_eligible") is False or raw.get("provenance") == PROVENANCE:
        return raw_source if raw_source in NEVER_PRODUCTION_TRUTH else "test_only"
    if snapshot.synthetic or excluded_from_production_truth(raw_source):
        return raw_source if raw_source in NEVER_PRODUCTION_TRUTH else "synthetic"
    return "platform_sync"


__all__ = [
    "ADAPTER_ID",
    "CONNECTOR_KEY",
    "DailyReportTestConnector",
    "DailyReportTestError",
    "ENVIRONMENT",
    "PartialPlatformSnapshot",
    "PROVENANCE",
    "SOURCE_NAME",
    "TEST_ONLY_MODES",
    "UNAVAILABLE",
    "UNKNOWN",
    "assert_daily_report_test_allowed",
    "incoming_funnel_source_for_snapshot",
    "is_registered_production_connector",
    "snapshot_source_is_production_truth",
]
