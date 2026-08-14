"""用户测试门店：一次开通经营所需权限。

开通：MOS / 低风险自动 / 投流日限额 / 订阅+钱包 / mock 平台已连接。
不开：真实美团 OAuth、改价/投流/活动写回 allowlist、利润诚实门禁。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commercial import AIWallet, StoreLicense
from app.models.entities import MenuItem, MenuItemVersion, Store
from app.models.settings import PlatformConnection
from app.services.commercial.board import subscribe_cycle, topup_wallet
from app.services.mue.engine import _save, load_understanding
from app.services.mos_engine import check_mos

TEST_ADS_DAILY_LIMIT_CNY = 500.0
TEST_LUNCH_CAPACITY = 40.0
TEST_PROFIT_FLOOR = 0.20
TEST_WALLET_CNY = 500.0


def _mark_platform_connected(db: Session, store: Store) -> str:
    platform = (store.platform or "meituan").strip() or "meituan"
    row = db.execute(
        select(PlatformConnection).where(
            PlatformConnection.store_id == store.id,
            PlatformConnection.platform == platform,
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = PlatformConnection(
            store_id=store.id,
            platform=platform,
            status="connected",
            connector_mode="mock",
            external_store_id=store.platform_store_key,
            connected_at=now,
            last_sync_at=now,
            meta_json=json.dumps({"source": "test_unlock", "synthetic": True}, ensure_ascii=False),
        )
        db.add(row)
    else:
        row.status = "connected"
        if not row.connector_mode:
            row.connector_mode = "mock"
        row.connected_at = row.connected_at or now
        row.last_error = None
        if not row.external_store_id:
            row.external_store_id = store.platform_store_key
    db.flush()
    return platform


def _hero_floor(db: Session, store_id: str) -> dict[str, float]:
    item = db.execute(
        select(MenuItem).where(MenuItem.store_id == store_id, MenuItem.is_active.is_(True)).limit(1)
    ).scalar_one_or_none()
    if item is None or not item.current_version_id:
        return {}
    version = db.execute(
        select(MenuItemVersion).where(MenuItemVersion.id == item.current_version_id)
    ).scalar_one_or_none()
    if version is None or not version.name or not version.price:
        return {}
    return {str(version.name): round(float(version.price) * 0.7, 2)}


def _open_understanding(db: Session, store: Store) -> dict[str, Any]:
    view = load_understanding(db, store.id)
    view.platform_connected = True
    view.store_profile = {**view.store_profile, "platform_connected": True}
    view.onboarding_stage = "operating"
    view.preferences.priority_style = view.preferences.priority_style or "balanced"
    view.preferences.weekend_more_aggressive = bool(view.preferences.weekend_more_aggressive)
    view.constraints.lunch_capacity_per_hour = (
        view.constraints.lunch_capacity_per_hour
        if view.constraints.lunch_capacity_per_hour is not None
        else TEST_LUNCH_CAPACITY
    )
    view.constraints.profit_floor_rate = (
        view.constraints.profit_floor_rate
        if view.constraints.profit_floor_rate is not None
        else TEST_PROFIT_FLOOR
    )
    if not view.constraints.item_min_price:
        floor = _hero_floor(db, store.id)
        if floor:
            view.constraints.item_min_price = floor
    view.permissions.low_risk_auto_ok = True
    view.permissions.auto_reply_good_reviews = True
    view.permissions.monitor_promo_expiry = True
    view.permissions.monitor_stockout = True
    view.permissions.monitor_competitors = True
    if view.permissions.ads_auto_daily_limit_cny is None:
        view.permissions.ads_auto_daily_limit_cny = TEST_ADS_DAILY_LIMIT_CNY
    for fact in view.inferred:
        fact.confirmed = True
    view.open_gaps = []
    view.last_interview_key = None
    saved = _save(db, view)
    satisfied, blocking = check_mos(saved)
    return {
        "mos_satisfied": satisfied,
        "system_mode": saved.system_mode,
        "blocking": blocking,
        "low_risk_auto_ok": saved.permissions.low_risk_auto_ok,
        "ads_auto_daily_limit_cny": saved.permissions.ads_auto_daily_limit_cny,
    }


def _open_commercial(db: Session, store: Store) -> dict[str, Any]:
    license_row = db.execute(select(StoreLicense).where(StoreLicense.store_id == store.id)).scalar_one_or_none()
    if license_row is None or license_row.status != "paid":
        subscribe_cycle(
            db,
            store,
            "monthly",
            payment_method="bank_transfer",
            operator="test_unlock",
            transfer_note="用户测试门店开通",
        )
    wallet = db.execute(select(AIWallet).where(AIWallet.merchant_id == store.merchant_id)).scalar_one_or_none()
    balance = round(float(wallet.balance_cny or 0), 2) if wallet else 0.0
    if balance <= 0:
        topup_wallet(
            db,
            store,
            TEST_WALLET_CNY,
            payment_method="bank_transfer",
            operator="test_unlock",
            transfer_note="用户测试门店开通",
        )
        balance = TEST_WALLET_CNY
    db.commit()
    license_row = db.execute(select(StoreLicense).where(StoreLicense.store_id == store.id)).scalar_one_or_none()
    return {
        "license": getattr(license_row, "status", None),
        "wallet_cny": balance,
    }


def open_test_store_access(db: Session, store: Store) -> dict[str, Any]:
    """把一家店开到可经营：权限全开、MOS 满足、订阅已付、平台 mock 已连。"""
    platform = _mark_platform_connected(db, store)
    understanding = _open_understanding(db, store)
    commercial = _open_commercial(db, store)
    return {
        "store_id": store.id,
        "store_name": store.name,
        "platform": platform,
        "platform_mode": "mock",
        **understanding,
        **commercial,
        "writeback_allowlist_unchanged": True,
        "profit_honesty_unchanged": True,
    }


def open_all_test_stores(db: Session) -> dict[str, Any]:
    stores = list(db.execute(select(Store).where(Store.status == "active")).scalars().all())
    opened = [open_test_store_access(db, store) for store in stores]
    return {"count": len(opened), "stores": opened}
