from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.closed_loop import ClosedLoopItem
from app.models.commercial import GrowthArtifact, ReferralAttribution
from app.models.entities import Merchant, Store
from app.services.commercial.growth import (
    attach_referral_store,
    ensure_result_card,
    public_card,
    run_free_audit,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session) -> Store:
    merchant = Merchant(name="裂变商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="老王牛肉饭")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def _loop(db: Session, store: Store, *, result: str = "positive", lift: float | None = 14.6) -> ClosedLoopItem:
    item = ClosedLoopItem(
        store_id=store.id,
        fingerprint="share-test",
        title="换主图抢回点击",
        action_type="change_main_image",
        success_metric="点击率",
        status="result_ready",
        result=result,
        pack_json='{"lift_pct": %s}' % (lift if lift is not None else "null"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_result_card_hides_store_and_money() -> None:
    db = _session()
    store = _store(db)
    item = _loop(db, store)
    artifact = ensure_result_card(db, item)
    assert artifact is not None
    card = public_card(artifact, share_url="/r/x")
    blob = str(card)
    assert "老王" not in blob
    assert "牛肉饭" not in blob
    assert "gmv" not in blob.lower()
    assert card["cta"] == "测一下我的店"
    assert card["lift_pct"] == 14.6
    assert "换主图" in card["title"]


def test_negative_result_does_not_auto_mint() -> None:
    db = _session()
    store = _store(db)
    item = _loop(db, store, result="negative", lift=-3)
    assert ensure_result_card(db, item, force=False) is None
    forced = ensure_result_card(db, item, force=True)
    assert forced is not None
    assert db.query(GrowthArtifact).count() == 1


def test_free_audit_creates_attribution_then_store() -> None:
    db = _session()
    store = _store(db)
    item = _loop(db, store)
    artifact = ensure_result_card(db, item)
    assert artifact is not None
    audit = run_free_audit(db, artifact, store_name="隔壁鸡饭", city="上海", pain="有曝光没转化")
    assert audit["audit_cap_cny"] == 5
    assert any("主图" in line or "标题" in line for line in audit["findings"])
    row = db.query(ReferralAttribution).one()
    assert row.from_store_id == store.id
    assert row.to_store_id is None
    assert row.path == "result_share"
    new_store = Store(merchant_id=store.merchant_id, name="隔壁鸡饭")
    db.add(new_store)
    db.flush()
    attached = attach_referral_store(db, artifact_id=artifact.id, to_store_id=new_store.id)
    assert attached is not None
    assert attached.to_store_id == new_store.id
    assert attached.status == "store_created"
