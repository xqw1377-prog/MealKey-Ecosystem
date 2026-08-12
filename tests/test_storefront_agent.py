from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.ohre import Recommendation
from app.services.agents import build_single_agent, create_storefront_action


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_storefront_agent_scores_dimensions_and_sales_impact() -> None:
    db = _session()
    seeded = seed_demo(db)

    result = build_single_agent(db, seeded["store_id"], "storefront")

    assert result is not None
    assert 20 <= result["health_score"] <= 98
    assert {row["key"] for row in result["dimensions"]} == {
        "hero_image",
        "signature_display",
        "category_ia",
        "set_meal_surface",
        "rating_zone",
    }
    assert result["sales_impact"]["primary_metric"] in {"ctr", "cvr"}
    assert result["priority_actions"]
    assert result["conclusion"]


def test_storefront_action_persists_recommendation() -> None:
    db = _session()
    seeded = seed_demo(db)

    response = create_storefront_action(db, seeded["store_id"], action_index=0, with_ai=False)
    assert response is not None
    assert response.status == "proposed"

    recommendation = db.execute(
        select(Recommendation).where(Recommendation.id == response.recommendation_id)
    ).scalar_one()
    assert recommendation.action_type in {
        "refresh_hero_image",
        "refresh_signature_card",
        "optimize_category_ia",
        "surface_set_meal",
        "reinforce_rating_zone",
    }
    assert "storefront_agent" in (recommendation.content_json or "")

    second = create_storefront_action(db, seeded["store_id"], action_index=0, with_ai=False)
    assert second is not None
    assert second.recommendation_id == response.recommendation_id
