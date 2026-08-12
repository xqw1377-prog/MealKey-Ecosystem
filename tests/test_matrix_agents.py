from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.ohre import Recommendation
from app.services.agents import build_single_agent, build_store_agents, create_matrix_agent_action


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


MATRIX_KEYS = ("promo", "ads", "crm", "service", "review", "store_matrix")


def test_matrix_agents_build_in_store_bundle() -> None:
    db = _session()
    seeded = seed_demo(db)

    payload = build_store_agents(db, seeded["store_id"])
    assert payload is not None
    for key in MATRIX_KEYS:
        agent = getattr(payload, key)
        assert agent.meta.key == key
        assert agent.conclusion
        assert 20 <= agent.health_score <= 98
        assert isinstance(agent.priority_actions, list)


def test_each_matrix_agent_via_build_single() -> None:
    db = _session()
    seeded = seed_demo(db)

    for key in MATRIX_KEYS:
        result = build_single_agent(db, seeded["store_id"], key)
        assert result is not None
        assert result["meta"]["key"] == key
        assert result["conclusion"]


def test_matrix_agent_action_persists_recommendation() -> None:
    db = _session()
    seeded = seed_demo(db)

    # Prefer an agent that always produces at least one action in V1 heuristics
    for key in ("crm", "service", "review", "promo", "ads", "store_matrix"):
        agent = build_single_agent(db, seeded["store_id"], key)
        assert agent is not None
        if not agent.get("priority_actions"):
            continue
        response = create_matrix_agent_action(db, seeded["store_id"], key, action_index=0)
        assert response is not None
        assert response.agent_key == key
        assert response.status == "proposed"

        recommendation = db.execute(
            select(Recommendation).where(Recommendation.id == response.recommendation_id)
        ).scalar_one()
        assert f"{key}_agent" in (recommendation.content_json or "")

        second = create_matrix_agent_action(db, seeded["store_id"], key, action_index=0)
        assert second is not None
        assert second.recommendation_id == response.recommendation_id
        return

    raise AssertionError("no matrix agent produced priority_actions")


def test_growth_pool_can_include_matrix_sources() -> None:
    db = _session()
    seeded = seed_demo(db)
    payload = build_store_agents(db, seeded["store_id"])
    assert payload is not None
    sources = {row.source_agent for row in payload.growth.opportunity_pool}
    # At least one specialist source or classic sources should appear
    assert sources
    assert sources & {
        "competition",
        "menu",
        "product",
        "diagnosis",
        "storefront",
        "promo",
        "ads",
        "crm",
        "service",
        "review",
        "store_matrix",
    }
