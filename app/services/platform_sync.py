from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ItemFunnelDaily, Menu, MenuItem, MenuItemVersion, ShopFunnelDaily, Store
from app.models.settings import PlatformConnection
from app.services.platform_connectors import PlatformSnapshot, fetch_platform_snapshot


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
    for metric in snapshot.daily_metrics:
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
                    )
                )

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
    connection.status = "connected"
    connection.external_store_id = snapshot.external_store_id
    connection.connector_mode = "mock" if snapshot.synthetic else connection.connector_mode or "http"
    connection.last_sync_at = datetime.now(timezone.utc)
    connection.last_error = None
    connection.meta_json = json.dumps(
        {"synthetic": snapshot.synthetic, "menu_count": created_or_updated, "metric_days": metric_days},
        ensure_ascii=False,
    )
    db.add(connection)
    db.flush()

    return {
        "store_id": store.id,
        "platform": snapshot.platform,
        "external_store_id": snapshot.external_store_id,
        "menu_upserted": created_or_updated,
        "metric_days": metric_days,
        "synthetic": snapshot.synthetic,
        "connection_id": connection.id,
    }


def sync_store_platform(
    db: Session,
    store: Store,
    platform: str,
    *,
    mode: str = "mock",
) -> dict[str, Any]:
    snapshot = fetch_platform_snapshot(
        platform,
        store_id=store.id,
        mode=mode,
        store_name=store.name,
        external_store_id=store.platform_store_key,
    )
    connection = db.execute(
        select(PlatformConnection).where(
            PlatformConnection.store_id == store.id,
            PlatformConnection.platform == platform,
        )
    ).scalar_one_or_none()
    if connection is None:
        connection = PlatformConnection(
            store_id=store.id,
            platform=platform,
            status="pending",
            connector_mode=mode,
        )
        db.add(connection)
        db.flush()
    connection.connector_mode = mode
    try:
        result = apply_platform_snapshot(db, store, snapshot)
        result["mode"] = mode
        return result
    except Exception as exc:  # noqa: BLE001 - surface to API
        connection.status = "error"
        connection.last_error = str(exc)
        db.add(connection)
        raise


# ═══ P2-7: 多平台数据对齐 ═══


def merge_multi_platform_snapshots(
    snapshots: list[Any],
) -> PlatformSnapshot:
    """把美团+饿了么+抖音等多个平台的 snapshot 合并成一个统一视图。

    合并规则：
    - menu_items: 按名称去重合并（同名取价格更高的）
    - daily_metrics: 按日期合并（orders/gmv 相加）
    - store_name: 取第一个
    """
    if not snapshots:
        return PlatformSnapshot(platform="multi", external_store_id="", store_name="", menu_items=[], daily_metrics=[])
    if len(snapshots) == 1:
        return snapshots[0]

    # 合并 menu_items
    seen_names: dict[str, PlatformMenuItem] = {}
    for snap in snapshots:
        for item in snap.menu_items:
            name_key = item.name.strip().lower()
            if name_key not in seen_names:
                seen_names[name_key] = item
            else:
                # 同名取价格更高的
                if item.price > seen_names[name_key].price:
                    seen_names[name_key] = item

    # 合并 daily_metrics
    metrics_by_day: dict[str, dict] = {}
    for snap in snapshots:
        for metric in snap.daily_metrics:
            day = metric.day or "unknown"
            if day not in metrics_by_day:
                metrics_by_day[day] = {"day": day, "impressions": 0, "visits": 0, "orders": 0, "gmv": 0.0}
            metrics_by_day[day]["impressions"] += metric.impressions
            metrics_by_day[day]["visits"] += metric.visits
            metrics_by_day[day]["orders"] += metric.orders
            metrics_by_day[day]["gmv"] += metric.gmv

    return PlatformSnapshot(
        platform="multi",
        external_store_id=",".join(s.external_store_id for s in snapshots if s.external_store_id),
        store_name=snapshots[0].store_name,
        menu_items=list(seen_names.values()),
        daily_metrics=[PlatformDailyMetric(**m) for m in metrics_by_day.values()],
    )
