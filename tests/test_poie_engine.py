from datetime import datetime, timezone

from app.schemas.poie import ArbitrationScore, CandidateAction
from app.schemas.store_state import ManagerHomeBrief, ParallelNote, PrimaryExperimentBrief
from app.services.poie import run_poie, score_candidate


def test_score_candidate_includes_goal_relevance():
    low = score_candidate(
        business_impact=0.7,
        urgency=0.7,
        confidence=0.8,
        need_for_human=0.8,
        goal_relevance=0.2,
    )
    high = score_candidate(
        business_impact=0.7,
        urgency=0.7,
        confidence=0.8,
        need_for_human=0.8,
        goal_relevance=0.95,
    )
    assert high.priority > low.priority
    assert isinstance(high, ArbitrationScore)


def test_run_poie_projects_ops_queue():
    brief = ManagerHomeBrief(
        store_name="测试店",
        business_health_score=70,
        business_judgment="平稳",
        parallel_notes=[ParallelNote(agent_key="review", title="自动回评", kind="auto")],
        primary_experiment=PrimaryExperimentBrief(
            title="主图实验",
            status="proposed",
            recommendation_id="r1",
            expected_metric="ctr",
            expected_lift_low=8,
            expected_lift_high=15,
        ),
    )
    result = run_poie(brief, store_id="s1")
    assert result.ops_queue.need_you
    assert result.candidates_total >= 1
    assert "筛掉" in result.principle or "老板" in result.principle
    assert result.generated_at.tzinfo is not None or isinstance(result.generated_at, datetime)


def test_candidate_action_defaults_to_noop_until_arbitrated():
    c = CandidateAction(id="c1", title="竞品降价1元", trigger="opportunity")
    assert c.suggested_state == "noop"
