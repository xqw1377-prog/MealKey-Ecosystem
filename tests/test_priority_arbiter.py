from app.schemas.arbiter import DecisionCard
from app.schemas.events import EventEngineResult, OperatingEvent
from app.schemas.store_state import ManagerHomeBrief, ParallelNote, PrimaryExperimentBrief
from app.services.priority_arbiter import build_ops_queue, score_interrupt
from datetime import datetime, timezone


def test_score_interrupt_prefers_high_urgency_human_need():
    low = score_interrupt(value=0.5, urgency=0.2, confidence=0.5, need_human=0.1, disturb_cost=0.8)
    high = score_interrupt(value=0.8, urgency=0.9, confidence=0.85, need_human=1.0, disturb_cost=0.35)
    assert high > low


def test_build_ops_queue_puts_confirm_in_need_you_and_auto_in_working():
    brief = ManagerHomeBrief(
        store_name="测试店",
        business_health_score=72,
        business_judgment="店况平稳",
        parallel_notes=[ParallelNote(agent_key="review", title="自动回复评价", kind="auto")],
        primary_experiment=PrimaryExperimentBrief(
            title="黑椒牛肉饭主图实验",
            status="proposed",
            recommendation_id="rec-1",
            expected_metric="ctr",
            expected_lift_low=8,
            expected_lift_high=17,
            window_hours=48,
        ),
    )
    events = EventEngineResult(
        store_id="s1",
        generated_at=datetime.now(timezone.utc),
        events=[
            OperatingEvent(
                id="e1",
                store_id="s1",
                event_type="CTR_DROP",
                title="竞品换了一张图",
                detail="轻微变化",
                severity="low",
                detected_at=datetime.now(timezone.utc),
                confidence=0.4,
                manager_decision="record",
            )
        ],
        open_count=1,
    )
    queue = build_ops_queue(brief, events=events, agents=None, strategy_memory=None)
    assert queue.need_you
    assert isinstance(queue.need_you[0], DecisionCard)
    assert queue.need_you[0].arbiter_state in {"confirm", "need_input", "report_result"}
    assert any(item.arbiter_state == "auto_do" for item in queue.working)
    assert queue.filtered_noop_count >= 1
