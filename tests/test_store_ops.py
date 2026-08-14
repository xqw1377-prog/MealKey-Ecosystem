"""门店线下动作：派单、证据门禁、催办、回看。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.business_facts import OpsMetricDaily
from app.services.ai_assist import build_setup_checklist
from app.services.closed_loop import mark_loop_executed, tick_observing_loops
from app.services.operating_demands.handler import handle_demand_intent
from app.services.store_ops import (
    attach_evidence,
    has_evidence,
    is_human_task,
    load_roster,
    nag_overdue_human_tasks,
    save_roster,
    store_id_for_token,
    verify_ops_result,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_setup_checklist_includes_store_ops() -> None:
    db = _session()
    seeded = seed_demo(db)
    from app.models.entities import Store

    store = db.get(Store, seeded["store_id"])
    checklist = build_setup_checklist(db, store)
    keys = [step["key"] for step in checklist["steps"]]
    assert "store_ops" in keys
    step = next(item for item in checklist["steps"] if item["key"] == "store_ops")
    assert step["done"] is False
    save_roster(db, store.id, {"manager_name": "李姐"})
    checklist = build_setup_checklist(db, store)
    step = next(item for item in checklist["steps"] if item["key"] == "store_ops")
    assert step["done"] is True
    roster = load_roster(db, store.id)
    assert roster["task_token"]
    assert store_id_for_token(db, roster["task_token"]) == store.id


def test_human_task_cannot_complete_without_evidence() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    save_roster(db, store_id, {"manager_name": "李姐"})
    result = handle_demand_intent(db, store_id, "为什么最近出餐越来越慢？")
    assert result is not None
    assert result["demand"]["code"] == "SLOW_COOK"
    loop_id = result["loop_id"]
    assert loop_id
    from app.models.closed_loop import ClosedLoopItem

    item = db.get(ClosedLoopItem, loop_id)
    assert is_human_task(item)
    assert item.assignee_name == "李姐"
    assert has_evidence(item) is False
    with pytest.raises(ValueError, match="没有证据"):
        mark_loop_executed(db, store_id, loop_id)
    attach_evidence(db, store_id, loop_id, note="午班已加一人盯出餐口")
    marked = mark_loop_executed(db, store_id, loop_id)
    assert marked.status == "observing"
    assert marked.executor == "STORE"


def test_rectify_question_nags_missing_evidence() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    save_roster(db, store_id, {"manager_name": "李姐"})
    first = handle_demand_intent(db, store_id, "为什么漏餐错餐频繁发生？")
    assert first and first["loop_id"]
    from app.models.closed_loop import ClosedLoopItem

    item = db.get(ClosedLoopItem, first["loop_id"])
    item.due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    nag = nag_overdue_human_tasks(db, store_id)
    assert first["loop_id"] in nag["nagged"]
    hit = handle_demand_intent(db, store_id, "昨天让门店整改的事做没做，有没有证据？")
    assert hit is not None
    assert hit["demand"]["code"] == "RECTIFY_EVIDENCE"
    assert "证据" in hit["demand"]["diagnosis"] or "证据" in hit["answer"]


def test_ops_metric_verify_after_evidence() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    save_roster(db, store_id, {"manager_name": "李姐"})
    result = handle_demand_intent(db, store_id, "为什么商责取消突然变高？")
    loop_id = result["loop_id"]
    attach_evidence(db, store_id, loop_id, note="缺料已补，取消单已停")
    marked = mark_loop_executed(db, store_id, loop_id)
    today = datetime.now(timezone.utc).date()
    for offset, rate in ((-3, 0.12), (0, 0.04)):
        db.add(
            OpsMetricDaily(
                store_id=store_id,
                day=today + timedelta(days=offset),
                merchant_cancel_rate=rate,
            )
        )
    db.commit()
    verdict, summary, lift = verify_ops_result(db, marked)
    assert verdict in {"positive", "neutral", "unknown"}
    assert "取消" in summary or "merchant_cancel" in summary or "证据" in summary


def test_tick_observing_human_task_uses_ops_verify() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    save_roster(db, store_id, {"manager_name": "李姐"})
    result = handle_demand_intent(db, store_id, "为什么最近包装洒漏很多？")
    loop_id = result["loop_id"]
    attach_evidence(db, store_id, loop_id, kind="photo", note="已换防漏袋，附打包照")
    marked = mark_loop_executed(db, store_id, loop_id)
    marked.observe_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    tick = tick_observing_loops(db)
    assert loop_id in tick["ready"]
    from app.models.closed_loop import ClosedLoopItem

    item = db.get(ClosedLoopItem, loop_id)
    assert item.status == "result_ready"
