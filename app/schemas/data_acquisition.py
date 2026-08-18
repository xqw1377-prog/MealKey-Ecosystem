"""DATA-AS-01 / Data Acquisition contracts.

Connector 产出 Evidence（FactEnvelope），不直接决定 Business Truth。
AUTHORIZED_SESSION 是 PlatformConnectorContract 下的一种 acquisition_mode，
不是独立 crawler framework。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Acquisition ladder (priority high → low; AUTHORIZED_SESSION never auto-promotes)
# ---------------------------------------------------------------------------

AcquisitionMode = Literal[
    "OFFICIAL_API",
    "SERVICE_PROVIDER_API",
    "AUTHORIZED_SESSION",
    "FILE_IMPORT",
    "SCREENSHOT",
    "MERCHANT_CONFIRMATION",
]

ACQUISITION_LADDER: tuple[AcquisitionMode, ...] = (
    "OFFICIAL_API",
    "SERVICE_PROVIDER_API",
    "AUTHORIZED_SESSION",
    "FILE_IMPORT",
    "SCREENSHOT",
    "MERCHANT_CONFIRMATION",
)

# ---------------------------------------------------------------------------
# Connector capability / health
# ---------------------------------------------------------------------------

ConnectorCapability = Literal[
    "ORDERS",
    "PRODUCT_SALES",
    "REFUNDS",
    "FULFILLMENT",
    "FINANCE",
    "PRODUCTS",
    "CAMPAIGNS",
    "ADS",
    "REVIEWS",
]

CapabilityStatus = Literal["AVAILABLE", "UNAVAILABLE", "DEGRADED"]

ConnectorHealthStatus = Literal[
    "HEALTHY",
    "DEGRADED",
    "AUTH_REQUIRED",
    "RATE_LIMITED",
    "SCHEMA_CHANGED",
    "UNAVAILABLE",
]

ReconciliationStatus = Literal[
    "UNCHECKED",
    "MATCHED",
    "EXPLAINABLE_DIFF",
    "MISMATCH",
    "BLOCKED",
]

FactType = Literal[
    "order",
    "order_line",
    "daily_gmv",
    "daily_merchant_revenue",
    "daily_refund",
    "sku_sales_daily",
    "fulfillment_daily",
    "finance_settlement",
]


class CapabilityDeclaration(BaseModel):
    """平台当前真实具备的能力；不具备则 UNAVAILABLE，绝不伪造。"""

    capability: ConnectorCapability
    status: CapabilityStatus = "UNAVAILABLE"
    notes: str = ""


class ConnectorHealth(BaseModel):
    status: ConnectorHealthStatus
    platform: str
    store_id: str
    acquisition_mode: AcquisitionMode
    checked_at: datetime
    detail: str = ""
    schema_fingerprint: Optional[str] = None
    next_action: Optional[str] = None  # e.g. reauthorize / wait / halt_ingest


class AuthorizationRecord(BaseModel):
    """授权元数据。禁止包含账号密码或明文 Cookie/token。

    session_handle_ref 只指向安全凭据存储中的句柄。
    """

    authorization_id: str
    store_id: str
    platform: str
    session_handle_ref: str
    scope: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Order / sales allowlist (PII default deny)
# ---------------------------------------------------------------------------

# 进入 MealKey 的订单事实默认只允许这些字段；姓名/完整手机/完整地址默认拒绝。
ORDER_FACT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "order_id_hash",
        "ordered_at",
        "sku_id",
        "sku_name",
        "quantity",
        "gross_amount",
        "merchant_discount",
        "platform_discount",
        "merchant_revenue",
        "refund_amount",
        "fulfillment_status",
        "fulfillment_duration",
    }
)


class FactEnvelope(BaseModel):
    """Connector → Normalize 的统一证据信封。

    任意 acquisition_mode（OAuth / Authorized Session / CSV）最终都应产出同类对象，
    再经 Reconciliation 后才能升为高置信 Business Fact 进入 StoreState。
    """

    platform: str
    store_id: str

    fact_type: FactType
    fact_key: str
    occurred_at: datetime

    value: Any = None
    unit: Optional[str] = None

    acquisition_mode: AcquisitionMode
    source_connector: str
    source_version: str = "1"

    collected_at: datetime
    authorization_id: Optional[str] = None

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reconciliation_status: ReconciliationStatus = "UNCHECKED"

    raw_evidence_ref: Optional[str] = None
    raw_evidence_hash: Optional[str] = None
    metric_definition_version: Optional[str] = None

    # allowlisted payload only; never dump full page JSON here
    payload: dict[str, Any] = Field(default_factory=dict)


class ReconciliationRow(BaseModel):
    """日度 Collector vs 官方报表对账行。"""

    day: str  # YYYY-MM-DD
    metric: Literal["orders", "gmv", "merchant_revenue", "refund", "sku_sales"]
    collector_value: float
    official_value: float
    absolute_diff: float
    relative_diff: float
    reason: str = ""
    status: ReconciliationStatus = "UNCHECKED"


class FetchRequest(BaseModel):
    store_id: str
    platform: str
    authorization_id: Optional[str] = None
    capabilities: list[ConnectorCapability] = Field(default_factory=list)
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    cursor: Optional[str] = None


class FetchResult(BaseModel):
    health: ConnectorHealth
    envelopes: list[FactEnvelope] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    unavailable_capabilities: list[ConnectorCapability] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 1×1 POC operational records (do not change the frozen connector contract)
# ---------------------------------------------------------------------------

# 真店第一版只允许这四个经营事实；不可靠则 UNKNOWN，禁止猜。
POC_MINIMAL_FACT_KEYS: tuple[str, ...] = (
    "order_count",
    "gross_gmv",
    "merchant_revenue",
    "refund_amount",
)


class MetricDefinitionVersion(BaseModel):
    """Day 0 口径签名。防三个月后平台改统计口径、数字仍能对上但含义已变。"""

    metric: Literal["order_count", "gross_gmv", "merchant_revenue", "refund_amount"]
    definition_version: str = "v1"
    time_basis: str = "order_created_at"
    included_statuses: list[str] = Field(default_factory=list)
    excluded_statuses: list[str] = Field(default_factory=list)
    refund_policy: list[str] = Field(default_factory=list)
    fee_policy: list[str] = Field(default_factory=list)

PocVerdict = Literal["PASS", "PASS_WITH_LIMITS", "REWORK", "STOP"]

AuthStatus = Literal["authorized", "expired", "revoked", "missing"]


class CollectorRun(BaseModel):
    """每日数据质量记录。第 7 天汇总为 Connector Reliability Report。"""

    platform: str
    store_id: str
    run_id: str

    started_at: datetime
    completed_at: Optional[datetime] = None

    health_status: ConnectorHealthStatus
    acquisition_mode: AcquisitionMode = "AUTHORIZED_SESSION"

    facts_collected: int = 0
    facts_rejected: int = 0
    facts_unknown: int = 0

    duplicate_count: int = 0
    schema_error_count: int = 0

    reconciliation_rate: Optional[float] = None
    critical_value_diff: Optional[float] = None

    auth_status: AuthStatus = "missing"
    manual_intervention: bool = False
    freshness_seconds: Optional[int] = None

    unknown_fields: list[str] = Field(default_factory=list)
    notes: str = ""


class PocReview(BaseModel):
    """第 7 天内部评审结果。不改 Contract，只分类。"""

    verdict: PocVerdict
    day_count: int
    reliability_ok: bool
    limits: list[str] = Field(default_factory=list)
    stop_reasons: list[str] = Field(default_factory=list)
    reached_candidate_action: bool = False
