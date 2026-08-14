"""业务数据导入测试 — 验证 4 种导入类型的解析和写入正确性。

补足竞品对标表中的"平台真实数据"短板。
"""
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.business_facts import AdSpendDaily, CampaignRecord, ReviewImport
from app.models.entities import Merchant, ReviewFact, ShopFunnelDaily, Store
from app.services.business_import import (
    get_data_coverage,
    import_ads_data,
    import_campaigns,
    import_funnel_data,
    import_reviews,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_store(db: Session) -> str:
    m = Merchant(name="测试商户")
    db.add(m)
    db.flush()
    s = Store(merchant_id=m.id, name="测试店")
    db.add(s)
    db.flush()
    return s.id


# ═══════════════════════════════════════════════════════════
# 每日经营数据导入
# ═══════════════════════════════════════════════════════════


def test_import_funnel_csv() -> None:
    """CSV 每日经营数据导入。"""
    db = _session()
    store_id = _seed_store(db)

    csv = "日期,曝光量,访问量,订单量,营业额,客单价\n2024-01-01,5000,800,150,4500,30\n2024-01-02,5200,850,160,4800,30\n"
    result = import_funnel_data(db, store_id, csv.encode("utf-8"), "funnel.csv")

    assert result["imported"] == 2
    assert "batch_id" in result

    rows = db.query(ShopFunnelDaily).filter_by(store_id=store_id).all()
    assert len(rows) == 2
    assert rows[0].impressions == 5000
    assert rows[0].orders == 150
    assert rows[0].gmv == 4500
    assert rows[0].data_source == "platform_export"
    db.close()


def test_import_funnel_with_ads_spend() -> None:
    """经营数据导入包含推广费。"""
    db = _session()
    store_id = _seed_store(db)

    csv = "日期,曝光量,订单量,营业额,推广费\n2024-01-01,5000,150,4500,300\n"
    import_funnel_data(db, store_id, csv.encode("utf-8"), "funnel.csv")

    row = db.query(ShopFunnelDaily).filter_by(store_id=store_id, day=date(2024, 1, 1)).one()
    assert row.ads_spend == 300
    db.close()


def test_import_funnel_json() -> None:
    """JSON 格式经营数据导入。"""
    db = _session()
    store_id = _seed_store(db)

    import json
    data = json.dumps({"items": [{"日期": "2024-03-01", "订单量": 200, "营业额": 6000}]})
    result = import_funnel_data(db, store_id, data.encode("utf-8"), "data.json")
    assert result["imported"] == 1

    row = db.query(ShopFunnelDaily).filter_by(store_id=store_id).one()
    assert row.orders == 200
    db.close()


# ═══════════════════════════════════════════════════════════
# 推广投流数据导入
# ═══════════════════════════════════════════════════════════


def test_import_ads_csv() -> None:
    """推广投流 CSV 导入 + CPC/ROAS 派生。"""
    db = _session()
    store_id = _seed_store(db)

    csv = "日期,花费,点击量,广告曝光,推广订单,推广交易额\n2024-01-01,300,150,3000,15,450\n"
    result = import_ads_data(db, store_id, csv.encode("utf-8"), "ads.csv")
    assert result["imported"] == 1

    row = db.query(AdSpendDaily).filter_by(store_id=store_id).one()
    assert row.cost == 300
    assert row.clicks == 150
    assert row.cpc == 2.0  # 300/150
    assert row.ctr == 0.05  # 150/3000
    assert row.roas == 1.5  # 450/300
    db.close()


# ═══════════════════════════════════════════════════════════
# 评价数据导入
# ═══════════════════════════════════════════════════════════


def test_import_reviews_csv() -> None:
    """评价 CSV 导入 + 同步写入 ReviewFact。"""
    db = _session()
    store_id = _seed_store(db)

    csv = "评分,评价内容,评价时间\n5,非常好吃,2024-01-01 12:00:00\n2,份量太少了,2024-01-02 13:00:00\n"
    result = import_reviews(db, store_id, csv.encode("utf-8"), "reviews.csv")
    assert result["imported"] == 2

    # ReviewImport 层
    imports = db.query(ReviewImport).filter_by(store_id=store_id).all()
    assert len(imports) == 2

    # ReviewFact 同步层(供诊断使用)
    facts = db.query(ReviewFact).filter_by(store_id=store_id).all()
    assert len(facts) == 2
    assert any(f.rating == 5 for f in facts)
    assert any("份量" in (f.content or "") for f in facts)
    db.close()


# ═══════════════════════════════════════════════════════════
# 活动数据导入
# ═══════════════════════════════════════════════════════════


def test_import_campaigns_csv() -> None:
    """活动 CSV 导入。"""
    db = _session()
    store_id = _seed_store(db)

    csv = "活动名称,开始日期,结束日期,优惠金额,平台承担,商家承担\n满30减5,2024-01-01,2024-01-31,5,3,2\n"
    result = import_campaigns(db, store_id, csv.encode("utf-8"), "campaigns.csv")
    assert result["imported"] == 1

    row = db.query(CampaignRecord).filter_by(store_id=store_id).one()
    assert row.name == "满30减5"
    assert row.platform_subsidy == 3
    assert row.merchant_subsidy == 2
    assert row.start_date == date(2024, 1, 1)
    db.close()


# ═══════════════════════════════════════════════════════════
# 数据覆盖度查询
# ═══════════════════════════════════════════════════════════


def test_data_coverage() -> None:
    """数据覆盖度查询。"""
    db = _session()
    store_id = _seed_store(db)

    # 初始为空
    cov = get_data_coverage(db, store_id)
    assert cov["funnel_days"] == 0
    assert cov["ads_days"] == 0
    assert cov["reviews"] == 0

    # 导入数据
    csv = "日期,曝光量,订单量\n2024-01-01,5000,150\n2024-01-02,5200,160\n"
    import_funnel_data(db, store_id, csv.encode("utf-8"), "f.csv")

    cov = get_data_coverage(db, store_id)
    assert cov["funnel_days"] == 2
    db.close()


# ═══════════════════════════════════════════════════════════
# 边界情况
# ═══════════════════════════════════════════════════════════


def test_import_funnel_no_date_column() -> None:
    """无日期列 → 报错。"""
    db = _session()
    store_id = _seed_store(db)
    csv = "曝光量,订单量\n5000,150\n"
    result = import_funnel_data(db, store_id, csv.encode("utf-8"), "bad.csv")
    assert "error" in result
    assert result["imported"] == 0
    db.close()


def test_import_funnel_upsert() -> None:
    """同一天数据二次导入 → 更新而非新增。"""
    db = _session()
    store_id = _seed_store(db)

    csv1 = "日期,订单量\n2024-01-01,100\n"
    import_funnel_data(db, store_id, csv1.encode("utf-8"), "f.csv")

    csv2 = "日期,订单量,营业额\n2024-01-01,120,3600\n"
    import_funnel_data(db, store_id, csv2.encode("utf-8"), "f2.csv")

    rows = db.query(ShopFunnelDaily).filter_by(store_id=store_id).all()
    assert len(rows) == 1  # 不是 2
    assert rows[0].orders == 120  # 更新后的值
    assert rows[0].gmv == 3600
    db.close()
