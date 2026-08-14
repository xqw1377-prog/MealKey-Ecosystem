from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, Store
from app.services.promo_poster import build_promo_poster, detect_occasion, looks_like_poster_request


def test_poster_request_does_not_steal_main_image() -> None:
    assert looks_like_poster_request("做一张午市促销海报") is True
    assert looks_like_poster_request("换主图") is False
    assert detect_occasion("午市爆单海报") == "lunch"
    assert detect_occasion("新品上新") == "new"


def test_promo_poster_plugin_returns_wallet_alert() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    merchant = Merchant(name="海报店")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="餐启样板店")
    db.add(store)
    db.commit()
    pack = build_promo_poster(db, store, prompt="做一张午市满30减5海报，主推牛肉饭")
    assert pack["plugin"] == "promo_poster"
    assert pack["poster"]["theme"] == "lunch"
    assert pack["poster"]["dish"] == "牛肉饭"
    assert pack["poster"]["offer"] == "满30减5"
    assert pack["poster"]["store_name"] == "餐启样板店"
    assert pack["wallet_alert"]["purchase_path"] == "avatar_wallet"
    assert pack["wallet"]["alert"]["status"] == "empty"
