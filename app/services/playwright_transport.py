"""PLAYWRIGHT-AS-01 — AuthorizedSessionConnector 的确定性传输层。

状态（已冻结）：
    PlaywrightTransport               READY_FOR_AUTHORIZED_WIRING
    AuthorizedSessionConnector        UNAVAILABLE UNTIL STORE AUTH
    Real Selector Rules               NOT_CREATED
    Stagehand Recovery Contract       READY
    Stagehand Runtime Integration     NOT_STARTED

三道墙（已实现）：
    1. 授权墙 — Playwright available ≠ Store authorized。
       fetch 必须先通过 SeedStore authorization PASS + store_id/scope binding + READ_ONLY。
    2. Schema Change 墙 — 关键事实 (order_count / gross_gmv / merchant_revenue /
       refund_amount) 规则失配时，connector health 必须显式 DEGRADED / SCHEMA_CHANGED，
       不得只表现为"少了一个 envelope"。
    3. 恢复提议墙 — PROPOSED → VALIDATED_ON_PAGE → RECONCILED →
       CONNECTOR_VERSION_PROMOTED。能抓到数字 ≠ 抓到的是正确业务口径，
       必须与官方报表 reconciliation 后才有资格升级生产规则。

纪律：不绕验证码、不绕安全机制、不做反检测。未安装 Playwright → UNAVAILABLE，
不伪造、不 Mock 冒充真实数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.schemas.data_acquisition import (
    CapabilityDeclaration,
    ConnectorCapability,
    ConnectorHealth,
    ConnectorHealthStatus,
    FactEnvelope,
    FetchRequest,
    FetchResult,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _playwright_available() -> bool:
    try:
        import playwright  # type: ignore[import-not-found]

        return True
    except ImportError:
        return False


def _stagehand_available() -> bool:
    try:
        import stagehand  # type: ignore[import-not-found]

        return True
    except ImportError:
        return False


# 关键事实集：任何一条规则失配 → connector 层可见的 DEGRADED/SCHEMA_CHANGED
CRITICAL_FACT_KEYS: frozenset[str] = frozenset(
    {"order_count", "gross_gmv", "merchant_revenue", "refund_amount"}
)

# 恢复提议状态链（只进不退）
RECOVERY_STATES: tuple[str, ...] = (
    "PROPOSED",
    "VALIDATED_ON_PAGE",
    "RECONCILED",
    "CONNECTOR_VERSION_PROMOTED",
)


# ---------------------------------------------------------------------------
# 平台提取规则：确定性 selector / network allowlist
# 真实 selector 属于「最小测试连接器」阶段逐平台校准，此处只定义结构。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionRule:
    """一条确定性提取规则（不是 AI 生成的猜测）。"""

    capability: ConnectorCapability
    # 事实键（用于关键事实判定，如 gross_gmv）
    fact_key: str = ""
    # 网络层：只允许捕获白名单 API 响应
    network_allowlist: tuple[str, ...] = ()
    # DOM 层：确定性 selector（key → selector）
    selectors: dict[str, str] = field(default_factory=dict)
    # schema 指纹：用于检测页面结构变化（SCHEMA_CHANGED 即停采）
    schema_fingerprint: str = ""

    @property
    def is_critical(self) -> bool:
        return self.fact_key in CRITICAL_FACT_KEYS


@dataclass
class ShadowRecoveryProposal:
    """Stagehand 兼容的 Shadow 恢复提议 — 只提议，不落 Truth，不直接替换生产规则。

    状态链: PROPOSED → VALIDATED_ON_PAGE → RECONCILED → CONNECTOR_VERSION_PROMOTED
    能在页面命中 (VALIDATED_ON_PAGE) 不等于口径正确 (需要 RECONCILED)。
    """

    broken_rule: str
    proposed_selectors: dict[str, str] = field(default_factory=dict)
    rationale: str = ""
    status: str = "PROPOSED"
    validated_by: str = ""  # 只有 "deterministic" 才能推进到 VALIDATED_ON_PAGE
    reconciled_against: str = ""  # 官方报表基准标识

    def to_dict(self) -> dict[str, Any]:
        return {
            "broken_rule": self.broken_rule,
            "proposed_selectors": self.proposed_selectors,
            "rationale": self.rationale,
            "status": self.status,
            "validated_by": self.validated_by,
            "reconciled_against": self.reconciled_against,
        }


class PlaywrightTransport:
    """AUTHORIZED_SESSION 的确定性浏览器传输层。

    生命周期：
        商家自助登录（人工，一次性）
        → persistent authorized context（复用登录态）
        → deterministic network/DOM read
        → Raw Evidence（FactEnvelope，走 allowlist）
        → 下游 Reconciliation / Truth Promotion（不在本层）
    """

    acquisition_mode = "AUTHORIZED_SESSION"
    source_connector = "playwright_authorized_session"
    source_version = "playwright-as-01"

    def __init__(self, *, profile_dir: str = "data/playwright_profiles"):
        self.profile_dir = profile_dir
        self._recovery_proposals: list[ShadowRecoveryProposal] = []
        self._schema_breaks: set[str] = set()  # 本轮 fetch 中失配的关键事实键

    # -- 授权墙 -------------------------------------------------------------

    @staticmethod
    def _authorization_pass(request: FetchRequest) -> bool:
        """授权墙：必须存在有效 AuthorizationRecord 才允许真实采集。

        Playwright available ≠ Store authorized。授权判断归 SeedStore/
        AuthorizationRecord 层，本方法只检查门是否开着。
        """
        from app.schemas.data_acquisition import AuthorizationRecord

        # 真实实现查 DB；此处只定义门禁语义（未接线 → 永远不开）
        del AuthorizationRecord, request
        return False

    # -- 契约实现 -----------------------------------------------------------

    def capabilities(self, store_id: str, platform: str) -> list[CapabilityDeclaration]:
        keys: tuple[ConnectorCapability, ...] = (
            "ORDERS", "PRODUCT_SALES", "REFUNDS", "FULFILLMENT", "FINANCE",
        )
        notes = (
            "PLAYWRIGHT-AS-01: playwright not installed "
            "(pip install playwright && playwright install)"
            if not _playwright_available()
            else "PLAYWRIGHT-AS-01: transport READY_FOR_AUTHORIZED_WIRING; "
            "gated by SeedStore authorization"
        )
        return [
            CapabilityDeclaration(capability=k, status="UNAVAILABLE", notes=notes)
            for k in keys
        ]

    def health_check(self, store_id: str, platform: str) -> ConnectorHealth:
        if not _playwright_available():
            return ConnectorHealth(
                status="UNAVAILABLE",
                platform=platform,
                store_id=store_id,
                acquisition_mode=self.acquisition_mode,
                checked_at=_utcnow(),
                detail="playwright runtime not installed",
                next_action="install_playwright",
            )
        return ConnectorHealth(
            status="AUTH_REQUIRED",
            platform=platform,
            store_id=store_id,
            acquisition_mode=self.acquisition_mode,
            checked_at=_utcnow(),
            detail="READY_FOR_AUTHORIZED_WIRING; requires SeedStore authorization "
            "PASS + store_id/scope binding + READ_ONLY",
            next_action="seed_store_authorization",
        )

    def fetch(self, request: FetchRequest) -> FetchResult:
        """确定性只读拉取。三道墙全过关才可能产出证据；当前返回空 + 明确 health。"""
        health = self.health_check(request.store_id, request.platform)

        # 授权墙：runtime 可用也不等于门店已授权
        if health.status != "UNAVAILABLE" and not self._authorization_pass(request):
            health = ConnectorHealth(
                status="AUTH_REQUIRED",
                platform=request.platform,
                store_id=request.store_id,
                acquisition_mode=self.acquisition_mode,
                checked_at=_utcnow(),
                detail="authorization record missing or revoked for this store",
                next_action="seed_store_authorization",
            )

        caps = self.capabilities(request.store_id, request.platform)
        unavailable = [c.capability for c in caps if c.status == "UNAVAILABLE"]
        return FetchResult(health=health, envelopes=[], unavailable_capabilities=unavailable)

    # -- 真实读取路径（授权到位后启用） ------------------------------------

    def open_authorized_context(self, authorization_id: str):
        """打开持久化授权浏览上下文（商家已自助完成登录）。

        纪律：本方法不代填账号密码、不处理验证码。
        登录态失效 → 上层标记 AUTH_REQUIRED 并引导商家重新自助登录。
        """
        if not _playwright_available():
            raise RuntimeError("playwright not installed")
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=f"{self.profile_dir}/{authorization_id}",
            headless=False,  # 授权会话必须可见，便于商家确认
        )
        return pw, context

    def read_with_rules(
        self,
        context,
        rules: list[ExtractionRule],
    ) -> list[FactEnvelope]:
        """按确定性规则读取页面/网络证据，产出 FactEnvelope。

        Schema Change 墙：关键事实规则失配 → 记入 _schema_breaks，
        health_check_after_read() 将报告 DEGRADED / SCHEMA_CHANGED。
        """
        self._schema_breaks = set()
        envelopes: list[FactEnvelope] = []
        page = context.new_page()

        for rule in rules:
            captured: list[dict[str, Any]] = []

            if rule.network_allowlist:
                def _on_response(response, _rule=rule, _sink=captured):
                    if any(pattern in response.url for pattern in _rule.network_allowlist):
                        try:
                            _sink.append({"url": response.url, "json": response.json()})
                        except Exception:  # noqa: BLE001 — 非 JSON 响应跳过
                            pass

                page.on("response", _on_response)

            rule_matched = bool(rule.network_allowlist)
            for key, selector in rule.selectors.items():
                locator = page.locator(selector)
                if locator.count() == 0:
                    self._record_schema_break(rule, key, selector)
                    continue
                rule_matched = True
                captured.append({"dom": key, "value": locator.first.inner_text()})

            if rule.is_critical and not rule_matched:
                # 关键事实规则完全失配 → connector 层可见
                self._schema_breaks.add(rule.fact_key)

            envelopes.extend(self._normalize(rule, captured))

        return envelopes

    def health_check_after_read(self, store_id: str, platform: str) -> ConnectorHealth:
        """读取后的 health：关键事实失配必须在这里可见。

        Missing critical fact must be observable at connector health level.
        多数关键事实失配 → SCHEMA_CHANGED（停采）；个别 → DEGRADED。
        """
        base = self.health_check(store_id, platform)
        if not self._schema_breaks:
            return base
        missing = sorted(self._schema_breaks)
        severe = len(missing) >= 2
        return ConnectorHealth(
            status="SCHEMA_CHANGED" if severe else "DEGRADED",
            platform=platform,
            store_id=store_id,
            acquisition_mode=self.acquisition_mode,
            checked_at=_utcnow(),
            detail=f"critical fact rules broken: {', '.join(missing)}",
            next_action="halt_ingest" if severe else "shadow_recovery",
        )

    # -- Shadow 恢复（Stagehand 只提议；状态链只进不退） --------------------

    def _record_schema_break(self, rule: ExtractionRule, key: str, selector: str) -> None:
        proposal = ShadowRecoveryProposal(
            broken_rule=f"{rule.capability}:{key}",
            proposed_selectors={},
            rationale=(
                f"deterministic selector '{selector}' no longer matches; "
                f"page schema likely changed — extraction halted for this rule"
            ),
        )
        if _stagehand_available():
            proposal.rationale += "; stagehand runtime available for shadow proposal"
        else:
            proposal.rationale += (
                "; stagehand runtime NOT_STARTED — recovery contract accepts proposals"
            )
        self._recovery_proposals.append(proposal)

    def pending_recovery_proposals(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._recovery_proposals if p.status == "PROPOSED"]

    def validate_recovery_proposal(self, index: int, context) -> bool:
        """推进 PROPOSED → VALIDATED_ON_PAGE。

        只证明 selector 在当前页面确定性命中；不等于口径正确，
        不替换生产规则。
        """
        if index < 0 or index >= len(self._recovery_proposals):
            return False
        proposal = self._recovery_proposals[index]
        if proposal.status != "PROPOSED" or not proposal.proposed_selectors:
            return False
        page = context.pages[0] if context.pages else context.new_page()
        ok = all(
            page.locator(selector).count() > 0
            for selector in proposal.proposed_selectors.values()
        )
        if ok:
            proposal.status = "VALIDATED_ON_PAGE"
            proposal.validated_by = "deterministic"
        return ok

    def reconcile_recovery_proposal(self, index: int, baseline_ref: str) -> bool:
        """推进 VALIDATED_ON_PAGE → RECONCILED。

        baseline_ref: 官方报表基准标识（Day 0 baseline / 官方对账单）。
        能抓到数字 ≠ 抓到的是正确业务口径 —— 必须对过官方报表。
        """
        if index < 0 or index >= len(self._recovery_proposals):
            return False
        proposal = self._recovery_proposals[index]
        if proposal.status != "VALIDATED_ON_PAGE" or not baseline_ref:
            return False
        proposal.status = "RECONCILED"
        proposal.reconciled_against = baseline_ref
        return True

    def promote_recovery_proposal(self, index: int) -> bool:
        """推进 RECONCILED → CONNECTOR_VERSION_PROMOTED。

        只有完成 reconciliation 的提议才有资格升级为新的 connector 版本规则。
        本方法只标记状态；规则替换由人工发布新 connector version 完成。
        """
        if index < 0 or index >= len(self._recovery_proposals):
            return False
        proposal = self._recovery_proposals[index]
        if proposal.status != "RECONCILED":
            return False
        proposal.status = "CONNECTOR_VERSION_PROMOTED"
        return True

    # -- 归一化（allowlist 纪律） -------------------------------------------

    def _normalize(
        self, rule: ExtractionRule, captured: list[dict[str, Any]]
    ) -> list[FactEnvelope]:
        from app.schemas.data_acquisition import FactType

        envelopes: list[FactEnvelope] = []
        fact_type_map: dict[ConnectorCapability, FactType] = {
            "ORDERS": "ORDER",
            "PRODUCT_SALES": "ORDER",
            "REFUNDS": "REFUND",
            "FULFILLMENT": "ORDER",
            "FINANCE": "SETTLEMENT",
        }
        fact_type = fact_type_map.get(rule.capability)
        if fact_type is None:
            return []
        for item in captured:
            envelopes.append(
                FactEnvelope(
                    platform="authorized_session",
                    store_id="",
                    fact_type=fact_type,
                    fact_key=f"{rule.capability}:{item.get('dom', item.get('url', 'unknown'))}",
                    occurred_at=_utcnow(),
                    payload=item,
                )
            )
        return envelopes
