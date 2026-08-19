from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ItemFunnelDaily, Menu, MenuItem, MenuItemVersion, ReviewFact, ShopFunnelDaily, Store
from app.models.settings import PlatformConnection
from app.services.truth_resolution import may_write_funnel_truth
from app.services.platform_connectors import (
    PlatformDailyMetric,
    PlatformMenuItem,
    PlatformReview,
    PlatformSnapshot,
    fetch_platform_snapshot,
)


def _ensure_menu(db: Session, store_id: str) -> Menu:
    menu = db.execute(
        select(Menu).where(Menu.store_id == store_id, Menu.status == "active").order_by(Menu.created_at.asc()).limit(1)
    ).scalar_one_or_none()
    if menu is None:
        menu = Menu(store_id=store_id, name="默认菜单", type="delivery", version=1, status="active")
        db.add(menu)
        db.flush()
    return menu


def apply_platform_snapshot(db: Session, store: Store, snapshot: PlatformSnapshot) -> dict[str, Any]:
    menu = _ensure_menu(db, store.id)
    existing_items = db.execute(select(MenuItem).where(MenuItem.store_id == store.id)).scalars().all()
    name_to_item: dict[str, MenuItem] = {}
    for item in existing_items:
        version = item.current_version
        if version and version.name:
            name_to_item[version.name.strip()] = item

    created_or_updated = 0
    item_ids: list[str] = []
    for row in snapshot.menu_items:
        name = row.name.strip()
        if not name:
            continue
        item = name_to_item.get(name)
        if item is None:
            item = MenuItem(store_id=store.id, menu_id=menu.id, is_active=True)
            db.add(item)
            db.flush()
            name_to_item[name] = item
        version = MenuItemVersion(
            item_id=item.id,
            name=name,
            category=row.category,
            price=row.price,
            description=row.description,
            image_url=row.image_url,
            source=f"platform:{snapshot.platform}",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        item.is_active = True
        db.add(item)
        item_ids.append(item.id)
        created_or_updated += 1

    metric_days = 0
    raw_meta = snapshot.raw if isinstance(snapshot.raw, dict) else {}
    test_only_snapshot = raw_meta.get("truth_eligible") is False or raw_meta.get("provenance") == "TEST_ONLY"
    if test_only_snapshot:
        from app.services.daily_report_test_connector import incoming_funnel_source_for_snapshot

        incoming_source_default = incoming_funnel_source_for_snapshot(snapshot)
    else:
        incoming_source_default = "synthetic" if snapshot.synthetic else "platform_sync"
    for metric in snapshot.daily_metrics:
        incoming_source = incoming_source_default
        existing = db.execute(
            select(ShopFunnelDaily).where(ShopFunnelDaily.store_id == store.id, ShopFunnelDaily.day == metric.day)
        ).scalar_one_or_none()
        if existing is not None and not may_write_funnel_truth(existing.data_source, incoming_source):
            continue
        db.merge(
            ShopFunnelDaily(
                store_id=store.id,
                day=metric.day,
                impressions=metric.impressions,
                visits=metric.visits,
                add_to_cart=metric.add_to_cart,
                payments=metric.payments,
                orders=metric.orders,
                gmv=metric.gmv,
                aov=metric.aov,
                data_source=incoming_source,
            )
        )
        metric_days += 1
        if item_ids and metric.orders:
            primary = item_ids[0]
            rest = item_ids[1:]
            primary_weight = 0.55
            rest_weight = (1.0 - primary_weight) / max(len(rest), 1)
            for index, item_id in enumerate(item_ids):
                weight = primary_weight if index == 0 else rest_weight
                item_orders = max(1, int(round(metric.orders * weight)))
                item_impressions = max(item_orders * 8, int(round(metric.impressions * weight)))
                item_visits = max(item_orders * 2, int(round(metric.visits * weight)))
                item_gmv = round(metric.gmv * weight, 2)
                db.merge(
                    ItemFunnelDaily(
                        item_id=item_id,
                        day=metric.day,
                        impressions=item_impressions,
                        visits=item_visits,
                        orders=item_orders,
                        gmv=item_gmv,
                        ctr=round(item_visits / item_impressions, 4) if item_impressions else None,
                        cvr=round(item_orders / item_visits, 4) if item_visits else None,
                        data_source="synthetic",
                    )
                )

    reviews_upserted = _upsert_snapshot_reviews(db, store.id, snapshot)

    store.platform = snapshot.platform
    store.platform_store_key = snapshot.external_store_id
    if snapshot.store_name and not store.name:
        store.name = snapshot.store_name
    db.add(store)

    connection = db.execute(
        select(PlatformConnection).where(
            PlatformConnection.store_id == store.id,
            PlatformConnection.platform == snapshot.platform,
        )
    ).scalar_one_or_none()
    if connection is None:
        connection = PlatformConnection(store_id=store.id, platform=snapshot.platform)
        db.add(connection)
    meta = _load_meta(connection.meta_json)
    raw_meta = snapshot.raw if isinstance(snapshot.raw, dict) else {}
    source_mode = str(raw_meta.get("source") or "").strip().lower()
    if source_mode not in {"mobile", "oauth", "http", "mock", "human_paste"}:
        if snapshot.synthetic:
            source_mode = "mock"
        else:
            source_mode = connection.connector_mode or "http"
        if source_mode == "mock" and not snapshot.synthetic:
            source_mode = "http"
    from app.services.connector_mode import allows_mock

    if source_mode == "mock" and not allows_mock():
        source_mode = connection.connector_mode if connection.connector_mode not in {"mock", "fixture", "sandbox"} else "http"
    connection.status = "connected"
    connection.external_store_id = snapshot.external_store_id
    connection.connector_mode = source_mode
    connection.last_sync_at = datetime.now(timezone.utc)
    connection.last_error = None
    meta.update(
        {
            "synthetic": snapshot.synthetic,
            "menu_count": created_or_updated,
            "metric_days": metric_days,
            "reviews": reviews_upserted,
            "source": source_mode,
        }
    )
    if raw_meta:
        meta["snapshot_keys"] = sorted(str(key) for key in raw_meta.keys())[:24]
    connection.meta_json = json.dumps(meta, ensure_ascii=False)
    db.add(connection)
    db.flush()

    return {
        "store_id": store.id,
        "platform": snapshot.platform,
        "external_store_id": snapshot.external_store_id,
        "menu_upserted": created_or_updated,
        "metric_days": metric_days,
        "reviews_upserted": reviews_upserted,
        "synthetic": snapshot.synthetic,
        "connection_id": connection.id,
    }


def sync_store_platform(
    db: Session,
    store: Store,
    platform: str,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    from app.services.connector_mode import resolve_fetch_mode

    connection = db.execute(
        select(PlatformConnection).where(
            PlatformConnection.store_id == store.id,
            PlatformConnection.platform == platform,
        )
    ).scalar_one_or_none()
    use_mode = resolve_fetch_mode(
        requested=mode,
        connection_mode=connection.connector_mode if connection else None,
    )
    snapshot = fetch_platform_snapshot(
        platform,
        store_id=store.id,
        mode=use_mode,
        store_name=store.name,
        external_store_id=store.platform_store_key,
    )
    if connection is None:
        connection = PlatformConnection(
            store_id=store.id,
            platform=platform,
            status="pending",
            connector_mode=use_mode,
        )
        db.add(connection)
        db.flush()
    connection.connector_mode = use_mode
    try:
        result = apply_platform_snapshot(db, store, snapshot)
        result["mode"] = use_mode
        return result
    except Exception as exc:  # noqa: BLE001 - surface to API
        from app.services.connector_mode import (
            AUTH_REQUIRED,
            PLATFORM_UNAVAILABLE,
            SCHEMA_CHANGED,
            classify_connector_failure,
        )

        classified = classify_connector_failure(exc)
        connection.status = {
            AUTH_REQUIRED: "auth_required",
            SCHEMA_CHANGED: "schema_changed",
            PLATFORM_UNAVAILABLE: "unavailable",
        }.get(classified.code, "degraded")
        connection.last_error = f"{classified.code}: {classified}"
        db.add(connection)
        raise classified from exc


# ═══ P2-7: 多平台数据对齐 ═══


def _upsert_snapshot_reviews(db: Session, store_id: str, snapshot: PlatformSnapshot) -> int:
    upserted = 0
    for review in snapshot.reviews or []:
        review_id = str(review.review_id or "").strip()
        if not review_id:
            continue
        source = f"platform:{snapshot.platform}:{review_id}"
        existing = db.execute(
            select(ReviewFact).where(ReviewFact.store_id == store_id, ReviewFact.source == source).limit(1)
        ).scalar_one_or_none()
        if existing is None:
            existing = ReviewFact(
                store_id=store_id,
                rating=float(review.rating or 0) or None,
                content=review.content or "",
                reviewed_at=datetime.now(timezone.utc),
                source=source,
            )
            db.add(existing)
        else:
            existing.rating = float(review.rating or existing.rating or 0) or existing.rating
            existing.content = review.content or existing.content
        if review.replied and review.reply_text:
            existing.reply_text = review.reply_text
            existing.replied_at = existing.replied_at or datetime.now(timezone.utc)
        upserted += 1
    return upserted


def merge_multi_platform_snapshots(
    snapshots: list[Any],
) -> PlatformSnapshot:
    """把美团+饿了么+抖音等多个平台的 snapshot 合并成一个统一视图。

    合并规则：
    - menu_items: 按名称去重合并（同名取价格更高的）
    - daily_metrics: 按日期合并（orders/gmv 相加）
    - reviews: 按 review_id 去重
    - store_name: 取第一个
    """
    if not snapshots:
        return PlatformSnapshot(platform="multi", external_store_id="", store_name="", menu_items=[], daily_metrics=[])
    if len(snapshots) == 1:
        return snapshots[0]

    seen_names: dict[str, PlatformMenuItem] = {}
    for snap in snapshots:
        for item in snap.menu_items:
            name_key = item.name.strip().lower()
            if name_key not in seen_names:
                seen_names[name_key] = item
            elif (item.price or 0) > (seen_names[name_key].price or 0):
                seen_names[name_key] = item

    metrics_by_day: dict[Any, dict] = {}
    for snap in snapshots:
        for metric in snap.daily_metrics:
            day = metric.day
            if day not in metrics_by_day:
                metrics_by_day[day] = {
                    "day": day,
                    "impressions": 0,
                    "visits": 0,
                    "add_to_cart": 0,
                    "payments": 0,
                    "orders": 0,
                    "gmv": 0.0,
                }
            bucket = metrics_by_day[day]
            bucket["impressions"] += metric.impressions or 0
            bucket["visits"] += metric.visits or 0
            bucket["add_to_cart"] += metric.add_to_cart or 0
            bucket["payments"] += metric.payments or 0
            bucket["orders"] += metric.orders or 0
            bucket["gmv"] += metric.gmv or 0.0
            if bucket["orders"]:
                bucket["aov"] = round(bucket["gmv"] / bucket["orders"], 2)

    reviews_by_id: dict[str, PlatformReview] = {}
    for snap in snapshots:
        for review in snap.reviews or []:
            key = str(review.review_id or "").strip()
            if key and key not in reviews_by_id:
                reviews_by_id[key] = review

    return PlatformSnapshot(
        platform="multi",
        external_store_id=",".join(s.external_store_id for s in snapshots if s.external_store_id),
        store_name=snapshots[0].store_name,
        menu_items=list(seen_names.values()),
        daily_metrics=[PlatformDailyMetric(**m) for m in metrics_by_day.values()],
        reviews=list(reviews_by_id.values()),
        synthetic=any(bool(getattr(s, "synthetic", False)) for s in snapshots),
    )


def sync_all_platforms(
    db: Session,
    store: Store,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """拉取该店已连接的全部平台，合并后再写入 StoreState 事实表。"""
    connections = db.execute(
        select(PlatformConnection).where(PlatformConnection.store_id == store.id)
    ).scalars().all()
    platforms = [row.platform for row in connections if row.platform]
    if not platforms:
        platforms = [store.platform or "meituan"]

    snapshots: list[PlatformSnapshot] = []
    errors: list[dict[str, str]] = []
    for platform in platforms:
        conn = next((row for row in connections if row.platform == platform), None)
        try:
            from app.services.connector_mode import resolve_fetch_mode

            use_mode = resolve_fetch_mode(
                requested=mode,
                connection_mode=conn.connector_mode if conn else None,
            )
        except Exception as exc:  # ConnectorModeError
            errors.append({"platform": platform, "error": str(exc)})
            if conn is not None:
                conn.status = "error"
                conn.last_error = str(exc)
                db.add(conn)
            continue
        try:
            snapshots.append(
                fetch_platform_snapshot(
                    platform,
                    store_id=store.id,
                    mode=use_mode,
                    store_name=store.name,
                    external_store_id=(conn.external_store_id if conn else store.platform_store_key),
                )
            )
        except Exception as exc:  # noqa: BLE001
            from app.services.connector_mode import (
                AUTH_REQUIRED,
                PLATFORM_UNAVAILABLE,
                SCHEMA_CHANGED,
                classify_connector_failure,
            )

            classified = classify_connector_failure(exc)
            errors.append({"platform": platform, "error": f"{classified.code}: {classified}"})
            if conn is not None:
                conn.status = {
                    AUTH_REQUIRED: "auth_required",
                    SCHEMA_CHANGED: "schema_changed",
                    PLATFORM_UNAVAILABLE: "unavailable",
                }.get(classified.code, "degraded")
                conn.last_error = f"{classified.code}: {classified}"
                db.add(conn)

    if not snapshots:
        raise ValueError("没有可合并的平台数据：" + "；".join(f"{e['platform']}: {e['error']}" for e in errors))

    merged = merge_multi_platform_snapshots(snapshots)
    result = apply_platform_snapshot(db, store, merged)
    result["mode"] = mode or "mixed"
    result["platforms"] = [snap.platform for snap in snapshots]
    result["errors"] = errors
    return result


def _load_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
