import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import (
    CompetitionCollectionRun,
    CompetitorRawPayload,
    CompetitorSnapshot,
    CompetitorStore,
    Merchant,
    Store,
    StoreCompetitorWatch,
)
from app.schemas.competition import CompetitorMenuItemInput
from app.services.competition_collection import (
    AmapCompetitionSource,
    DiscoveredCompetitor,
    LicensedPartnerCompetitionSource,
    backfill_legacy_competitor_watches,
    build_competition_map,
    collect_store_competitors,
)


def _session_with_store() -> tuple[Session, Store]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    merchant = Merchant(name="老王牛肉饭", category="快餐")
    db.add(merchant)
    db.flush()
    store = Store(
        merchant_id=merchant.id,
        name="老王牛肉饭·国贸店",
        area="国贸",
        latitude=39.909,
        longitude=116.397,
        delivery_radius_m=2500,
    )
    db.add(store)
    db.commit()
    return db, store


class _FakeSource:
    provider = "licensed_test"

    def discover(self, store: Store) -> list[DiscoveredCompetitor]:
        return [
            DiscoveredCompetitor(
                external_id="self",
                name=store.name,
                latitude=store.latitude,
                longitude=store.longitude,
            ),
            DiscoveredCompetitor(
                external_id="competitor-a",
                name="饭点到·国贸店",
                category="快餐",
                area=store.area,
                latitude=39.912,
                longitude=116.401,
                rating=4.7,
                price_band_min=25,
                price_band_max=36,
                menu_items=[
                    CompetitorMenuItemInput(name="鸡腿饭", price=29),
                    CompetitorMenuItemInput(name="午餐套餐", price=35),
                ],
                raw_payload={"source": "licensed", "id": "competitor-a"},
            ),
        ]


def test_collection_persists_raw_clean_and_map_layers() -> None:
    db, store = _session_with_store()

    result = collect_store_competitors(db, store.id, source=_FakeSource())

    assert result.status == "completed"
    assert result.discovered_count == 2
    assert result.snapshot_count == 1
    assert result.skipped_count == 1
    assert db.scalar(select(func.count()).select_from(CompetitorRawPayload)) == 1
    assert db.scalar(select(func.count()).select_from(CompetitorSnapshot)) == 1
    assert db.scalar(select(func.count()).select_from(StoreCompetitorWatch)) == 1
    run = db.get(CompetitionCollectionRun, result.run_id)
    assert run is not None
    assert run.status == "completed"

    map_payload = build_competition_map(db, store.id)
    assert map_payload is not None
    assert map_payload.radius_m == 2500
    assert map_payload.competitors[0].name == "饭点到·国贸店"
    assert map_payload.competitors[0].distance_m is not None


class _FakeHttpResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "status": "1",
                "pois": [
                    {
                        "id": "B001",
                        "name": "附近餐厅",
                        "location": "116.401,39.912",
                        "type": "餐饮服务;中餐厅;快餐",
                        "adname": "朝阳区",
                        "business": {"rating": "4.6", "cost": "32"},
                    }
                ],
            },
            ensure_ascii=False,
        ).encode()


def test_amap_source_normalizes_poi_response(monkeypatch) -> None:
    db, store = _session_with_store()
    monkeypatch.setattr(
        "app.services.competition_collection.urlopen",
        lambda *_args, **_kwargs: _FakeHttpResponse(),
    )

    rows = AmapCompetitionSource(api_key="test-key").discover(store)

    assert len(rows) == 1
    assert rows[0].external_id == "B001"
    assert rows[0].rating == 4.6
    assert rows[0].price_band_min == 25.6
    assert rows[0].price_band_max == 38.4


class _FakeGeocodeResponse(_FakeHttpResponse):
    def read(self) -> bytes:
        return json.dumps(
            {
                "status": "1",
                "geocodes": [{"location": "116.397,39.909"}],
            }
        ).encode()


def test_amap_source_geocodes_store_before_discovery(monkeypatch) -> None:
    db, store = _session_with_store()
    store.latitude = None
    store.longitude = None
    store.address = "北京市朝阳区国贸"

    def fake_urlopen(request, **_kwargs):
        if "geocode/geo" in request.full_url:
            return _FakeGeocodeResponse()
        return _FakeHttpResponse()

    monkeypatch.setattr(
        "app.services.competition_collection.urlopen",
        fake_urlopen,
    )

    rows = AmapCompetitionSource(api_key="test-key").discover(store)

    assert rows
    assert store.latitude == 39.909
    assert store.longitude == 116.397


def test_collection_failure_is_auditable() -> None:
    db, store = _session_with_store()

    result = collect_store_competitors(
        db,
        store.id,
        source=AmapCompetitionSource(api_key=""),
    )

    assert result.status == "failed"
    assert "AMAP_WEB_SERVICE_KEY" in (result.error or "")
    run = db.get(CompetitionCollectionRun, result.run_id)
    assert run is not None
    assert run.status == "failed"


class _FakePartnerResponse(_FakeHttpResponse):
    def read(self) -> bytes:
        return json.dumps(
            {
                "competitors": [
                    {
                        "external_id": "partner-1",
                        "name": "授权竞品",
                        "latitude": 39.913,
                        "longitude": 116.402,
                        "rating": 4.8,
                        "review_count": 1200,
                        "price_band_min": 28,
                        "price_band_max": 42,
                        "menu_items": [
                            {
                                "name": "双人套餐",
                                "price": 42,
                                "image_url": "https://example.com/combo.jpg",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ).encode()


def test_licensed_partner_source_normalizes_deep_data(monkeypatch) -> None:
    db, store = _session_with_store()
    monkeypatch.setattr(
        "app.services.competition_collection.urlopen",
        lambda *_args, **_kwargs: _FakePartnerResponse(),
    )

    rows = LicensedPartnerCompetitionSource(
        api_url="https://partner.example.com/competition",
        api_token="test-token",
    ).discover(store)

    assert len(rows) == 1
    assert rows[0].review_count == 1200
    assert rows[0].menu_items[0].name == "双人套餐"


def test_legacy_competitors_are_backfilled_to_store_watch() -> None:
    db, store = _session_with_store()
    db.add(
        CompetitorStore(
            name="历史竞品",
            area=store.area,
            platform="legacy",
            platform_store_key="legacy-1",
        )
    )
    db.commit()

    created_count = backfill_legacy_competitor_watches(db)

    assert created_count == 1
    assert db.scalar(select(func.count()).select_from(StoreCompetitorWatch)) == 1
