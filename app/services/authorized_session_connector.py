"""DATA-AS-01 — PlatformConnector protocol extension.

AUTHORIZED_SESSION 实现必须挂在此 Contract 下，禁止另起 MeituanCrawler 类族。
本文件只定接口；真实平台采集实现属于后续「最小测试连接器」阶段。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.data_acquisition import (
    CapabilityDeclaration,
    ConnectorHealth,
    FetchRequest,
    FetchResult,
)


@runtime_checkable
class PlatformConnector(Protocol):
    """统一平台连接器契约。

    责任边界：只获得 Evidence（FactEnvelope），不决定 Truth，不写回平台。
    """

    acquisition_mode: str
    source_connector: str
    source_version: str

    def capabilities(self, store_id: str, platform: str) -> list[CapabilityDeclaration]:
        """声明当前真实具备的能力；不具备返回 UNAVAILABLE。"""
        ...

    def health_check(self, store_id: str, platform: str) -> ConnectorHealth:
        """含 AUTH_REQUIRED / SCHEMA_CHANGED；页面结构变化必须停采，不得错字段入库。"""
        ...

    def fetch(self, request: FetchRequest) -> FetchResult:
        """只读拉取；payload 必须走 allowlist，禁止整页 JSON 直灌。"""
        ...


class AuthorizedSessionConnector:
    """商家授权数据连接器（AUTHORIZED_SESSION）骨架。

    CONTRACT FROZEN。未接入真实授权店前，capabilities 全为 UNAVAILABLE，
    health_check 返回 UNAVAILABLE，fetch 不伪造、不 Mock 冒充真实数据。
    """

    acquisition_mode = "AUTHORIZED_SESSION"
    source_connector = "authorized_session"
    source_version = "data-as-01"

    def capabilities(self, store_id: str, platform: str) -> list[CapabilityDeclaration]:
        from app.schemas.data_acquisition import CapabilityDeclaration

        keys = ("ORDERS", "PRODUCT_SALES", "REFUNDS", "FULFILLMENT", "FINANCE")
        return [
            CapabilityDeclaration(
                capability=k,  # type: ignore[arg-type]
                status="UNAVAILABLE",
                notes="DATA-AS-01: real platform adapter not wired yet",
            )
            for k in keys
        ]

    def health_check(self, store_id: str, platform: str) -> ConnectorHealth:
        from datetime import datetime, timezone

        from app.schemas.data_acquisition import ConnectorHealth

        return ConnectorHealth(
            status="UNAVAILABLE",
            platform=platform,
            store_id=store_id,
            acquisition_mode="AUTHORIZED_SESSION",
            checked_at=datetime.now(timezone.utc),
            detail="DATA-AS-01 skeleton: awaiting authorized test-store adapter",
            next_action="implement_minimal_test_connector",
        )

    def fetch(self, request: FetchRequest) -> FetchResult:
        health = self.health_check(request.store_id, request.platform)
        caps = self.capabilities(request.store_id, request.platform)
        unavailable = [c.capability for c in caps if c.status == "UNAVAILABLE"]
        return FetchResult(
            health=health,
            envelopes=[],
            unavailable_capabilities=unavailable,
        )
