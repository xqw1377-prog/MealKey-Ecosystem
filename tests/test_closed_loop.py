import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.closed_loop import ClosedLoopItem
from app.models.thread import OperatingThread
from app.models.entities import Merchant, Store
from app.models.ohre import Experiment, Recommendation
from app.models.runtime_v1 import BusinessEventRecord, SignalRecord
from app.services.closed_loop import (
    apply_loop_to_workspace,
    ensure_now_loop,
    mark_loop_acked,
    mark_loop_executed,
    mark_loop_not_executed,
    project_loop,
    tick_observing_loops,
)
from app.services.execution_pack import build_execution_pack
from app.services.store_ops import attach_evidence
from app.services.loop_ingest import ingest_operating_text


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session) -> Store:
    merchant = Merchant(name="测试商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="老王牛肉饭")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def _now_flow() -> dict:
    pack = build_execution_pack("change_main_image", object_name="黑椒牛肉饭", title="先换主图")
    return {
        "now": {
            "id": "nba-1",
            "source_card_id": "nba-1",
            "title": "先换黑椒牛肉饭主图",
            "why_now": "点击率连续下滑，份量感弱",
            "ai_already_did": "主图主体太小，份量看不清",
            "business_impact": "预计今天少几单",
            "execution_pack": pack,
        }
    }


def _payload() -> dict:
    return {
        "left": {
            "need_you": [
                {"id": "nba-1", "title": "先换主图"},
                {"id": "ev-ctr", "title": "点击率下降", "related_now_id": "nba-1"},
            ],
            "active": [{"id": "nba-1", "title": "先换主图"}],
            "waiting": [],
        },
        "center": {
            "guide": {"id": "nba-1", "type": "APPROVAL", "title": "先换主图"},
            "decision_flow": _now_flow(),
        },
        "right": {
            "proactive_feed": [{"id": "ev-ctr", "summary": "点击率下降"}],
        },
    }


def test_three_columns_share_the_same_loop_id() -> None:
    item = ClosedLoopItem(
        id="loop-1",
        store_id="s1",
        fingerprint="s1:nba-1",
        source_card_id="nba-1",
        source_event_id="ev-ctr",
        title="黑椒牛肉饭差评整改",
        finding="我已经把 7 条差评归因完了，其中 5 条集中在肉少。",
        judgment="回复稿已经准备好，要直接使用吗？",
        action_type="batch_reply_negative_reviews",
        status="now",
        pack_json="{}",
    )
    projected = project_loop(item)
    assert projected["id"] == projected["left"]["id"] == projected["center"]["id"] == projected["right"]["id"]
    workspace = apply_loop_to_workspace(_payload(), item)
    loop_id = workspace["center"]["loop"]["id"]
    assert workspace["center"]["guide"]["id"] == loop_id
    assert workspace["center"]["decision_flow"]["now"]["id"] == loop_id
    assert workspace["center"]["guide"]["work_thread_id"] == loop_id
    assert workspace["center"]["decision_flow"]["now"]["work_thread_id"] == loop_id
    assert workspace["left"]["need_you"][0]["id"] == loop_id
    assert workspace["left"]["need_you"][0]["work_thread_id"] == loop_id
    assert workspace["right"]["proactive_feed"][0]["id"] == loop_id
    assert workspace["right"]["proactive_feed"][0]["work_thread_id"] == loop_id
    left_ids = [item["id"] for item in workspace["left"]["need_you"]]
    assert left_ids.count(loop_id) == 1
    assert "nba-1" not in left_ids
    assert "ev-ctr" not in left_ids


def test_executing_thread_projects_to_active_bucket() -> None:
    pack = {
        "thread_status": "EXECUTING",
        "thread_history": [
            {"state": "NEED_APPROVAL", "at": "2026-01-01T00:00:00+00:00"},
            {"state": "APPROVED", "at": "2026-01-01T00:05:00+00:00"},
            {"state": "EXECUTING", "at": "2026-01-01T00:06:00+00:00"},
        ],
    }
    item = ClosedLoopItem(
        id="loop-exec",
        store_id="s1",
        fingerprint="s1:nba-2",
        source_card_id="nba-2",
        source_event_id="ev-2",
        title="黑椒牛肉饭改标题",
        finding="标题已经确认，准备执行。",
        judgment="正在把动作写回平台。",
        action_type="change_title",
        status="now",
        pack_json=json.dumps(pack, ensure_ascii=False),
    )
    projected = project_loop(item)
    assert projected["thread_status"] == "EXECUTING"
    assert projected["left"]["slot"] == "active"
    assert projected["center"]["type"] == "PROGRESS"
    workspace = apply_loop_to_workspace(_payload(), item)
    assert workspace["left"]["active"][0]["id"] == "loop-exec"
    assert workspace["left"]["need_you"][0]["id"] != "loop-exec"


def test_mark_executed_enters_observation_window() -> None:
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    assert item is not None
    assert item.status == "now"
    marked = mark_loop_executed(db, store.id, item.id)
    assert marked.status == "observing"
    assert marked.executed_at is not None
    assert marked.observe_until is not None
    assert marked.observe_until >= marked.executed_at + timedelta(hours=47)
    assert marked.experiment_id
    assert marked.recommendation_id
    rec = db.get(Recommendation, marked.recommendation_id)
    exp = db.get(Experiment, marked.experiment_id)
    assert rec is not None and rec.status == "executed"
    assert exp is not None and exp.result == "pending"
    assert rec.work_thread_id == marked.id
    assert exp.work_thread_id == marked.id
    projected = project_loop(marked)
    assert projected["waiting"] is True
    assert projected["work_thread_id"] == marked.id
    assert projected["thread_status"] == "OBSERVING"
    assert projected["thread_stage"] == "OBSERVING"
    assert projected["action_spec"]["type"] == "CHANGE_PRODUCT_IMAGE"
    assert [row["state"] for row in projected["thread_history"]] == [
        "NEED_APPROVAL",
        "APPROVED",
        "EXECUTING",
        "OBSERVING",
    ]
    workspace = apply_loop_to_workspace(_payload(), marked)
    waiting_ids = [row["id"] for row in workspace["left"]["waiting"]]
    need_ids = [row["id"] for row in workspace["left"]["need_you"]]
    assert marked.id in waiting_ids
    assert marked.id not in need_ids


def test_not_executed_does_not_open_observation() -> None:
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    skipped = mark_loop_not_executed(db, store.id, item.id)
    assert skipped.status == "not_executed"
    assert skipped.observe_until is None
    assert skipped.executed_at is None
    assert skipped.experiment_id is None
    projected = project_loop(skipped)
    assert projected["waiting"] is False
    assert projected["thread_status"] == "CANCELLED"
    assert projected["thread_history"][-1]["state"] == "CANCELLED"


def test_not_executed_reopens_when_same_now_returns() -> None:
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    mark_loop_not_executed(db, store.id, item.id)
    again = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    assert again.id == item.id
    assert again.status == "now"


def test_observing_blocks_a_new_now() -> None:
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    mark_loop_executed(db, store.id, item.id)
    other = {
        "now": {
            "id": "nba-2",
            "source_card_id": "nba-2",
            "title": "加投流冲排名",
            "why_now": "想加预算",
            "execution_pack": build_execution_pack("ops_hint", title="加投流冲排名"),
        }
    }
    still = ensure_now_loop(db, store.id, decision_flow=other, events=None)
    assert still.id == item.id
    assert still.status == "observing"


def test_tick_moves_due_loop_to_result_ready() -> None:
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    marked = mark_loop_executed(db, store.id, item.id)
    marked.observe_until = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    result = tick_observing_loops(db)
    assert marked.id in result["ready"]
    db.refresh(marked)
    assert marked.status == "result_ready"
    projected = project_loop(marked)
    assert projected["result_ready"] is True
    assert projected["waiting"] is False
    assert projected["thread_status"] == "WAITING_RESULT"
    assert projected["thread_history"][-1]["state"] == "WAITING_RESULT"
    workspace = apply_loop_to_workspace(_payload(), marked)
    assert workspace["left"]["need_you"][0]["id"] == marked.id
    assert workspace["left"]["need_you"][0]["meta"] == "结果出来了"
    acked = mark_loop_acked(db, store.id, marked.id)
    assert acked.status == "closed"
    closed = project_loop(acked)
    assert closed["thread_status"] == "COMPLETED"
    assert closed["thread_history"][-1]["state"] == "COMPLETED"
    nxt = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    assert nxt.id != marked.id
    assert nxt.status == "now"


def test_csv_text_becomes_a_now_loop() -> None:
    db = _session()
    store = _store(db)
    text = "商品,点击率\n黑椒牛肉饭,3.2%\n黑椒牛肉饭点击率较昨天下降 15%"
    item = ingest_operating_text(db, store.id, text, filename="funnel.csv")
    assert item is not None
    assert item.status == "now"
    assert item.action_type == "change_main_image"
    assert item.source_card_id.startswith("ingest:")
    assert db.get(SignalRecord, item.source_card_id.split(":", 1)[1]) is not None
    assert db.get(BusinessEventRecord, item.source_event_id) is not None
    current = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    assert current.id == item.id


def test_now_loop_creates_same_work_thread_identity() -> None:
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    assert item is not None
    thread = db.get(OperatingThread, item.id)
    assert thread is not None
    assert thread.id == item.id
    assert thread.title == item.title


def test_new_loop_starts_with_need_approval_history() -> None:
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    assert item is not None
    pack = json.loads(item.pack_json or "{}")
    assert pack["thread_status"] == "NEED_APPROVAL"
    assert [row["state"] for row in pack["thread_history"]] == ["NEED_APPROVAL"]


def test_review_text_becomes_reply_loop() -> None:
    db = _session()
    store = _store(db)
    item = ingest_operating_text(db, store.id, "黑椒牛肉饭差评突然增加，7条里5条说肉少")
    assert item is not None
    assert item.action_type == "batch_reply_negative_reviews"
    assert "差评" in item.title


def test_ordinary_review_text_becomes_reply_loop() -> None:
    db = _session()
    store = _store(db)
    item = ingest_operating_text(db, store.id, "店铺好评未回 12 条，都是 4 星以上")
    assert item is not None
    assert item.action_type == "reply_ordinary_reviews"
    assert "好评" in item.title


def test_execution_pack_copy_is_human() -> None:
    pack = build_execution_pack("change_title", object_name="黑椒牛肉饭")
    blob = f"{pack['copy_text']} {pack['goal']} {pack['guardrail']}"
    assert "CTR" not in blob
    assert "baseline_window" not in blob
    assert pack["observe_hours"] == 48
    assert pack["success_metric"]
    assert pack["guardrail"]


def test_evidence_updates_work_thread_progress() -> None:
    db = _session()
    store = _store(db)
    pack = build_execution_pack("appeal_pack", object_name="当前店铺", title="恶意评价申诉")
    flow = {
        "now": {
            "id": "appeal-1",
            "source_card_id": "appeal-1",
            "title": "恶意评价申诉",
            "why_now": "这条评价疑似不实",
            "execution_pack": pack,
        }
    }
    item = ensure_now_loop(db, store.id, decision_flow=flow, events=None)
    assert item is not None
    attach_evidence(db, store.id, item.id, note="已补订单记录和聊天截图")
    thread = db.get(OperatingThread, item.id)
    assert thread is not None
    assert "已补 1 份证据" in (thread.current_result or "")
    assert thread.needs_owner is True


def test_appeal_result_ready_keeps_ticket_summary_in_thread() -> None:
    db = _session()
    store = _store(db)
    pack = build_execution_pack("appeal_pack", object_name="当前店铺", title="恶意评价申诉")
    assert pack is not None
    pack["writeback"] = {
        "ok": True,
        "op": "submit_review_appeal",
        "ticket_id": "appeal:demo:1",
        "evidence_count": 2,
        "summary": "已提交评价申诉并读回工单号 appeal:demo:1。",
    }
    item = ClosedLoopItem(
        id="loop-appeal",
        store_id=store.id,
        fingerprint="appeal",
        source_card_id="appeal-card",
        title="恶意评价申诉",
        finding="疑似不实评价",
        judgment="申诉已提交",
        action_type="appeal_pack",
        status="observing",
        pack_json=json.dumps(pack, ensure_ascii=False),
        executor="PLATFORM",
        observe_hours=48,
        observe_until=datetime.now(timezone.utc) - timedelta(hours=1),
        result="pending",
    )
    db.add(item)
    db.commit()
    tick_observing_loops(db)
    db.refresh(item)
    assert item.status == "result_ready"
    assert "工单" in (item.notes or "")
    thread = db.get(OperatingThread, item.id)
    assert thread is not None
    assert "工单" in (thread.current_result or "")
    assert thread.needs_owner is True
