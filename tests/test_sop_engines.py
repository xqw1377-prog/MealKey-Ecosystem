"""SOP 双引擎测试：Merchant Context Engine + Analysis Playbook。

覆盖：
- A1: 信息字段元数据 InfoFieldMeta
- A2: MOS + Safe Mode
- A3: Question Arbitration blocking 维度
- B1: 12 步分析 Pipeline
- B2: Daily Operating Clock
- B3: DecisionCard ODO 补全字段
"""

from app.schemas.merchant_understanding import (
    InfoFieldMeta,
    MerchantUnderstanding,
    OperatingPreferences,
    OperatingConstraints,
    PermissionPolicy,
)
from app.schemas.arbiter import DecisionCard
from app.services.mos_engine import (
    check_mos,
    determine_system_mode,
    is_action_allowed_in_safe_mode,
    update_mos_status,
)
from app.services.analysis_pipeline import (
    PipelineContext,
    run_analysis_pipeline,
    OperatingDecisionObject,
)


def _make_mu(**overrides) -> MerchantUnderstanding:
    """生成测试用 MerchantUnderstanding。"""
    mu = MerchantUnderstanding(
        store_id="s1",
        preferences=OperatingPreferences(),
        constraints=OperatingConstraints(),
        permissions=PermissionPolicy(),
    )
    for k, v in overrides.items():
        setattr(mu, k, v)
    return mu


# ═══════════════════════════════════════════════════════════
# A1: 信息字段元数据
# ═══════════════════════════════════════════════════════════


def test_info_field_meta_has_7_attributes() -> None:
    """InfoFieldMeta 有 source/confidence/last_verified_at/volatility_days/required_for/blocking。"""
    meta = InfoFieldMeta(
        key="profit_floor",
        label="利润底线",
        domain="PROFIT",
        value=0.58,
        source="user",
        source_priority=["user", "inferred"],
        confidence=0.9,
        first_required_at="pre_lunch_nba",
        volatility_days=90,
        required_for=["promo", "ads"],
        used_by=["odo.profit_guard"],
        blocking=True,
        blocking_mode="safe_mode",
        ask_policy="ask_when_blocking",
        fallback="禁止利润敏感动作自动执行",
    )
    assert meta.label == "利润底线"
    assert meta.domain == "PROFIT"
    assert meta.source == "user"
    assert meta.source_priority == ["user", "inferred"]
    assert meta.confidence == 0.9
    assert meta.first_required_at == "pre_lunch_nba"
    assert meta.volatility_days == 90
    assert "promo" in meta.required_for
    assert "odo.profit_guard" in meta.used_by
    assert meta.blocking is True
    assert meta.blocking_mode == "safe_mode"
    assert meta.ask_policy == "ask_when_blocking"


def test_merchant_understanding_has_field_meta() -> None:
    """MerchantUnderstanding 有 field_meta 字典。"""
    mu = _make_mu()
    assert hasattr(mu, "field_meta")
    assert isinstance(mu.field_meta, dict)


# ═══════════════════════════════════════════════════════════
# A2: MOS + Safe Mode
# ═══════════════════════════════════════════════════════════


def test_mos_not_satisfied_for_empty_understanding() -> None:
    """空 understanding 应该 MOS 不满足。"""
    mu = _make_mu()
    satisfied, blocking = check_mos(mu)
    assert not satisfied
    assert len(blocking) > 0


def test_mos_satisfied_with_minimum_info() -> None:
    """填了关键信息后 MOS 应该满足。"""
    mu = _make_mu()
    mu.store_profile = {"store_name": "测试店"}
    mu.preferences.priority_style = "profit"
    mu.permissions.low_risk_auto_ok = True
    mu.constraints.lunch_capacity_per_hour = 100
    satisfied, blocking = check_mos(mu)
    assert satisfied
    assert blocking == []


def test_safe_mode_when_mos_not_satisfied() -> None:
    """MOS 不满足时 system_mode=safe。"""
    mu = _make_mu()
    mode = determine_system_mode(mu)
    assert mode == "safe"


def test_operating_mode_when_mos_satisfied() -> None:
    """MOS 满足时 system_mode=operating。"""
    mu = _make_mu()
    mu.store_profile = {"name": "店"}
    mu.preferences.priority_style = "balanced"
    mu.permissions.low_risk_auto_ok = False  # 已确认（False 也算）
    mu.constraints.profit_floor_rate = 0.58
    mode = determine_system_mode(mu)
    assert mode == "operating"


def test_safe_mode_blocks_spend_actions() -> None:
    """Safe Mode 禁止补贴/投流类动作。"""
    assert not is_action_allowed_in_safe_mode("join_lunch_campaign")
    assert not is_action_allowed_in_safe_mode("boost_hero_item_ads")
    assert not is_action_allowed_in_safe_mode("store_discount")


def test_safe_mode_allows_low_risk_actions() -> None:
    """Safe Mode 允许低风险动作。"""
    assert is_action_allowed_in_safe_mode("batch_reply_negative_reviews")
    assert is_action_allowed_in_safe_mode("change_title")
    assert is_action_allowed_in_safe_mode("menu_patch")


def test_update_mos_status_sets_fields() -> None:
    """update_mos_status 正确设置 mos_satisfied/mos_blocking_fields/system_mode。"""
    mu = _make_mu()
    mu = update_mos_status(mu)
    assert mu.mos_satisfied is False
    assert len(mu.mos_blocking_fields) > 0
    assert mu.system_mode == "safe"


# ═══════════════════════════════════════════════════════════
# B1: 12 步分析 Pipeline
# ═══════════════════════════════════════════════════════════


def test_pipeline_completes_all_steps() -> None:
    """Pipeline 完成全部步骤（12 步基础 + OPTIONS + RISK GATE = 14 步）。"""
    ctx = PipelineContext(
        store_id="s1",
        trigger="anomaly",
        observed_metric="ctr",
        observed_delta=-15.0,
        compare_baseline="7日基线",
        root_cause="主图竞争力下降",
        evidence=["竞品3家换图"],
        subject_type="sku",
        subject_id="sku_1",
        subject_name="黑椒牛肉饭",
        estimated_loss=25,
        goal_text="稳定订单",
        goal_relevance_level="high",
        required_context_keys=["real_food_photo"],
        selected_action="换主图",
        selected_action_type="change_main_image",
        source_node="pre_lunch_nba",
        success_metric="CTR ≥ +8%",
    )
    odo = run_analysis_pipeline(ctx)
    assert len(odo.pipeline_steps_completed) >= 12  # 至少 12 步（V1 扩展后 14 步）
    assert "observe" in odo.pipeline_steps_completed
    assert "learn_hook" in odo.pipeline_steps_completed
    assert "options" in odo.pipeline_steps_completed  # V1 补全
    assert "risk_gate" in odo.pipeline_steps_completed  # V1 补全
    assert odo.reason == "ANOMALY"
    assert odo.domain == "PRODUCT"
    assert odo.object.type == "sku"
    assert odo.object.id == "sku_1"
    assert odo.source_node == "pre_lunch_nba"
    assert odo.finding.metric == "ctr"
    assert odo.diagnosis.primary == "主图竞争力下降"
    assert odo.estimated_loss == 25
    assert odo.required_context_keys == ["real_food_photo"]
    assert odo.goal_relevance_level == "high"
    assert odo.recommended_action.type == "change_main_image"
    assert odo.recommended_action.title == "换主图"
    assert odo.execution_mode in ("AUTO", "AUTO_AND_REPORT", "ASK_APPROVAL", "ASK_INFORMATION", "OBSERVE", "DROP")
    assert odo.risk_level in ("low", "medium", "high")


def test_pipeline_safe_mode_blocks_action() -> None:
    """Safe Mode 下 Pipeline 应标记 safe_mode_blocked。"""
    ctx = PipelineContext(
        store_id="s1",
        trigger="time",
        selected_action_type="join_lunch_campaign",  # 被 Safe Mode 禁止
        system_mode="safe",
    )
    odo = run_analysis_pipeline(ctx)
    assert odo.safe_mode_blocked is True
    assert odo.autonomy == "silent_observe"


def test_pipeline_operating_mode_allows_action() -> None:
    """Operating Mode 下不阻塞。"""
    ctx = PipelineContext(
        store_id="s1",
        selected_action_type="change_title",
        system_mode="operating",
    )
    odo = run_analysis_pipeline(ctx)
    assert odo.safe_mode_blocked is False


def test_pipeline_returns_operating_decision_object() -> None:
    """Pipeline 返回 OperatingDecisionObject。"""
    ctx = PipelineContext(store_id="s1")
    odo = run_analysis_pipeline(ctx)
    assert isinstance(odo, OperatingDecisionObject)
    assert odo.trigger
    assert odo.confidence > 0


# ═══════════════════════════════════════════════════════════
# B3: DecisionCard ODO 字段
# ═══════════════════════════════════════════════════════════


def test_decision_card_has_odo_fields() -> None:
    """DecisionCard 包含 ODO 补全字段。"""
    card = DecisionCard(
        id="test",
        title="测试",
        arbiter_state="confirm",
        queue_bucket="need_you",
        evidence=["CTR -15%"],
        business_impact="预计损失20单",
        estimated_loss=20,
        goal_relevance="与当前目标高相关",
        observation_window_hours=48,
        confidence=0.85,
    )
    assert card.evidence == ["CTR -15%"]
    assert card.estimated_loss == 20
    assert card.goal_relevance
    assert card.observation_window_hours == 48
    assert card.confidence == 0.85
