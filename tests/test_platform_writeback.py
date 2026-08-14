from datetime import timedelta
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, Store
from app.models.ohre import Experiment
from app.services.closed_loop import (
    ensure_now_loop,
    execute_loop_platform_writeback,
    mark_loop_executed,
    project_loop,
)
from app.services.execution_pack import build_execution_pack
from app.services.platform_connectors import reset_mock_platform_state
from app.services.platform_write import (
    ReadBackMismatchError,
    WriteFailedError,
    WritePermissionError,
    check_write_permission,
    is_platform_writeable,
    suggested_title_from_pack,
)


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


def _title_flow(name: str = "招牌牛肉盖饭") -> dict:
    pack = build_execution_pack("change_title", object_name=name, title=f"改{name}标题")
    return {
        "now": {
            "id": "nba-title",
            "source_card_id": "nba-title",
            "title": f"改{name}标题",
            "why_now": "标题信息弱，点击率下滑",
            "ai_already_did": "已经写好一版强调份量的标题",
            "business_impact": "预计点击会回来一点",
            "execution_pack": pack,
        }
    }


def _image_flow() -> dict:
    pack = build_execution_pack("change_main_image", object_name="黑椒牛肉饭", title="先换主图")
    return {
        "now": {
            "id": "nba-image",
            "source_card_id": "nba-image",
            "title": "先换黑椒牛肉饭主图",
            "why_now": "点击率连续下滑",
            "ai_already_did": "主图主体太小",
            "execution_pack": pack,
        }
    }


def test_title_and_ordinary_review_are_platform_writeable() -> None:
    assert is_platform_writeable("change_title") is True
    assert is_platform_writeable("reply_ordinary_reviews") is True
    assert is_platform_writeable("change_main_image") is True
    assert is_platform_writeable("appeal_pack") is True
    assert is_platform_writeable("adjust_price_value") is False
    assert is_platform_writeable("batch_reply_negative_reviews") is False
    check_write_permission("change_title", confirmed=True)
    check_write_permission("reply_ordinary_reviews", confirmed=True)
    check_write_permission("appeal_pack", confirmed=True)
    try:
        check_write_permission("adjust_price_value", confirmed=True)
        raise AssertionError("price writeback must be blocked")
    except WritePermissionError:
        pass
    try:
        check_write_permission("batch_reply_negative_reviews", confirmed=True)
        raise AssertionError("negative review writeback must be blocked")
    except WritePermissionError:
        pass
    try:
        check_write_permission("change_title", confirmed=False)
        raise AssertionError("unconfirmed writeback must be blocked")
    except WritePermissionError:
        pass


def test_platform_write_title_enters_observation() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_title_flow(), events=None)
    assert item is not None
    assert item.status == "now"
    projected = project_loop(item)
    assert projected["platform_writeable"] is True

    marked = execute_loop_platform_writeback(db, store.id, item.id)
    assert marked.status == "observing"
    assert marked.executor == "PLATFORM"
    assert marked.executed_at is not None
    assert marked.observe_until is not None
    assert marked.observe_until >= marked.executed_at + timedelta(hours=47)
    assert "读回确认" in (marked.notes or "")
    exp = db.get(Experiment, marked.experiment_id)
    assert exp is not None
    assert exp.executor == "PLATFORM"
    assert exp.result == "pending"
    waiting = project_loop(marked)
    assert waiting["waiting"] is True
    assert waiting["platform_writeable"] is False
    assert waiting["executor"] == "PLATFORM"


def test_platform_write_fail_keeps_loop_in_now(monkeypatch) -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_title_flow(), events=None)
    assert item is not None

    def _boom(*_args, **_kwargs):
        raise ValueError("平台写回接口返回 502")

    monkeypatch.setattr("app.services.platform_write.post_platform_write", _boom)
    try:
        execute_loop_platform_writeback(db, store.id, item.id)
        raise AssertionError("write failure must not mark executed")
    except WriteFailedError:
        pass
    db.refresh(item)
    assert item.status == "now"
    assert item.executed_at is None
    assert item.executor == "OWNER"
    pack = json.loads(item.pack_json or "{}")
    assert pack.get("writeback", {}).get("ok") is False
    assert "502" in str(pack.get("writeback", {}).get("error") or "")


def test_read_back_mismatch_does_not_mark_executed(monkeypatch) -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_title_flow(), events=None)
    assert item is not None
    monkeypatch.setattr("app.services.platform_write.read_back_product_title", lambda *_a, **_k: None)
    try:
        execute_loop_platform_writeback(db, store.id, item.id)
        raise AssertionError("mismatch must not mark executed")
    except ReadBackMismatchError:
        pass
    db.refresh(item)
    assert item.status == "now"
    assert item.experiment_id is None


def test_image_loop_uses_platform_writeback() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_image_flow(), events=None)
    assert item is not None
    assert project_loop(item)["platform_writeable"] is True
    marked = execute_loop_platform_writeback(db, store.id, item.id)
    assert marked.status == "observing"
    assert marked.executor == "PLATFORM"
    assert "主图" in (marked.notes or "")
    exp = db.get(Experiment, marked.experiment_id)
    assert exp is not None
    assert exp.result == "pending"


def test_human_executed_still_works_for_title() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_title_flow(), events=None)
    assert item is not None
    marked = mark_loop_executed(db, store.id, item.id)
    assert marked.status == "observing"
    assert marked.executor == "OWNER"


def test_suggested_title_comes_from_pack() -> None:
    pack = build_execution_pack("change_title", object_name="招牌牛肉盖饭", title="改标题")
    assert pack is not None
    assert pack["suggested_title"] == "招牌牛肉盖饭｜现炒·足量热饭"
    assert suggested_title_from_pack(pack, object_name="招牌牛肉盖饭") == pack["suggested_title"]


def test_http_write_then_read_back(monkeypatch) -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_title_flow(), events=None)
    assert item is not None
    new_title = "招牌牛肉盖饭｜现炒·足量热饭"

    monkeypatch.setattr(
        "app.services.platform_write.resolve_connector",
        lambda *_a, **_k: type("T", (), {"platform": "meituan", "mode": "http", "external_store_id": "ext-1"})(),
    )
    monkeypatch.setattr(
        "app.services.platform_write.post_platform_write",
        lambda *_a, **_k: {"ok": True, "external_ref": "sku-1", "applied_title": new_title},
    )
    monkeypatch.setattr(
        "app.services.platform_write.read_back_product_title",
        lambda *_a, **_k: new_title,
    )
    marked = execute_loop_platform_writeback(db, store.id, item.id)
    assert marked.executor == "PLATFORM"
    assert marked.status == "observing"
    assert new_title in (marked.notes or "")


def test_loop_not_in_now_cannot_writeback() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_title_flow(), events=None)
    assert item is not None
    mark_loop_executed(db, store.id, item.id)
    try:
        execute_loop_platform_writeback(db, store.id, item.id)
        raise AssertionError("observing loop must not write again")
    except ValueError as exc:
        assert "现在" in str(exc)


def _review_flow() -> dict:
    pack = build_execution_pack("reply_ordinary_reviews", object_name="当前店铺", title="普通好评待回复")
    return {
        "now": {
            "id": "nba-review",
            "source_card_id": "nba-review",
            "title": "普通好评待回复",
            "why_now": "有普通好评还没回",
            "ai_already_did": "回复稿已经准备好",
            "execution_pack": pack,
        }
    }


def test_ordinary_review_writeback_enters_observation() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_review_flow(), events=None)
    assert item is not None
    assert project_loop(item)["platform_writeable"] is True
    marked = execute_loop_platform_writeback(db, store.id, item.id)
    assert marked.status == "observing"
    assert marked.executor == "PLATFORM"
    assert "好评" in (marked.notes or "")
    pack = json.loads(marked.pack_json or "{}")
    assert pack.get("writeback", {}).get("ok") is True
    assert pack.get("writeback", {}).get("op") == "reply_review"
    assert pack.get("writeback", {}).get("review_id")


def test_negative_review_cannot_use_ordinary_reply() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    pack = build_execution_pack("reply_ordinary_reviews", object_name="当前店铺")
    assert pack is not None
    pack["review_id"] = f"mock-bad-{(store.id or 'demo')[:8]}-1"
    flow = {
        "now": {
            "id": "nba-bad",
            "source_card_id": "nba-bad",
            "title": "误把差评当好评",
            "execution_pack": pack,
        }
    }
    item = ensure_now_loop(db, store.id, decision_flow=flow, events=None)
    assert item is not None
    try:
        execute_loop_platform_writeback(db, store.id, item.id)
        raise AssertionError("negative review must not be replied via ordinary path")
    except WriteFailedError as exc:
        assert "差评" in str(exc)
    db.refresh(item)
    assert item.status == "now"


def test_batch_reply_loop_stays_human() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    pack = build_execution_pack("batch_reply_negative_reviews")
    flow = {
        "now": {
            "id": "nba-neg",
            "source_card_id": "nba-neg",
            "title": "差评整改",
            "execution_pack": pack,
        }
    }
    item = ensure_now_loop(db, store.id, decision_flow=flow, events=None)
    assert item is not None
    assert project_loop(item)["platform_writeable"] is False
    try:
        execute_loop_platform_writeback(db, store.id, item.id)
        raise AssertionError("batch negative reply must stay human")
    except WritePermissionError:
        pass
    db.refresh(item)
    assert item.status == "now"


def _appeal_flow() -> dict:
    pack = build_execution_pack("appeal_pack", object_name="当前店铺", title="恶意评价申诉")
    assert pack is not None
    pack["review_id"] = "mock-bad-demo-1"
    return {
        "now": {
            "id": "nba-appeal",
            "source_card_id": "nba-appeal",
            "title": "恶意评价申诉",
            "why_now": "这条差评疑似不实，已准备申诉说明",
            "ai_already_did": "申诉文案和证据清单已经整理好",
            "execution_pack": pack,
        }
    }


def test_appeal_writeback_requires_evidence() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    flow = _appeal_flow()
    flow["now"]["execution_pack"]["review_id"] = f"mock-bad-{(store.id or 'demo')[:8]}-1"
    item = ensure_now_loop(db, store.id, decision_flow=flow, events=None)
    assert item is not None
    try:
        execute_loop_platform_writeback(db, store.id, item.id)
        raise AssertionError("appeal without evidence must be blocked")
    except WriteFailedError as exc:
        assert "证据" in str(exc)
    db.refresh(item)
    assert item.status == "now"


def test_appeal_writeback_enters_observation_after_read_back() -> None:
    reset_mock_platform_state()
    db = _session()
    store = _store(db)
    flow = _appeal_flow()
    flow["now"]["execution_pack"]["review_id"] = f"mock-bad-{(store.id or 'demo')[:8]}-1"
    item = ensure_now_loop(db, store.id, decision_flow=flow, events=None)
    assert item is not None
    item.evidence_json = json.dumps(
        [{"kind": "note", "note": "已核对订单与聊天记录，评价内容不实", "by": "OWNER"}],
        ensure_ascii=False,
    )
    db.commit()

    marked = execute_loop_platform_writeback(db, store.id, item.id)
    assert marked.status == "observing"
    assert marked.executor == "PLATFORM"
    assert "工单号" in (marked.notes or "")
    pack = json.loads(marked.pack_json or "{}")
    assert pack.get("writeback", {}).get("ok") is True
    assert pack.get("writeback", {}).get("op") == "submit_review_appeal"
    assert pack.get("writeback", {}).get("ticket_id")
    assert pack.get("writeback", {}).get("evidence_count") == 1
