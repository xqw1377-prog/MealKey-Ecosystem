"""PLAYWRIGHT-AS-01 + GROWTH-PRIMITIVE-02 测试（含三道墙 + capability 门）。"""
from app.services.playwright_transport import (
    CRITICAL_FACT_KEYS,
    ExtractionRule,
    PlaywrightTransport,
)
from app.schemas.data_acquisition import FetchRequest
from app.services.growth_primitives import (
    GROWTH_PRIMITIVES,
    check_budget_guard,
    get_primitive,
    primitives_for_segment,
)


# ---------------------------------------------------------------------------
# 钉1: 授权墙 — Playwright available ≠ Store authorized
# ---------------------------------------------------------------------------


def test_transport_never_fakes_data_without_runtime() -> None:
    """playwright 未安装 → UNAVAILABLE + 空 envelopes，绝不冒充真实数据。"""
    t = PlaywrightTransport()
    result = t.fetch(FetchRequest(store_id="s1", platform="meituan"))
    assert result.envelopes == []
    assert result.health.status in ("UNAVAILABLE", "AUTH_REQUIRED")
    assert result.unavailable_capabilities


def test_authorization_wall_gates_fetch() -> None:
    """授权墙：runtime 可用也不等于门店已授权 — fetch 永远过授权门。"""
    t = PlaywrightTransport()
    # 即使伪造 runtime 可用状态，_authorization_pass 未接线 → 门不开
    assert t._authorization_pass(FetchRequest(store_id="s1", platform="meituan")) is False
    result = t.fetch(FetchRequest(store_id="s1", platform="meituan"))
    assert result.envelopes == []
    assert result.health.next_action in ("install_playwright", "seed_store_authorization")


# ---------------------------------------------------------------------------
# 钉2: Schema Change 墙 — 关键事实失配必须 connector health 可见
# ---------------------------------------------------------------------------


class _NoMatchLocator:
    def count(self):
        return 0


class _NoMatchPage:
    def locator(self, selector):
        return _NoMatchLocator()

    def on(self, *a, **k):
        pass


class _NoMatchContext:
    def new_page(self):
        return _NoMatchPage()


def test_critical_fact_break_surfaces_in_health() -> None:
    """关键事实(gross_gmv)规则失配 → health 变 DEGRADED/SCHEMA_CHANGED，不只是少一个 envelope。"""
    t = PlaywrightTransport()
    rule = ExtractionRule(
        capability="FINANCE",
        fact_key="gross_gmv",  # 关键事实
        selectors={"gmv_cell": "#gmv"},
        schema_fingerprint="v1",
    )
    envelopes = t.read_with_rules(_NoMatchContext(), [rule])
    assert envelopes == []

    health = t.health_check_after_read("s1", "meituan")
    assert health.status in ("DEGRADED", "SCHEMA_CHANGED")
    assert "gross_gmv" in health.detail
    assert health.next_action in ("halt_ingest", "shadow_recovery")


def test_multiple_critical_breaks_halt_ingest() -> None:
    """多条关键事实失配 → SCHEMA_CHANGED + halt_ingest。"""
    t = PlaywrightTransport()
    rules = [
        ExtractionRule(capability="FINANCE", fact_key="gross_gmv", selectors={"a": "#a"}),
        ExtractionRule(capability="FINANCE", fact_key="merchant_revenue", selectors={"b": "#b"}),
    ]
    t.read_with_rules(_NoMatchContext(), rules)
    health = t.health_check_after_read("s1", "meituan")
    assert health.status == "SCHEMA_CHANGED"
    assert health.next_action == "halt_ingest"


def test_no_breaks_health_unchanged() -> None:
    t = PlaywrightTransport()
    health = t.health_check_after_read("s1", "meituan")
    assert health.status in ("UNAVAILABLE", "AUTH_REQUIRED")  # 无 schema break 时保持原状态


# ---------------------------------------------------------------------------
# 钉3: 恢复提议状态链 — 只进不退，reconciliation 才能升级
# ---------------------------------------------------------------------------


def test_recovery_state_chain_requires_reconciliation() -> None:
    """PROPOSED → VALIDATED_ON_PAGE → RECONCILED → CONNECTOR_VERSION_PROMOTED。"""
    t = PlaywrightTransport()
    t._record_schema_break(
        ExtractionRule(capability="FINANCE", fact_key="gross_gmv", selectors={"x": "#x"}),
        "x", "#x",
    )
    # 人工/Stagehand 填入提议 selector
    t._recovery_proposals[0].proposed_selectors = {"gmv_cell": "#new-gmv"}

    # 跳级 promote 被拒（必须先 VALIDATED_ON_PAGE + RECONCILED）
    assert t.promote_recovery_proposal(0) is False
    assert t.reconcile_recovery_proposal(0, "day0_baseline_v1") is False  # 还没 VALIDATED_ON_PAGE

    # VALIDATED_ON_PAGE（用真实命中页面的假 context）
    class _HitLocator:
        def count(self):
            return 1

    class _HitPage:
        def locator(self, s):
            return _HitLocator()

    class _HitContext:
        pages = [_HitPage()]

        def new_page(self):
            return _HitPage()

    assert t.validate_recovery_proposal(0, _HitContext()) is True
    assert t._recovery_proposals[0].status == "VALIDATED_ON_PAGE"
    assert t._recovery_proposals[0].validated_by == "deterministic"

    # 没有官方基准 → 不能 RECONCILED
    assert t.reconcile_recovery_proposal(0, "") is False
    # 有官方基准 → RECONCILED
    assert t.reconcile_recovery_proposal(0, "day0_baseline_v1") is True
    assert t._recovery_proposals[0].reconciled_against == "day0_baseline_v1"

    # RECONCILED 后才能升级
    assert t.promote_recovery_proposal(0) is True
    assert t._recovery_proposals[0].status == "CONNECTOR_VERSION_PROMOTED"


# ---------------------------------------------------------------------------
# 钉4: Growth 原语 — permission ≠ capability
# ---------------------------------------------------------------------------


def test_primitives_registry_complete() -> None:
    assert len(GROWTH_PRIMITIVES) >= 6
    required_fields = [
        "target_segment", "channel", "offer_type", "eligibility",
        "est_cost_per_target", "profit_guard", "risk_level", "permission",
        "frequency_cap", "observation_window_hours", "attribution_method",
        "incremental_success_metric", "execution_capability",
    ]
    for p in GROWTH_PRIMITIVES.values():
        for f in required_fields:
            assert getattr(p, f) is not None, f"{p.action_type} missing {f}"


def test_mutating_primitives_blocked_not_implemented() -> None:
    """permission=AUTO_AND_REPORT + capability=NOT_IMPLEMENTED → BLOCKED_NOT_IMPLEMENTED。"""
    watch = get_primitive("CHURN_RISK_WATCH")
    assert watch is not None
    assert watch.execution_capability == "OBSERVE_ONLY"
    assert watch.execution_status == "OBSERVE_ONLY"

    # 所有 mutating 原语（发券/积分/推荐）都必须 BLOCKED_NOT_IMPLEMENTED
    for name in ("REACTIVATE_SLEEPING_COUPON", "NEW_MEMBER_FIRST_ORDER_COUPON",
                 "REFERRAL_BOTH_REWARD", "LOYALTY_POINTS_MULTIPLIER",
                 "COMPLAINT_RECOVERY_COUPON"):
        p = get_primitive(name)
        assert p is not None, name
        assert p.execution_capability == "NOT_IMPLEMENTED", name
        assert p.execution_status == "BLOCKED_NOT_IMPLEMENTED", name


def test_budget_guard_blocks_overspend() -> None:
    ok = check_budget_guard("REACTIVATE_SLEEPING_COUPON", 50)
    assert ok["ok"] is True
    assert ok["est_total_cost"] == 250.0

    blocked = check_budget_guard("REACTIVATE_SLEEPING_COUPON", 100)
    assert blocked["ok"] is False
    assert blocked["max_targets"] == 60


def test_segment_filter() -> None:
    sleeping = primitives_for_segment("SLEEPING")
    assert any(p.action_type == "REACTIVATE_SLEEPING_COUPON" for p in sleeping)
    churn = primitives_for_segment("CHURN_RISK")
    assert any(p.action_type == "CHURN_RISK_WATCH" for p in churn)
    assert any(p.action_type == "LOYALTY_POINTS_MULTIPLIER" for p in churn)


def test_get_primitive_unknown() -> None:
    assert get_primitive("NONEXISTENT") is None
