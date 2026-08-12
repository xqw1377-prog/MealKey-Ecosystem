from app.schemas.content_engine import (
    AnalysisPlaybookRule,
    ChecklistFieldSpec,
    GuideChoice,
    GuideDirective,
    ProactiveEventProjection,
    WorkThreadProjection,
)


def test_checklist_field_spec_matches_v1_contract() -> None:
    spec = ChecklistFieldSpec(
        key="ads_daily_budget_limit",
        label="投流预算上限",
        domain="TRAFFIC",
        source_priority=["merchant", "inferred"],
        first_required_at="pre_lunch_nba",
        used_by=["odo.traffic_budget_guard"],
        blocking_mode="block_action",
        ask_policy="ask_when_blocking",
        stale_after="90d",
        fallback="超限动作一律需确认",
    )
    assert spec.domain == "TRAFFIC"
    assert spec.blocking_mode == "block_action"
    assert spec.ask_policy == "ask_when_blocking"


def test_analysis_playbook_rule_matches_v1_contract() -> None:
    rule = AnalysisPlaybookRule(
        node="pre_lunch_nba",
        enabled_when=["store.open_for_lunch = true"],
        domains=["TRAFFIC", "PRODUCT", "PROFIT", "COMPETITION"],
        output_limit=1,
        protect_mode=False,
        allowed_reasons=["TIME", "ANOMALY", "GOAL_DEVIATION", "OPPORTUNITY"],
        summary="午高峰前只允许一个最值得做的动作进入仲裁",
    )
    assert rule.node == "pre_lunch_nba"
    assert rule.output_limit == 1
    assert "PRODUCT" in rule.domains


def test_projection_contracts_share_same_odo_source() -> None:
    thread = WorkThreadProjection(
        id="thread_1",
        title="牛肉饭点击恢复",
        status="need_you",
        owner_line="等待老板确认主图真实性",
        next_step="48h 主图实验",
        source_odo_id="odo_1",
    )
    guide = GuideDirective(
        id="guide_1",
        type="QUESTION",
        title="这张图和实际份量一致吗？",
        prompt="新图已经准备好了，但我需要确认真实性。",
        choices=[GuideChoice(id="ok", label="一致")],
        required_context_keys=["real_food_photo"],
        source_odo_id="odo_1",
    )
    event = ProactiveEventProjection(
        id="event_1",
        reason="ANOMALY",
        domain="PRODUCT",
        headline="黑椒牛肉饭正在丢点击",
        summary="已完成原因排查，等待主图真实性确认。",
        source_odo_id="odo_1",
    )
    assert thread.source_odo_id == guide.source_odo_id == event.source_odo_id == "odo_1"
