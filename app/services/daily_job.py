from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.store_state import DailyJobResult
from app.services.store_state import build_store_state
from app.services.engines.feature_engine import feature_engine
from app.services.engines.diagnosis_engine import diagnosis_engine
from app.services.engines.opportunity_engine import opportunity_engine
from app.services.engines.strategy_engine import strategy_engine, to_action_candidates


def run_daily_job(db: Session, store_id: str, days: int = 7) -> DailyJobResult | None:
    """
    V1 Daily Job：
    - 生成 StoreState
    - Feature -> Observation
    - Diagnosis -> Hypothesis
    - Opportunity -> Top3
    - Strategy -> Recommendation(Top3) + TodayAction(Top1)
    """
    store_state = build_store_state(db=db, store_id=store_id, days=days)
    if store_state is None:
        return None

    observations = feature_engine(db=db, store_state=store_state, days=days)
    hypothesis = diagnosis_engine(db=db, store_state=store_state, observations=observations)
    ops = opportunity_engine(store_state=store_state, hypothesis=hypothesis)
    recs = strategy_engine(db=db, store_state=store_state, hypothesis=hypothesis, opportunities=ops)

    db.flush()  # ensure ids are allocated
    db.commit()

    top_actions = to_action_candidates(recs)
    today_action = top_actions[0] if top_actions else None

    return DailyJobResult(
        store_state=store_state,
        observations=[{"id": o.id, "metric": o.metric, "what_happened": o.what_happened, "confidence": o.confidence} for o in observations],
        hypothesis=(
            {"id": hypothesis.id, "root_cause": hypothesis.root_cause, "funnel_stage": hypothesis.funnel_stage, "confidence": hypothesis.confidence}
            if hypothesis
            else None
        ),
        opportunities=[op.to_dict() for op in ops],
        top_actions=top_actions,
        today_action=today_action,
    )

