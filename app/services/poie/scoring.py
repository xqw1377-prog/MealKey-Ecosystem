"""POIE 统一仲裁打分。"""

from __future__ import annotations

from app.schemas.poie import ArbitrationScore
from app.services.priority_arbiter import score_interrupt


def score_candidate(
    *,
    business_impact: float,
    urgency: float,
    confidence: float,
    need_for_human: float,
    goal_relevance: float = 0.55,
    interruption_cost: float = 0.55,
) -> ArbitrationScore:
    """Impact × Urgency × Confidence × GoalRelevance × NeedHuman ÷ Cost。"""
    score = ArbitrationScore(
        business_impact=business_impact,
        urgency=urgency,
        confidence=confidence,
        goal_relevance=goal_relevance,
        need_for_human=need_for_human,
        interruption_cost=interruption_cost,
    )
    base = score_interrupt(
        value=business_impact,
        urgency=urgency,
        confidence=confidence,
        need_human=need_for_human,
        disturb_cost=interruption_cost,
    )
    score.priority = round(min(100.0, base * max(0.35, goal_relevance) / 0.55), 2)
    return score
