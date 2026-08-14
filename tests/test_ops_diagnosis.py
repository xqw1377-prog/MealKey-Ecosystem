"""运营诊断引擎测试 — 履约/SKU/体验/对账/合规。"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.business_facts import AdSpendDaily, OpsMetricDaily
from app.models.entities import (
    Merchant, Menu, MenuItem, MenuItemVersion, ReviewFact, ShopFunnelDaily, Store,
)
from app.services.ops_diagnosis import (
    diagnose_financial_reconciliation,
    diagnose_fulfillment,
    diagnose_order_experience,
    diagnose_sku_lifecycle,
)
from app.services.compliance_check import check_compliance


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_store(db: Session) -> str:
    m = Merchant(name="t"); db.add(m); db.flush()
    s = Store(merchant_id=m.id, name="测试店"); db.add(s); db.flush()
    return s.id


def _seed_menu(db: Session, store_id: str):
    menu = Menu(store_id=store_id); db.add(menu); db.flush()
    for name, price, cost in [("黑椒牛肉饭", 29.9, 14.6), ("宫保鸡丁", 26.9, 12.0)]:
        item = MenuItem(store_id=store_id, menu_id=menu.id, is_active=True, food_cost=cost)
        db.add(item); db.flush()
        v = MenuItemVersion(item_id=item.id, name=name, price=price, category="快餐")
        db.add(v); db.flush()
        item.current_version_id = v.id
    db.commit()


# ═══════════════════════════════════════════════════════════
# 履约诊断
# ═══════════════════════════════════════════════════════════


def test_fulfillment_no_data() -> None:
    db = _session(); sid = _seed_store(db)
    r = diagnose_fulfillment(db, sid)
    assert not r["has_data"]
    db.close()


def test_fulfillment_meal_prep_slowing() -> None:
    db = _session(); sid = _seed_store(db)
    today = date.today()
    # 出餐率从 95% 降到 85%
    db.add(OpsMetricDaily(store_id=sid, day=today-timedelta(days=3), meal_prep_rate=0.95))
    db.add(OpsMetricDaily(store_id=sid, day=today-timedelta(days=1), meal_prep_rate=0.85))
    db.commit()
    r = diagnose_fulfillment(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "MEAL_PREP_SLOWING" in codes
    db.close()


def test_fulfillment_cancel_high() -> None:
    db = _session(); sid = _seed_store(db)
    today = date.today()
    for i in range(3):
        db.add(OpsMetricDaily(store_id=sid, day=today-timedelta(days=i), merchant_cancel_rate=0.05))
    db.commit()
    r = diagnose_fulfillment(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "HIGH_MERCHANT_CANCEL" in codes
    db.close()


def test_fulfillment_packaging_complaints() -> None:
    db = _session(); sid = _seed_store(db)
    now = datetime.now(timezone.utc)
    for i in range(4):
        db.add(ReviewFact(store_id=sid, rating=1.0, content="汤全洒了", reviewed_at=now-timedelta(days=i), source="test"))
    db.commit()
    r = diagnose_fulfillment(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "PACKAGING_COMPLAINTS" in codes
    db.close()


# ═══════════════════════════════════════════════════════════
# SKU 生命周期
# ═══════════════════════════════════════════════════════════


def test_sku_lifecycle_no_menu() -> None:
    db = _session(); sid = _seed_store(db)
    r = diagnose_sku_lifecycle(db, sid)
    assert not r["has_data"]
    db.close()


def test_sku_lifecycle_low_margin() -> None:
    db = _session(); sid = _seed_store(db); _seed_menu(db, sid)
    # 给黑椒牛肉饭设一个高销量低利润
    from app.models.entities import ItemFunnelDaily
    item = db.query(MenuItem).filter_by(store_id=sid).first()
    for i in range(7):
        db.add(ItemFunnelDaily(item_id=item.id, day=date.today()-timedelta(days=i), orders=20))
    # 设 food_cost 接近 price → 低利润
    item.food_cost = 26.0  # price=29.9, cost=26 → margin=13%
    db.commit()
    r = diagnose_sku_lifecycle(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "LOW_MARGIN_HIGH_VOLUME" in codes
    db.close()


# ═══════════════════════════════════════════════════════════
# 下单体验
# ═══════════════════════════════════════════════════════════


def test_order_experience_expectation_gap() -> None:
    db = _session(); sid = _seed_store(db)
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.add(ReviewFact(store_id=sid, rating=2.0, content="实物和图片完全不一样", reviewed_at=now-timedelta(days=i), source="test"))
    db.commit()
    r = diagnose_order_experience(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "EXPECTATION_GAP" in codes
    db.close()


def test_order_experience_quality_issue() -> None:
    db = _session(); sid = _seed_store(db)
    now = datetime.now(timezone.utc)
    db.add(ReviewFact(store_id=sid, rating=1.0, content="鸡肉是坏的馊了", reviewed_at=now, source="test"))
    db.add(ReviewFact(store_id=sid, rating=1.0, content="米饭不新鲜", reviewed_at=now-timedelta(days=1), source="test"))
    db.commit()
    r = diagnose_order_experience(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "QUALITY_UNSTABLE" in codes
    db.close()


# ═══════════════════════════════════════════════════════════
# 财务对账
# ═══════════════════════════════════════════════════════════


def test_financial_no_data() -> None:
    db = _session(); sid = _seed_store(db)
    r = diagnose_financial_reconciliation(db, sid)
    assert not r["has_data"]
    db.close()


def test_financial_high_ads_ratio() -> None:
    db = _session(); sid = _seed_store(db)
    today = date.today()
    for i in range(3):
        db.add(ShopFunnelDaily(store_id=sid, day=today-timedelta(days=i), gmv=1000, orders=30, ads_spend=200))
    db.commit()
    r = diagnose_financial_reconciliation(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "HIGH_ADS_RATIO" in codes
    db.close()


# ═══════════════════════════════════════════════════════════
# 合规检测
# ═══════════════════════════════════════════════════════════


def test_compliance_name_violation() -> None:
    db = _session(); sid = _seed_store(db); _seed_menu(db, sid)
    # 修改一个商品名含违规词
    item = db.query(MenuItem).filter_by(store_id=sid).first()
    v = db.get(MenuItemVersion, item.current_version_id)
    v.name = "全国最好吃的牛肉饭"
    db.commit()
    r = check_compliance(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "PRODUCT_NAME_VIOLATION_RISK" in codes
    db.close()


def test_compliance_missing_image() -> None:
    db = _session(); sid = _seed_store(db); _seed_menu(db, sid)
    r = check_compliance(db, sid)
    codes = [f["code"] for f in r["findings"]]
    assert "MISSING_IMAGE" in codes  # 都没图片
    db.close()
