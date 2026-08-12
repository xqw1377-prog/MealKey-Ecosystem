from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.ohre import Experiment, Recommendation
from app.services.agents import build_single_agent


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_growth_agent_ranks_cross_agent_opportunities_with_explainable_score() -> None:
    db = _session()
    seeded = seed_demo(db)

    result = build_single_agent(db, seeded["store_id"], "growth")

    assert result is not None
    assert result["selected_opportunity"]
    assert result["strategy_score"] > 0
    assert result["today_priority"]
    assert {"product", "menu", "competition", "diagnosis"}.issubset(
        {row["source_agent"] for row in result["opportunity_pool"]}
    )
    scores = [row["score"] for row in result["opportunity_pool"]]
    assert scores == sorted(scores, reverse=True)
    selected = result["selected_opportunity"]
    assert selected["executable"] is True
    assert set(selected["factors"]) == {
        "expected_impact",
        "confidence",
        "ease_of_execution",
        "strategic_fit",
        "risk",
    }
    assert selected["evidence"]


def test_growth_agent_builds_adaptive_seven_day_single_variable_plan() -> None:
    db = _session()
    seeded = seed_demo(db)

    result = build_single_agent(db, seeded["store_id"], "growth")

    assert result is not None
    assert result["weekly_goal"]
    assert [step["day"] for step in result["weekly_plan"]] == list(range(1, 8))
    assert result["weekly_plan"][0]["stop_condition"]
    assert result["weekly_plan"][1]["dependency"].startswith("Day 1")
    assert "单变量" in " ".join(
        step["goal"] + step["instruction"] for step in result["weekly_plan"]
    )
    assert len(result["do_not_do"]) >= 3


def test_growth_agent_learns_from_experiment_result() -> None:
    db = _session()
    seeded = seed_demo(db)
    initial = build_single_agent(db, seeded["store_id"], "growth")
    assert initial is not None
    recommendation_id = initial["selected_opportunity"]["recommendation_id"]
    initial_score = initial["selected_opportunity"]["score"]
    experiment = db.execute(
        select(Experiment).where(Experiment.recommendation_id == recommendation_id)
    ).scalars().first()
    if experiment is None:
        recommendation = db.execute(
            select(Recommendation).where(Recommendation.id == recommendation_id)
        ).scalar_one_or_none()
        assert recommendation is not None
        experiment = Experiment(
            store_id=seeded["store_id"],
            recommendation_id=recommendation.id,
            result="pending",
        )
    experiment.result = "positive"
    experiment.lift_pct = 9.5
    db.add(experiment)
    db.commit()

    result = build_single_agent(db, seeded["store_id"], "growth")

    assert result is not None
    assert result["experiments_summary"]["positive"] >= 1
    assert result["plan_progress_pct"] > 0
    assert "验证有效" in result["learning_summary"]
    learned = next(
        row for row in result["opportunity_pool"] if row["recommendation_id"] == recommendation_id
    )
    assert learned["score"] >= initial_score
    assert any("历史实验结果：positive" in evidence for evidence in learned["evidence"])
