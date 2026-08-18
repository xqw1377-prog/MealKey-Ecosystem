from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.ohre import Recommendation
from app.services.agents import build_single_agent, create_product_action
from truth_fixtures import seed_reconciled_authorized_session_funnel


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_product_agent_builds_health_root_cause_and_decision_path() -> None:
    db = _session()
    seeded = seed_demo(db)
    # seed_demo funnel 是 synthetic → 被 production_funnel_clause 过滤；product agent 需要 observed funnel，
    # 补 authorized_session provenance 才能看见 ctr 下滑（Option B / Truth Contract）。
    seed_reconciled_authorized_session_funnel(db, seeded["store_id"], seeded["item_id"])

    result = build_single_agent(db, seeded["store_id"], "product")

    assert result is not None
    assert result["focus_item_id"]
    assert 20 <= result["health_score"] <= 98
    assert {row["key"] for row in result["health_dimensions"]} == {"sales", "exposure", "ctr", "cvr"}
    assert result["diagnosis_stage"] == "ctr"
    assert result["decision_path"]
    assert result["root_causes"]
    assert result["item_candidates"][0]["recommended_action"]
    assert result["recommendations"][0]["expected_metric"] == "ctr"
    assert result["recommendations"][0]["generated_content"]["visual_brief"]


def test_product_action_creation_persists_auditable_recommendation() -> None:
    db = _session()
    seeded = seed_demo(db)

    response = create_product_action(db, seeded["store_id"], suggestion_index=0)

    assert response is not None
    assert response.status == "proposed"
    recommendation = db.execute(
        select(Recommendation).where(Recommendation.id == response.recommendation_id)
    ).scalar_one()
    assert recommendation.scope == "item"
    assert recommendation.object_ref == f"item:{response.item_id}"
    assert recommendation.action_type == "change_main_image"
    assert recommendation.expected_metric == "ctr"
    assert recommendation.rollback_rule
    assert "product_health_score" in (recommendation.content_json or "")


def test_product_action_creation_is_idempotent_for_duplicate_active_action() -> None:
    db = _session()
    seeded = seed_demo(db)
    first = create_product_action(db, seeded["store_id"], suggestion_index=0)

    assert first is not None
    second = create_product_action(db, seeded["store_id"], suggestion_index=0, item_id=first.item_id)
    assert second is not None
    assert second.recommendation_id == first.recommendation_id
    matches = db.execute(
        select(Recommendation).where(
            Recommendation.store_id == seeded["store_id"],
            Recommendation.object_ref == f"item:{first.item_id}",
            Recommendation.action_type == "change_main_image",
        )
    ).scalars().all()
    assert len(matches) == 1
