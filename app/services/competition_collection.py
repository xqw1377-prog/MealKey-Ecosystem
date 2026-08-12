from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import (
    CompetitionCollectionRun,
    CompetitorMenuItem,
    CompetitorRawPayload,
    CompetitorSnapshot,
    CompetitorStore,
    Store,
    StoreCompetitorWatch,
)
from app.schemas.competition import (
    CompetitionCollectionResult,
    CompetitionMapPoint,
    CompetitionMapResponse,
    CompetitorMenuItemInput,
    CompetitorSnapshotInput,
)
from app.services.agents import _distance_m
from app.services.store_state import build_store_state

AMAP_AROUND_URL = "https://restapi.amap.com/v5/place/around"
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"


class CompetitionSourceError(RuntimeError):
    pass


@dataclass
class DiscoveredCompetitor:
    external_id: str
    name: str
    category: str | None = None
    area: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    review_count: int | None = None
    price_band_min: float | None = None
    price_band_max: float | None = None
    source_url: str | None = None
    menu_items: list[CompetitorMenuItemInput] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


class CompetitionSource(Protocol):
    provider: str

    def discover(self, store: Store) -> list[DiscoveredCompetitor]: ...


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, "", []):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        if value in (None, "", []):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalized_name(value: str) -> str:
    return "".join(char for char in value.strip().lower() if char.isalnum())


class AmapCompetitionSource:
    provider = "amap"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: int = 15,
        max_pages: int = 5,
    ):
        from app.services.settings_store import get_setting

        self.api_key = api_key or get_setting("amap_web_service_key") or settings.amap_web_service_key
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages

    def _ensure_store_coordinates(self, store: Store) -> None:
        if store.longitude is not None and store.latitude is not None:
            return
        address = store.address or "".join(
            part for part in (store.city, store.area, store.name) if part
        )
        if not address:
            raise CompetitionSourceError("门店缺少地址和经纬度，无法执行周边搜索")
        params = {
            "key": self.api_key,
            "address": address,
            "city": store.city or "",
        }
        request = Request(
            f"{AMAP_GEOCODE_URL}?{urlencode(params)}",
            headers={"User-Agent": "MealKey-AI/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CompetitionSourceError(f"门店地址地理编码失败：{exc}") from exc
        geocodes = payload.get("geocodes") or []
        location = str(geocodes[0].get("location") if geocodes else "").split(",")
        if str(payload.get("status")) != "1" or len(location) != 2:
            raise CompetitionSourceError("门店地址无法解析为有效经纬度")
        longitude = _as_float(location[0])
        latitude = _as_float(location[1])
        if longitude is None or latitude is None:
            raise CompetitionSourceError("门店地址返回了无效经纬度")
        store.longitude = longitude
        store.latitude = latitude

    def discover(self, store: Store) -> list[DiscoveredCompetitor]:
        if not self.api_key:
            raise CompetitionSourceError("未配置 AMAP_WEB_SERVICE_KEY")
        self._ensure_store_coordinates(store)

        base_params = {
            "key": self.api_key,
            "location": f"{store.longitude:.6f},{store.latitude:.6f}",
            "types": "050000",
            "radius": str(store.delivery_radius_m or 3000),
            "sortrule": "distance",
            "page_size": "25",
            "show_fields": "business",
        }
        pois: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for page_number in range(1, self.max_pages + 1):
            params = {**base_params, "page_num": str(page_number)}
            request = Request(
                f"{AMAP_AROUND_URL}?{urlencode(params)}",
                headers={"User-Agent": "MealKey-AI/1.0"},
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                raise CompetitionSourceError(f"高德周边搜索失败：{exc}") from exc
            if str(payload.get("status")) != "1":
                message = payload.get("info") or payload.get("infocode") or "未知错误"
                raise CompetitionSourceError(f"高德周边搜索返回错误：{message}")
            page_pois = payload.get("pois") or []
            for poi in page_pois:
                identity = str(poi.get("id") or poi.get("location") or poi.get("name"))
                if identity not in seen_ids:
                    seen_ids.add(identity)
                    pois.append(poi)
            if len(page_pois) < 25:
                break

        discovered: list[DiscoveredCompetitor] = []
        for poi in pois:
            location = str(poi.get("location") or "").split(",")
            if len(location) != 2:
                continue
            longitude = _as_float(location[0])
            latitude = _as_float(location[1])
            if longitude is None or latitude is None:
                continue
            business = poi.get("business") if isinstance(poi.get("business"), dict) else {}
            average_cost = _as_float(business.get("cost"))
            rating = _as_float(business.get("rating"))
            discovered.append(
                DiscoveredCompetitor(
                    external_id=str(poi.get("id") or f"{longitude},{latitude}:{poi.get('name')}"),
                    name=str(poi.get("name") or "未命名餐饮门店"),
                    category=str(poi.get("type") or "").split(";")[-1] or None,
                    area=str(poi.get("adname") or store.area or "") or None,
                    latitude=latitude,
                    longitude=longitude,
                    rating=rating if rating is None or 0 <= rating <= 5 else None,
                    price_band_min=round(average_cost * 0.8, 2) if average_cost else None,
                    price_band_max=round(average_cost * 1.2, 2) if average_cost else None,
                    source_url=f"https://www.amap.com/place/{poi.get('id')}" if poi.get("id") else None,
                    raw_payload=poi,
                )
            )
        return discovered


class LicensedPartnerCompetitionSource:
    provider = "licensed_partner"

    def __init__(
        self,
        api_url: str | None = None,
        api_token: str | None = None,
        timeout_seconds: int = 30,
    ):
        from app.services.settings_store import get_setting

        self.api_url = api_url or get_setting("competition_partner_api_url") or settings.competition_partner_api_url
        self.api_token = (
            api_token or get_setting("competition_partner_api_token") or settings.competition_partner_api_token
        )
        self.timeout_seconds = timeout_seconds

    def discover(self, store: Store) -> list[DiscoveredCompetitor]:
        if not self.api_url or not self.api_token:
            raise CompetitionSourceError(
                "未配置 COMPETITION_PARTNER_API_URL/TOKEN"
            )
        if store.longitude is None or store.latitude is None:
            raise CompetitionSourceError("门店缺少经纬度，无法查询竞品数据")
        request_payload = {
            "store_id": store.id,
            "name": store.name,
            "category": store.merchant.category if store.merchant else None,
            "latitude": store.latitude,
            "longitude": store.longitude,
            "radius_m": store.delivery_radius_m or 3000,
        }
        request = Request(
            self.api_url,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "User-Agent": "MealKey-AI/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CompetitionSourceError(f"授权竞品数据源请求失败：{exc}") from exc

        rows = payload.get("competitors") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise CompetitionSourceError("授权竞品数据源响应缺少 competitors 数组")
        discovered: list[DiscoveredCompetitor] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("external_id") or not row.get("name"):
                continue
            menu_items = [
                CompetitorMenuItemInput.model_validate(item)
                for item in (row.get("menu_items") or [])
                if isinstance(item, dict)
            ]
            discovered.append(
                DiscoveredCompetitor(
                    external_id=str(row["external_id"]),
                    name=str(row["name"]),
                    category=row.get("category"),
                    area=row.get("area"),
                    latitude=_as_float(row.get("latitude")),
                    longitude=_as_float(row.get("longitude")),
                    rating=_as_float(row.get("rating")),
                    review_count=_as_int(row.get("review_count")),
                    price_band_min=_as_float(row.get("price_band_min")),
                    price_band_max=_as_float(row.get("price_band_max")),
                    source_url=row.get("source_url"),
                    menu_items=menu_items,
                    raw_payload=row,
                )
            )
        return discovered


def get_competition_source(provider: str) -> CompetitionSource:
    if provider == "amap":
        return AmapCompetitionSource()
    if provider == "licensed_partner":
        return LicensedPartnerCompetitionSource()
    raise ValueError(f"unsupported competition provider: {provider}")


def backfill_legacy_competitor_watches(db: Session) -> int:
    """One-time compatibility path for databases created before watch links."""
    created_count = 0
    stores = list(db.execute(select(Store)).scalars())
    for store in stores:
        existing_ids = set(
            db.execute(
                select(StoreCompetitorWatch.c_store_id).where(
                    StoreCompetitorWatch.store_id == store.id
                )
            ).scalars()
        )
        if existing_ids:
            continue
        competitors = list(
            db.execute(
                select(CompetitorStore).where(
                    CompetitorStore.area == store.area
                )
            ).scalars()
        )
        for competitor in competitors:
            db.add(
                StoreCompetitorWatch(
                    store_id=store.id,
                    c_store_id=competitor.id,
                    provider=competitor.platform or "legacy",
                    distance_m=_distance_m(
                        store.latitude,
                        store.longitude,
                        competitor.latitude,
                        competitor.longitude,
                    ),
                    active=True,
                )
            )
            created_count += 1
    if created_count:
        db.commit()
    return created_count


def _raw_checksum(payload: dict[str, Any]) -> tuple[str, str]:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def ingest_competitor_snapshot(
    db: Session,
    store: Store,
    payload: CompetitorSnapshotInput,
    run_id: str | None = None,
) -> CompetitorStore:
    competitor_stmt = select(CompetitorStore).where(
        CompetitorStore.platform == payload.provider,
        CompetitorStore.platform_store_key == payload.external_id,
    )
    competitor = db.execute(competitor_stmt).scalar_one_or_none()
    if competitor is None:
        competitor = CompetitorStore(
            area=payload.area or store.area,
            name=payload.name,
            category=payload.category,
            latitude=payload.latitude,
            longitude=payload.longitude,
            platform=payload.provider,
            platform_store_key=payload.external_id,
        )
        db.add(competitor)
        db.flush()
    else:
        competitor.name = payload.name
        competitor.area = payload.area or competitor.area or store.area
        competitor.category = payload.category or competitor.category
        competitor.latitude = payload.latitude if payload.latitude is not None else competitor.latitude
        competitor.longitude = payload.longitude if payload.longitude is not None else competitor.longitude

    captured_at = payload.captured_at or datetime.now(timezone.utc)
    watch_stmt = select(StoreCompetitorWatch).where(
        StoreCompetitorWatch.store_id == store.id,
        StoreCompetitorWatch.c_store_id == competitor.id,
    )
    watch = db.execute(watch_stmt).scalar_one_or_none()
    distance = _distance_m(
        store.latitude,
        store.longitude,
        competitor.latitude,
        competitor.longitude,
    )
    if watch is None:
        watch = StoreCompetitorWatch(
            store_id=store.id,
            c_store_id=competitor.id,
            provider=payload.provider,
            distance_m=distance,
            active=True,
            first_seen_at=captured_at,
            last_seen_at=captured_at,
        )
        db.add(watch)
    else:
        watch.provider = payload.provider
        watch.distance_m = distance
        watch.active = True
        watch.last_seen_at = captured_at

    snapshot = CompetitorSnapshot(
        c_store_id=competitor.id,
        captured_at=captured_at,
        rating=payload.rating,
        review_count=payload.review_count,
        price_band_min=payload.price_band_min,
        price_band_max=payload.price_band_max,
    )
    db.add(snapshot)
    db.flush()
    for item in payload.menu_items:
        db.add(
            CompetitorMenuItem(
                snapshot_id=snapshot.id,
                name=item.name,
                category=item.category,
                price=item.price,
                image_url=item.image_url,
                rating=item.rating,
            )
        )

    raw_payload = payload.raw_payload or payload.model_dump(mode="json")
    serialized, checksum = _raw_checksum(raw_payload)
    db.add(
        CompetitorRawPayload(
            run_id=run_id,
            store_id=store.id,
            provider=payload.provider,
            external_id=payload.external_id,
            source_url=payload.source_url,
            captured_at=captured_at,
            payload_json=serialized,
            checksum=checksum,
        )
    )
    return competitor


def collect_store_competitors(
    db: Session,
    store_id: str,
    source: CompetitionSource | None = None,
) -> CompetitionCollectionResult:
    store = db.get(Store, store_id)
    if store is None:
        raise ValueError("store not found")

    source = source or AmapCompetitionSource()
    run = CompetitionCollectionRun(
        store_id=store.id,
        provider=source.provider,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    discovered_count = 0
    snapshot_count = 0
    skipped_count = 0
    try:
        rows = source.discover(store)
        discovered_count = len(rows)
        own_name = _normalized_name(store.name)
        merchant_name = _normalized_name(store.merchant.name) if store.merchant else ""
        for row in rows:
            row_name = _normalized_name(row.name)
            distance = _distance_m(
                store.latitude,
                store.longitude,
                row.latitude,
                row.longitude,
            )
            if row_name in {own_name, merchant_name} or (distance is not None and distance < 30):
                skipped_count += 1
                continue
            ingest_competitor_snapshot(
                db,
                store,
                CompetitorSnapshotInput(
                    provider=source.provider,
                    external_id=row.external_id,
                    name=row.name,
                    category=row.category,
                    # area 表示本店的竞争分析圈层；高德 adname 保留在 raw_payload。
                    area=store.area,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    rating=row.rating,
                    review_count=row.review_count,
                    price_band_min=row.price_band_min,
                    price_band_max=row.price_band_max,
                    source_url=row.source_url,
                    menu_items=row.menu_items,
                    raw_payload=row.raw_payload,
                ),
                run_id=run.id,
            )
            snapshot_count += 1
        run.status = "completed"
        run.discovered_count = discovered_count
        run.snapshot_count = snapshot_count
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_run = db.get(CompetitionCollectionRun, run.id)
        if failed_run is None:
            failed_run = CompetitionCollectionRun(
                id=run.id,
                store_id=store.id,
                provider=source.provider,
            )
            db.add(failed_run)
        failed_run.status = "failed"
        failed_run.error = str(exc)[:1000]
        failed_run.discovered_count = discovered_count
        failed_run.snapshot_count = snapshot_count
        failed_run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return CompetitionCollectionResult(
            run_id=run.id,
            store_id=store.id,
            provider=source.provider,
            status="failed",
            discovered_count=discovered_count,
            snapshot_count=snapshot_count,
            skipped_count=skipped_count,
            error=str(exc),
        )

    return CompetitionCollectionResult(
        run_id=run.id,
        store_id=store.id,
        provider=source.provider,
        status="completed",
        discovered_count=discovered_count,
        snapshot_count=snapshot_count,
        skipped_count=skipped_count,
    )


def build_competition_map(db: Session, store_id: str) -> CompetitionMapResponse | None:
    store = db.get(Store, store_id)
    if store is None or store.latitude is None or store.longitude is None:
        return None

    state = build_store_state(db, store_id)
    changes_by_competitor: dict[str, str] = {}
    if state:
        for change in state.competition_changes:
            changes_by_competitor.setdefault(change.c_store_id, change.summary)

    watched_ids = list(
        db.execute(
            select(StoreCompetitorWatch.c_store_id).where(
                StoreCompetitorWatch.store_id == store.id,
                StoreCompetitorWatch.active.is_(True),
            )
        ).scalars()
    )
    competitor_stmt = select(CompetitorStore).where(
        CompetitorStore.id.in_(watched_ids)
    )
    competitors = list(db.execute(competitor_stmt).scalars())
    points: list[CompetitionMapPoint] = []
    for competitor in competitors:
        if competitor.latitude is None or competitor.longitude is None:
            continue
        latest = db.execute(
            select(CompetitorSnapshot)
            .where(CompetitorSnapshot.c_store_id == competitor.id)
            .order_by(CompetitorSnapshot.captured_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        price_band = None
        if latest and latest.price_band_min is not None and latest.price_band_max is not None:
            price_band = f"{latest.price_band_min:g}-{latest.price_band_max:g}"
        points.append(
            CompetitionMapPoint(
                competitor_id=competitor.id,
                name=competitor.name,
                latitude=competitor.latitude,
                longitude=competitor.longitude,
                distance_m=_distance_m(
                    store.latitude,
                    store.longitude,
                    competitor.latitude,
                    competitor.longitude,
                ),
                category=competitor.category,
                rating=latest.rating if latest else None,
                price_band=price_band,
                latest_change=changes_by_competitor.get(competitor.id),
            )
        )
    points.sort(key=lambda row: row.distance_m if row.distance_m is not None else 10**9)
    return CompetitionMapResponse(
        store_id=store.id,
        store_name=store.name,
        center_latitude=store.latitude,
        center_longitude=store.longitude,
        radius_m=store.delivery_radius_m or 3000,
        generated_at=datetime.now(timezone.utc),
        competitors=points,
    )
