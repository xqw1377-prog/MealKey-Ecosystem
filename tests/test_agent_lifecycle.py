from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.ohre import Experiment, Recommendation
from app.schemas.agents import AgentWorkflowItem, GrowthOpportunityView, GrowthScoreFactors, ProductSuggestion
from app.services.action_feedback import find_recent_action_feedback
from app.services.agents import (
    ACTION_HISTORY_DAYS,
    _build_competition_agent,
    _build_context,
    _build_diagnosis_agent,
    _build_growth_agent,
    _build_menu_agent,
    _build_product_agent,
    _build_storefront_agent,
    _growth_sync_queue_with_selection,
    _product_sync_queue_with_suggestions,
    _workflow_phase,
    build_single_agent,
    create_matrix_agent_action,
    create_product_action,
    create_storefront_action,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _make_recommendation(
    db: Session,
    *,
    store_id: str,
    action_type: str,
    status: str,
    expected_metric: str = "orders",
    object_ref: str | None = None,
    created_at: datetime | None = None,
    adopted_at: datetime | None = None,
    executed_at: datetime | None = None,
    confidence: float = 0.7,
    expected_lift_low: float = 1.0,
    expected_lift_high: float = 6.0,
    source: str = "service_agent",
    title: str | None = None,
) -> Recommendation:
    rec = Recommendation(
        store_id=store_id,
        scope="store" if (object_ref or f"store:{store_id}").startswith("store:") else "item",
        object_ref=object_ref or f"store:{store_id}",
        action_type=action_type,
        expected_metric=expected_metric,
        expected_lift_pct_low=expected_lift_low,
        expected_lift_pct_high=expected_lift_high,
        window_hours=24,
        confidence=confidence,
        status=status,
        content_json=json.dumps(
            {
                "source": source,
                "title": title or action_type,
                "object_name": "门店整体",
                "evidence": [f"evidence:{action_type}"],
            },
            ensure_ascii=False,
        ),
        evidence_json=json.dumps([f"evidence:{action_type}"], ensure_ascii=False),
        created_at=created_at or datetime.now(timezone.utc),
        adopted_at=adopted_at,
        executed_at=executed_at,
    )
    db.add(rec)
    db.flush()
    return rec


def _make_experiment(
    db: Session,
    *,
    recommendation_id: str,
    store_id: str,
    result: str,
    lift_pct: float = 0.0,
) -> Experiment:
    exp = Experiment(
        recommendation_id=recommendation_id,
        store_id=store_id,
        result=result,
        lift_pct=lift_pct,
    )
    db.add(exp)
    db.flush()
    return exp


def test_context_filters_recommendations_outside_21_day_window() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    now = datetime.now(timezone.utc)

    old_rec = _make_recommendation(
        db,
        store_id=store_id,
        action_type="batch_reply_negative_reviews",
        status="proposed",
        created_at=now - timedelta(days=ACTION_HISTORY_DAYS + 2),
    )
    recent_rec = _make_recommendation(
        db,
        store_id=store_id,
        action_type="publish_service_reply_scripts",
        status="proposed",
        created_at=now - timedelta(days=ACTION_HISTORY_DAYS - 2),
    )
    db.commit()

    ctx = _build_context(db, store_id, 7)
    assert ctx is not None
    ids = {rec.id for rec in ctx.recommendations}
    assert recent_rec.id in ids
    assert old_rec.id not in ids


def test_workflow_phase_covers_execute_observe_and_review() -> None:
    now = datetime.now(timezone.utc)
    rec = Recommendation(
        store_id="store-1",
        scope="store",
        object_ref="store:store-1",
        action_type="change_main_image",
        expected_metric="ctr",
        window_hours=24,
        confidence=0.7,
        status="proposed",
    )
    phase, _ = _workflow_phase(rec, None)
    assert phase == "execute_now"

    rec.status = "executed"
    rec.executed_at = now - timedelta(hours=2)
    phase, _ = _workflow_phase(rec, None)
    assert phase == "observe"

    exp = Experiment(recommendation_id="rec-1", store_id="store-1", result="positive", lift_pct=5.0)
    phase, _ = _workflow_phase(rec, exp)
    assert phase == "review"


def test_product_sync_marks_discount_backup_as_deferred() -> None:
    db = _session()
    seeded = seed_demo(db)
    ctx = _build_context(db, seeded["store_id"], 7)
    assert ctx is not None
    item = ctx.item_snapshots[0]

    queue = [
        AgentWorkflowItem(
            recommendation_id="discount-1",
            title="只在必要时做门店折扣测试",
            action_type="store_discount",
            object_ref=f"item:{item.item_id}",
            object_name=item.name,
            status="proposed",
            execution_phase="execute_now",
            expected_metric="orders",
            window_hours=24,
            confidence=0.7,
        )
    ]
    suggestions = [
        ProductSuggestion(
            type="visual",
            title="先换主图",
            detail="先用低风险主图动作验证 CTR。",
            action_type="change_main_image",
            expected_metric="ctr",
            expected_lift_pct_low=2,
            expected_lift_pct_high=8,
            window_hours=24,
            risk_level="low",
            rollback_rule="24h CTR 无改善则回退。",
        )
    ]

    synced_queue, current_action = _product_sync_queue_with_suggestions(item, queue, suggestions)
    assert synced_queue[0].execution_phase == "deferred"
    assert current_action is not None
    assert current_action.execution_phase == "execute_now"
    assert current_action.action_type == "change_main_image"


def test_growth_sync_marks_discount_backup_as_deferred() -> None:
    db = _session()
    seeded = seed_demo(db)
    ctx = _build_context(db, seeded["store_id"], 7)
    assert ctx is not None

    queue = [
        AgentWorkflowItem(
            recommendation_id="discount-1",
            title="只在必要时做门店折扣测试",
            action_type="store_discount",
            object_ref=f"store:{seeded['store_id']}",
            object_name="门店整体",
            status="proposed",
            execution_phase="execute_now",
            expected_metric="orders",
            window_hours=24,
            confidence=0.7,
        )
    ]
    selected = GrowthOpportunityView(
        key="product:hero",
        source_agent="product",
        title="先换主图，抢回第一眼点击",
        problem="CTR 下降",
        action_type="change_main_image",
        object_name="招牌牛肉饭",
        expected_metric="ctr",
        expected_lift_pct_low=2,
        expected_lift_pct_high=8,
        score=82,
        factors=GrowthScoreFactors(
            expected_impact=4.5,
            confidence=4.2,
            ease_of_execution=4.8,
            strategic_fit=4.4,
            risk=1.2,
        ),
        evidence=["CTR 连续下滑"],
        recommendation_id=None,
        status="candidate",
        executable=True,
    )

    synced_queue, current_action = _growth_sync_queue_with_selection(ctx, queue, selected)
    assert synced_queue[0].execution_phase == "deferred"
    assert current_action is not None
    assert current_action.execution_phase == "execute_now"
    assert current_action.action_type == "change_main_image"


def test_product_action_reuses_active_duplicate_even_if_newer_archived_exists() -> None:
    db = _session()
    seeded = seed_demo(db)
    initial = create_product_action(db, seeded["store_id"], suggestion_index=0)
    assert initial is not None

    archived = _make_recommendation(
        db,
        store_id=seeded["store_id"],
        action_type="change_main_image",
        status="archived",
        object_ref=f"item:{initial.item_id}",
        created_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        source="product_agent",
        title="archived copy",
    )
    db.commit()

    second = create_product_action(db, seeded["store_id"], suggestion_index=0, item_id=initial.item_id)
    assert second is not None
    assert second.recommendation_id == initial.recommendation_id
    assert second.recommendation_id != archived.id


def test_diagnosis_current_action_uses_full_queue_before_display_slice() -> None:
    db = _session()
    seeded = seed_demo(db)
    ctx = _build_context(db, seeded["store_id"], 7)
    assert ctx is not None
    ctx.document_alignment = {"status": "ready", "summary": "facts aligned"}

    now = datetime.now(timezone.utc)
    observe_recs = [
        _make_recommendation(
            db,
            store_id=seeded["store_id"],
            action_type=f"observe_action_{idx}",
            status="executed",
            expected_metric="orders",
            confidence=0.95 - idx * 0.05,
            expected_lift_high=12 - idx,
            executed_at=now - timedelta(hours=idx + 1),
            source="service_agent",
            title=f"observe-{idx}",
        )
        for idx in range(4)
    ]
    review_rec = _make_recommendation(
        db,
        store_id=seeded["store_id"],
        action_type="review_target",
        status="executed",
        expected_metric="orders",
        confidence=0.25,
        expected_lift_high=1,
        executed_at=now - timedelta(hours=6),
        source="service_agent",
        title="review-target",
    )
    review_exp = _make_experiment(
        db,
        recommendation_id=review_rec.id,
        store_id=seeded["store_id"],
        result="positive",
        lift_pct=4.0,
    )
    db.commit()

    ctx.recommendations = [*observe_recs, review_rec]
    ctx.experiments = [review_exp]
    diagnosis = _build_diagnosis_agent(db, ctx)

    assert diagnosis.current_action is not None
    assert diagnosis.current_action.recommendation_id == review_rec.id
    assert diagnosis.current_action.execution_phase == "review"


def test_growth_current_action_uses_full_queue_before_display_slice() -> None:
    db = _session()
    seeded = seed_demo(db)
    ctx = _build_context(db, seeded["store_id"], 7)
    assert ctx is not None
    ctx.document_alignment = {"status": "ready", "summary": "facts aligned"}

    now = datetime.now(timezone.utc)
    observe_recs = [
        _make_recommendation(
            db,
            store_id=seeded["store_id"],
            action_type=f"observe_growth_{idx}",
            status="executed",
            expected_metric="orders",
            confidence=0.92 - idx * 0.05,
            expected_lift_high=12 - idx,
            executed_at=now - timedelta(hours=idx + 1),
            source="service_agent",
            title=f"growth-observe-{idx}",
        )
        for idx in range(4)
    ]
    review_rec = _make_recommendation(
        db,
        store_id=seeded["store_id"],
        action_type="growth_review_target",
        status="executed",
        expected_metric="orders",
        confidence=0.2,
        expected_lift_high=1,
        executed_at=now - timedelta(hours=6),
        source="service_agent",
        title="growth-review-target",
    )
    review_exp = _make_experiment(
        db,
        recommendation_id=review_rec.id,
        store_id=seeded["store_id"],
        result="positive",
        lift_pct=4.0,
    )
    db.commit()

    ctx.recommendations = [*observe_recs, review_rec]
    ctx.experiments = [review_exp]

    competition = _build_competition_agent(db, ctx)
    menu = _build_menu_agent(ctx)
    product = _build_product_agent(ctx)
    diagnosis = _build_diagnosis_agent(db, ctx)
    growth = _build_growth_agent(ctx, competition, menu, product, diagnosis)

    assert growth.current_action is not None
    assert growth.current_action.recommendation_id == review_rec.id
    assert growth.current_action.execution_phase == "review"


def test_storefront_queue_and_action_responses_expose_lifecycle_fields() -> None:
    db = _session()
    seeded = seed_demo(db)

    storefront_created = create_storefront_action(db, seeded["store_id"], action_index=0, with_ai=False)
    assert storefront_created is not None
    assert storefront_created.review_note
    assert storefront_created.observe_focus
    assert storefront_created.next_decision
    assert storefront_created.experiment_id is None

    product_created = create_product_action(db, seeded["store_id"], suggestion_index=0)
    assert product_created is not None
    assert product_created.review_note
    assert product_created.observe_focus
    assert product_created.next_decision
    assert product_created.experiment_id is None

    for key in ("crm", "service", "review", "promo", "ads", "store_matrix"):
        agent_payload = build_single_agent(db, seeded["store_id"], key)
        assert agent_payload is not None
        if not agent_payload.get("priority_actions"):
            continue
        agent = create_matrix_agent_action(db, seeded["store_id"], key, action_index=0)
        assert agent is not None
        assert agent.review_note
        assert agent.observe_focus
        assert agent.next_decision
        assert agent.experiment_id is None
        break
    else:
        raise AssertionError("no matrix action available for lifecycle contract check")


def test_storefront_current_action_can_enter_review_phase() -> None:
    db = _session()
    seeded = seed_demo(db)
    ctx = _build_context(db, seeded["store_id"], 7)
    assert ctx is not None
    ctx.document_alignment = {"status": "ready", "summary": "facts aligned"}

    rec = _make_recommendation(
        db,
        store_id=seeded["store_id"],
        action_type="refresh_hero_image",
        status="executed",
        expected_metric="ctr",
        source="storefront_agent",
        title="refresh hero",
        executed_at=datetime.now(timezone.utc) - timedelta(hours=6),
    )
    exp = _make_experiment(
        db,
        recommendation_id=rec.id,
        store_id=seeded["store_id"],
        result="positive",
        lift_pct=5.0,
    )
    db.commit()

    ctx.recommendations = [rec]
    ctx.experiments = [exp]
    storefront = _build_storefront_agent(db, ctx)

    assert storefront.current_action is not None
    assert storefront.current_action.recommendation_id == rec.id
    assert storefront.current_action.execution_phase == "review"


def test_product_recommendations_downrank_recent_negative_feedback() -> None:
    db = _session()
    seeded = seed_demo(db)
    ctx = _build_context(db, seeded["store_id"], 7)
    assert ctx is not None
    item = ctx.item_snapshots[0]

    rec = _make_recommendation(
        db,
        store_id=seeded["store_id"],
        action_type="change_main_image",
        status="executed",
        expected_metric="ctr",
        object_ref=f"item:{item.item_id}",
        source="product_agent",
        title="negative main image",
        executed_at=datetime.now(timezone.utc) - timedelta(hours=8),
    )
    _make_experiment(
        db,
        recommendation_id=rec.id,
        store_id=seeded["store_id"],
        result="negative",
        lift_pct=-4.0,
    )
    db.commit()

    refreshed = _build_context(db, seeded["store_id"], 7)
    assert refreshed is not None
    product = _build_product_agent(refreshed, focus_item_id=item.item_id)

    assert [row.action_type for row in product.recommendations[:2]] == ["change_title", "change_main_image"]
    assert product.recommendations[1].generated_content["feedback_result"] == "negative"


def test_storefront_priority_actions_boost_recent_positive_feedback() -> None:
    db = _session()
    seeded = seed_demo(db)
    ctx = _build_context(db, seeded["store_id"], 7)
    assert ctx is not None

    baseline = _build_storefront_agent(db, ctx)
    assert len(baseline.priority_actions) >= 2
    promoted = baseline.priority_actions[1]

    rec = _make_recommendation(
        db,
        store_id=seeded["store_id"],
        action_type=promoted.action_type,
        status="executed",
        expected_metric=promoted.expected_metric,
        object_ref=promoted.object_ref,
        source="storefront_agent",
        title=promoted.title,
        executed_at=datetime.now(timezone.utc) - timedelta(hours=10),
    )
    _make_experiment(
        db,
        recommendation_id=rec.id,
        store_id=seeded["store_id"],
        result="positive",
        lift_pct=6.5,
    )
    db.commit()

    refreshed = _build_context(db, seeded["store_id"], 7)
    assert refreshed is not None
    storefront = _build_storefront_agent(db, refreshed)

    assert storefront.priority_actions[0].action_type == promoted.action_type
    assert storefront.priority_actions[0].generated_content["feedback_result"] == "positive"


def test_matrix_priority_actions_downrank_pending_feedback() -> None:
    db = _session()
    seeded = seed_demo(db)

    initial = build_single_agent(db, seeded["store_id"], "promo")
    assert initial is not None
    assert len(initial["priority_actions"]) >= 2
    pending_action = initial["priority_actions"][0]
    fallback_action = initial["priority_actions"][1]

    rec = _make_recommendation(
        db,
        store_id=seeded["store_id"],
        action_type=pending_action["action_type"],
        status="executed",
        expected_metric=pending_action["expected_metric"],
        object_ref=pending_action["object_ref"],
        source="promo_agent",
        title=pending_action["title"],
        executed_at=datetime.now(timezone.utc) - timedelta(hours=6),
    )
    _make_experiment(
        db,
        recommendation_id=rec.id,
        store_id=seeded["store_id"],
        result="pending",
        lift_pct=0.0,
    )
    db.commit()

    updated = build_single_agent(db, seeded["store_id"], "promo")
    assert updated is not None
    assert updated["priority_actions"][0]["action_type"] == fallback_action["action_type"]
    assert updated["priority_actions"][1]["generated_content"]["feedback_result"] == "pending"


def test_recent_action_feedback_marks_neutral_result_as_soft_penalty() -> None:
    db = _session()
    seeded = seed_demo(db)
    ctx = _build_context(db, seeded["store_id"], 7)
    assert ctx is not None
    item = ctx.item_snapshots[0]

    rec = _make_recommendation(
        db,
        store_id=seeded["store_id"],
        action_type="change_title",
        status="executed",
        expected_metric="ctr",
        object_ref=f"item:{item.item_id}",
        source="product_agent",
        title="neutral title test",
        executed_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    exp = _make_experiment(
        db,
        recommendation_id=rec.id,
        store_id=seeded["store_id"],
        result="neutral",
        lift_pct=0.3,
    )

    feedback = find_recent_action_feedback(
        [rec],
        [exp],
        action_type="change_title",
        object_ref=f"item:{item.item_id}",
        source_tag="product_agent",
    )

    assert feedback is not None
    assert feedback.result == "neutral"
    assert feedback.score_delta < 0
