from app.schemas.poie import CandidateAction
from app.schemas.arbiter import OpsQueueBrief
from app.services.poie.arbitrate import candidate_to_card, merge_candidates_into_queue
from app.services.poie.scoring import score_candidate


def test_noop_candidate_filtered():
    c = CandidateAction(
        id="n1",
        title="今晚不再新开动作",
        trigger="time",
        suggested_state="noop",
        score=score_candidate(
            business_impact=0.2,
            urgency=0.2,
            confidence=0.9,
            need_for_human=0.05,
            interruption_cost=0.9,
        ),
    )
    assert candidate_to_card(c) is None


def test_confirm_candidate_becomes_need_you():
    c = CandidateAction(
        id="c1",
        title="主图实验待确认",
        trigger="anomaly",
        insight="CTR 下滑",
        why_now="再不拍板会继续漏单",
        suggested_state="confirm",
        interrupt_reason="anomaly",
        score=score_candidate(
            business_impact=0.9,
            urgency=0.85,
            confidence=0.8,
            need_for_human=0.9,
            goal_relevance=0.8,
            interruption_cost=0.35,
        ),
    )
    card = candidate_to_card(c)
    assert card is not None
    assert card.queue_bucket == "need_you"
    assert card.priority_score >= 42


def test_merge_caps_need_you_at_three():
    queue = OpsQueueBrief()
    cands = []
    for i in range(5):
        cands.append(
            CandidateAction(
                id=f"c{i}",
                title=f"事项{i}",
                trigger="anomaly",
                suggested_state="confirm",
                score=score_candidate(
                    business_impact=0.9,
                    urgency=0.9,
                    confidence=0.9,
                    need_for_human=0.9,
                    goal_relevance=0.9,
                    interruption_cost=0.3,
                ),
            )
        )
    merge_candidates_into_queue(queue, cands)
    assert len(queue.need_you) <= 3
    assert queue.filtered_noop_count >= 2
