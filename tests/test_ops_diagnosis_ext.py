"""扩展运营诊断测试 — 财务/排班/SKU策略/体验细节/内容/新店/设备。"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.business_facts import AdSpendDaily
from app.models.entities import (
    Merchant, Menu, MenuItem, MenuItemVersion, ReviewFact, ShopFunnelDaily, Store,
)
from app.services.ops_diagnosis import (
    diagnose_content_health,
    diagnose_device_health,
    diagnose_new_store_setup,
    diagnose_order_detail,
    diagnose_settlement_detail,
    diagnose_sku_strategy,
    diagnose_staffing,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _seed(db):
    m = Merchant(name="t"); db.add(m); db.flush()
    s = Store(merchant_id=m.id, name="测试店"); db.add(s); db.flush()
    return s.id


def test_settlement_forecast() -> None:
    db = _session(); sid = _seed(db)
    today = date.today()
    for i in range(5):
        db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=i), gmv=3000, orders=100, data_source="file_import"))
    db.commit()
    r = diagnose_settlement_detail(db, sid)
    assert r["has_data"]
    codes = [f["code"] for f in r["findings"]]
    assert "SETTLEMENT_FORECAST" in codes
    db.close()


def test_settlement_cash_flow() -> None:
    db = _session(); sid = _seed(db)
    today = date.today()
    for i in range(3):
        db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=i), gmv=1000, orders=30, ads_spend=200, data_source="file_import"))
    db.commit()
    r = diagnose_settlement_detail(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "CASH_FLOW_PRESSURE" in codes
    db.close()


def test_staffing_prep_forecast() -> None:
    db = _session(); sid = _seed(db)
    today = date.today()
    for i in range(7):
        db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=i), orders=80+i, data_source="file_import"))
    db.commit()
    r = diagnose_staffing(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "PREP_FORECAST" in codes
    db.close()


def test_staffing_bottleneck() -> None:
    db = _session(); sid = _seed(db)
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.add(ReviewFact(store_id=sid, rating=2.0, content="等太久了出餐太慢", reviewed_at=now-timedelta(days=i), source="test"))
    from app.models.business_facts import OpsMetricDaily
    db.add(OpsMetricDaily(store_id=sid, day=date.today(), meal_prep_rate=0.75, merchant_cancel_rate=0.01, im_reply_rate=0.9))
    # Need funnel data too so it has has_data
    for i in range(3):
        db.add(ShopFunnelDaily(store_id=sid, day=date.today()-timedelta(days=i), orders=80, data_source="file_import"))
    db.commit()
    r = diagnose_staffing(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "BOTTLENECK_DETECTED" in codes
    db.close()


def test_sku_strategy_price_increase() -> None:
    db = _session(); sid = _seed(db)
    menu = Menu(store_id=sid); db.add(menu); db.flush()
    # price=29.9, food_cost=28, packaging=1 → margin = (29.9-28-1)/29.9 = 3% < 12%
    item = MenuItem(store_id=sid, menu_id=menu.id, is_active=True, food_cost=28.0, packaging_cost=1.0)
    db.add(item); db.flush()
    v = MenuItemVersion(item_id=item.id, name="牛肉饭", price=29.9)
    db.add(v); db.flush()
    item.current_version_id = v.id
    db.commit()
    r = diagnose_sku_strategy(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "PRICE_INCREASE_NEEDED" in codes
    db.close()


def test_order_detail_note_issue() -> None:
    db = _session(); sid = _seed(db)
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.add(ReviewFact(store_id=sid, rating=2.0, content="备注了不要葱还是放了", reviewed_at=now-timedelta(days=i), source="test"))
    db.commit()
    r = diagnose_order_detail(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "NOTE_EXECUTION_ISSUE" in codes
    db.close()


def test_content_health_no_image() -> None:
    db = _session(); sid = _seed(db)
    menu = Menu(store_id=sid); db.add(menu); db.flush()
    for name in ["牛肉饭","鸡丁","炒蛋"]:
        item = MenuItem(store_id=sid, menu_id=menu.id, is_active=True)
        db.add(item); db.flush()
        v = MenuItemVersion(item_id=item.id, name=name, price=20)
        db.add(v); db.flush()
        item.current_version_id = v.id
    db.commit()
    r = diagnose_content_health(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "IMAGE_REALITY_GAP" in codes
    db.close()


def test_device_zero_order() -> None:
    db = _session(); sid = _seed(db)
    today = date.today()
    db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=2), orders=50, data_source="file_import"))
    db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=1), orders=0, data_source="file_import"))
    db.add(ShopFunnelDaily(store_id=sid, day=today, orders=50, data_source="file_import"))
    db.commit()
    r = diagnose_device_health(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "ZERO_ORDER_DAY" in codes
    db.close()


def test_new_store_advice() -> None:
    db = _session(); sid = _seed(db)
    today = date.today()
    for i in range(7):
        db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=i), orders=50, data_source="file_import"))
    db.commit()
    r = diagnose_new_store_setup(db, sid)
    assert r["has_data"]
    codes = [f["code"] for f in r["findings"]]
    assert "BUSINESS_HOURS_ADVICE" in codes
    assert "DELIVERY_RADIUS_ADVICE" in codes
    db.close()


def test_order_detail_note_type() -> None:
    db = _session(); sid = _seed(db)
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.add(ReviewFact(store_id=sid, rating=2.0, content="备注了不要葱还是放了", reviewed_at=now-timedelta(days=i), source="test"))
    db.commit()
    r = diagnose_order_detail(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "NOTE_TYPE_MISS" in codes
    db.close()


def test_settlement_refund_gap_is_honest() -> None:
    db = _session(); sid = _seed(db)
    today = date.today()
    for i in range(5):
        db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=i), gmv=3000, orders=100, data_source="file_import"))
    db.commit()
    r = diagnose_settlement_detail(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "REFUND_LEDGER_MISSING" in codes
    db.close()


def test_project_ops_findings_filters_demand() -> None:
    from app.services.ops_diagnosis import project_ops_findings

    db = _session(); sid = _seed(db)
    today = date.today()
    for i in range(5):
        db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=i), gmv=3000, orders=100, data_source="file_import"))
    db.commit()
    facts = project_ops_findings(db, sid, 108)
    assert facts["ops_has_data"]
    assert facts["ops_findings"]
    assert all(item["demand_id"] == 108 for item in facts["ops_findings"])
    empty = project_ops_findings(db, sid, 1)
    assert empty == {}
    db.close()
