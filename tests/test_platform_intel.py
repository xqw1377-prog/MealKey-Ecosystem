"""官网公开政策 / 促销采集：只抓公开页，失败不编造。"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.business_facts import CampaignRecord
from app.models.platform_intel import PlatformIntelItem, PlatformIntelRun
from app.services.operating_demands.handler import handle_demand_intent
from app.services.operating_demands.router import match_demand
from app.services.platform_intel import (
    IntelFetchError,
    _is_safe_url,
    classify_kind,
    collect_official_intel,
    default_fetch,
    list_intel,
)

_MEITUAN_NEWS = "https://www.meituan.com/news/"
_POLICY_URL = "https://www.meituan.com/news/NN260612201002604"
_PROMO_URL = "https://www.meituan.com/news/NN250207077004104"

_PAGES = {
    _MEITUAN_NEWS: """
    <html><head><title>美团新闻</title></head>
    <body>
      <a href="/news/NN260612201002604">美团上线商家AI守护 治理恶意评价</a>
      <a href="/news/NN250207077004104">午市流量券活动开始报名</a>
      <p>美团新闻中心公开稿件</p>
    </body></html>
    """,
    _POLICY_URL: """
    <html><head><title>美团上线商家AI守护 治理恶意评价</title></head>
    <body><p>平台将持续投入恶意退款和评价治理。商家需遵守评价规则。</p></body></html>
    """,
    _PROMO_URL: """
    <html><head><title>午市流量券活动开始报名</title></head>
    <body><p>即日起至本月底，午市满减活动商家承担部分补贴，可报名参加。</p></body></html>
    """,
}

_SOURCE = {
    "platform": "meituan",
    "name": "美团新闻中心",
    "url": _MEITUAN_NEWS,
    "kind_hint": "news",
    "follow_links": True,
    "link_contains": "/news/",
}


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _fake_fetch(url: str) -> tuple[int, str, str, str]:
    body = _PAGES.get(url)
    if body is None:
        raise IntelFetchError(f"HTTP 404 {url}")
    return 200, "text/html; charset=utf-8", body, url


def test_classify_policy_and_promo() -> None:
    assert classify_kind("美团上线商家AI守护 治理恶意评价", "评价规则", "news") == "policy"
    assert classify_kind("午市流量券活动开始报名", "满减活动可报名", "news") == "promo"


def test_rejects_private_and_login_like_urls() -> None:
    assert _is_safe_url("https://www.meituan.com/news/") is True
    assert _is_safe_url("http://www.meituan.com/news/") is False
    assert _is_safe_url("https://127.0.0.1/merchant/login") is False
    assert _is_safe_url("https://localhost/waimaie") is False
    try:
        default_fetch("https://127.0.0.1/secret")
        assert False, "should reject loopback"
    except IntelFetchError:
        pass


def test_collect_persists_and_dedupes(monkeypatch) -> None:
    monkeypatch.setattr("app.services.platform_intel.load_sources", lambda db=None: [_SOURCE])
    db = _session()
    first = collect_official_intel(db, fetch=_fake_fetch)
    assert first["status"] == "completed"
    assert first["new_count"] >= 2
    titles = {row.title for row in db.execute(select(PlatformIntelItem)).scalars()}
    assert "午市流量券活动开始报名" in titles
    assert "美团上线商家AI守护 治理恶意评价" in titles
    kinds = {row.title: row.kind for row in db.execute(select(PlatformIntelItem)).scalars()}
    assert kinds["午市流量券活动开始报名"] == "promo"
    assert kinds["美团上线商家AI守护 治理恶意评价"] == "policy"

    second = collect_official_intel(db, fetch=_fake_fetch)
    assert second["new_count"] == 0
    count = len(list(db.execute(select(PlatformIntelItem)).scalars()))
    assert count == first["fetched_count"]


def test_failed_fetch_does_not_invent_campaigns(monkeypatch) -> None:
    monkeypatch.setattr("app.services.platform_intel.load_sources", lambda db=None: [_SOURCE])

    def boom(url: str) -> tuple[int, str, str, str]:
        raise IntelFetchError(f"HTTP 403 {url}")

    db = _session()
    result = collect_official_intel(db, fetch=boom)
    assert result["status"] == "failed"
    assert result["fetched_count"] == 0
    assert db.execute(select(PlatformIntelItem)).scalar_one_or_none() is None
    run = db.execute(select(PlatformIntelRun)).scalar_one()
    assert run.error
    assert "403" in run.error


def test_ask_official_campaign_uses_collected_intel(monkeypatch) -> None:
    monkeypatch.setattr("app.services.platform_intel.load_sources", lambda db=None: [_SOURCE])
    db = _session()
    seeded = seed_demo(db)
    collect_official_intel(db, store_id=seeded["store_id"], fetch=_fake_fetch)

    demand = match_demand("最近有什么官方活动")
    assert demand is not None
    assert demand.code == "JOIN_CAMPAIGN"
    assert match_demand("平台最新政策是什么").code == "JOIN_CAMPAIGN"

    result = handle_demand_intent(db, seeded["store_id"], "最近有什么官方活动")
    assert result is not None
    assert result["demand"]["code"] == "JOIN_CAMPAIGN"
    assert "午市流量券活动开始报名" in result["answer"]
    assert "禁止" in result["answer"] and "无账" in result["answer"]
    assert "活动一定能带来利润" not in result["conclusion"]
    campaigns = list(
        db.execute(select(CampaignRecord).where(CampaignRecord.store_id == seeded["store_id"])).scalars()
    )
    official = [row for row in campaigns if row.source == "official_web"]
    assert official
    assert all(row.merchant_subsidy is None for row in official)
    assert all(row.status == "unknown" for row in official)
    assert list_intel(db, kind="promo")
