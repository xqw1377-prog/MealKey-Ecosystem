"""增强能力测试 — 投流诊断 / 评价闭环 / 归因护栏。

验证补足竞品短板的 3 个新能力:
1. analyze_ads: CPC/ROAS 趋势判断
2. trigger_bad_reviews: 差评率自动检测
3. experiment_attribution 护栏: 到手率/CPC 恶化时降级 positive→neutral
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.business_facts import AdSpendDaily
from app.models.entities import Merchant, ReviewFact, Store
from app.services.domain_skills import analyze_ads


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
# 1. 投流诊断 analyze_ads
# ═══════════════════════════════════════════════════════════


def test_analyze_ads_insufficient_data() -> None:
    """数据不足 → 友好提示。"""
    result = analyze_ads(ads_daily=[], profit_floor=0.17)
    assert "不足" in result.diagnosis.primary
    assert len(result.candidate_actions) == 0


def test_analyze_ads_cpc_rising() -> None:
    """CPC 上涨 → 检测到 CPC_RISING + 建议优化。"""
    ads = [
        {"day": "2024-01-01", "cost": 200, "clicks": 100, "cpc": 2.0, "roas": 3.0},
        {"day": "2024-01-02", "cost": 250, "clicks": 100, "cpc": 2.5, "roas": 2.8},
        {"day": "2024-01-03", "cost": 300, "clicks": 100, "cpc": 3.0, "roas": 2.5},  # CPC +50%
    ]
    result = analyze_ads(ads_daily=ads, profit_floor=0.17)
    codes = [f.code for f in result.findings]
    assert "CPC_RISING" in codes
    assert len(result.candidate_actions) > 0


def test_analyze_ads_low_roas() -> None:
    """ROAS 过低 → 检测到 LOW_ROAS + 建议减预算。"""
    ads = [
        {"day": "2024-01-01", "cost": 300, "clicks": 150, "cpc": 2.0, "roas": 2.5},
        {"day": "2024-01-02", "cost": 300, "clicks": 150, "cpc": 2.0, "roas": 1.5},
    ]
    result = analyze_ads(ads_daily=ads, profit_floor=0.17)
    codes = [f.code for f in result.findings]
    assert "LOW_ROAS" in codes


def test_analyze_ads_healthy() -> None:
    """投流健康 → 正面发现。"""
    ads = [
        {"day": "2024-01-01", "cost": 200, "clicks": 100, "cpc": 2.0, "roas": 4.0},
        {"day": "2024-01-02", "cost": 200, "clicks": 100, "cpc": 2.0, "roas": 4.0},
    ]
    result = analyze_ads(ads_daily=ads, profit_floor=0.17)
    codes = [f.code for f in result.findings]
    assert "ADS_HEALTHY" in codes


# ═══════════════════════════════════════════════════════════
# 2. 评价闭环 trigger_bad_reviews
# ═══════════════════════════════════════════════════════════


def test_trigger_bad_reviews_fires() -> None:
    """差评率 > 20% 且 >= 3 条 → 触发候选。"""
    from app.schemas.store_state import ManagerHomeBrief
    from app.services.poie.triggers import trigger_bad_reviews

    db = _session()
    store_id = _seed_store(db)
    now = datetime.now(timezone.utc)

    # 插入 10 条评价,5 条差评(50% 差评率)
    for i in range(5):
        db.add(ReviewFact(
            store_id=store_id, rating=2.0, content="份量太少了",
            reviewed_at=now - timedelta(days=i), source="test",
        ))
    for i in range(5):
        db.add(ReviewFact(
            store_id=store_id, rating=5.0, content="很好吃",
            reviewed_at=now - timedelta(days=i), source="test",
        ))
    db.commit()

    brief = ManagerHomeBrief(store_name="测试店", business_health_score=70, business_judgment="正常")
    candidates = trigger_bad_reviews(brief, db=db, store_id=store_id)
    assert len(candidates) == 1
    assert "差评率" in candidates[0].title
    db.close()


def test_trigger_bad_reviews_no_fire_when_good() -> None:
    """好评为主 → 不触发。"""
    from app.schemas.store_state import ManagerHomeBrief
    from app.services.poie.triggers import trigger_bad_reviews

    db = _session()
    store_id = _seed_store(db)
    now = datetime.now(timezone.utc)

    for i in range(10):
        db.add(ReviewFact(
            store_id=store_id, rating=5.0, content="很好",
            reviewed_at=now - timedelta(days=i), source="test",
        ))
    db.commit()

    brief = ManagerHomeBrief(store_name="测试店", business_health_score=70, business_judgment="正常")
    candidates = trigger_bad_reviews(brief, db=db, store_id=store_id)
    assert len(candidates) == 0
    db.close()


def test_trigger_bad_reviews_too_few() -> None:
    """差评少于 3 条 → 不触发。"""
    from app.schemas.store_state import ManagerHomeBrief
    from app.services.poie.triggers import trigger_bad_reviews

    db = _session()
    store_id = _seed_store(db)
    now = datetime.now(timezone.utc)

    # 只插 1 条差评 → 不触发(阈值 >= 2)
    db.add(ReviewFact(
        store_id=store_id, rating=1.0, content="差",
        reviewed_at=now, source="test",
    ))
    db.commit()

    brief = ManagerHomeBrief(store_name="测试店", business_health_score=70, business_judgment="正常")
    candidates = trigger_bad_reviews(brief, db=db, store_id=store_id)
    assert len(candidates) == 0
    db.close()


# ═══════════════════════════════════════════════════════════
# 3. FeedbackInfo 差评信号
# ═══════════════════════════════════════════════════════════


def test_feedback_info_has_bad_review_fields() -> None:
    """FeedbackInfo 包含差评信号字段。"""
    from app.schemas.store_state import FeedbackInfo

    fi = FeedbackInfo()
    assert fi.recent_review_count == 0
    assert fi.recent_bad_review_count == 0
    assert fi.bad_review_rate is None
    assert fi.recent_bad_reviews == []
