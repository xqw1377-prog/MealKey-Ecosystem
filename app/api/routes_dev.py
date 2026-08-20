from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.entities import (
    CompetitorMenuItem,
    CompetitorSnapshot,
    CompetitorStore,
    ItemFunnelDaily,
    Menu,
    MenuItem,
    MenuItemVersion,
    Brand,
    Merchant,
    ShopFunnelDaily,
    Store,
    StoreCompetitorWatch,
)
from app.services.daily_report_test_import import (
    import_daily_report_test_records,
    list_daily_report_test_stores,
)

router = APIRouter()


@router.post("/seed")
def seed_demo(db: Session = Depends(get_db)):
    """
    创建一套最小 Demo 数据，方便你立刻跑通：
    StoreState -> daily_job -> OHRE + recommendation

    幂等：若 demo store 已存在则直接返回现有 ids，不重复创建（PRE-PROD-GATE-01 P0-7）。
    """
    if not settings.is_dev:
        raise HTTPException(status_code=403, detail="seed is only available in development")

    existing_store = db.execute(
        select(Store).where(Store.platform_store_key == "demo_store_key")
    ).scalar_one_or_none()
    if existing_store is not None:
        existing_item = db.execute(
            select(MenuItem).where(MenuItem.store_id == existing_store.id).limit(1)
        ).scalar_one_or_none()
        return {
            "merchant_id": existing_store.merchant_id,
            "store_id": existing_store.id,
            "item_id": existing_item.id if existing_item else None,
        }

    merchant = Merchant(name="老王牛肉饭", brand_name="老王牛肉饭", category="快餐", cuisine_type="盖饭")
    db.add(merchant)
    db.flush()
    brand = Brand(
        merchant_id=merchant.id,
        name="老王牛肉饭",
        category="快餐",
        cuisine_type="盖饭",
        status="active",
    )
    db.add(brand)
    db.flush()

    store = Store(
        merchant_id=merchant.id,
        brand_id=brand.id,
        name="老王牛肉饭·国贸店",
        city="北京",
        area="国贸",
        latitude=39.909,
        longitude=116.397,
        delivery_radius_m=2500,
        platform="meituan",
        platform_store_key="demo_store_key",
        primary_audience="写字楼",
        primary_pain="订单下降",
    )
    db.add(store)
    db.flush()

    competitor = CompetitorStore(
        area="国贸",
        name="饭点到·国贸店",
        category="快餐",
        latitude=39.912,
        longitude=116.401,
        platform="meituan",
        platform_store_key="demo_competitor_key",
    )
    db.add(competitor)
    db.flush()
    db.add(
        StoreCompetitorWatch(
            store_id=store.id,
            c_store_id=competitor.id,
            provider="seed",
            distance_m=480,
            active=True,
        )
    )

    captured_at = datetime.now(timezone.utc)
    previous_snapshot = CompetitorSnapshot(
        c_store_id=competitor.id,
        captured_at=captured_at - timedelta(days=1),
        rating=4.4,
        review_count=820,
        price_band_min=26,
        price_band_max=38,
    )
    latest_snapshot = CompetitorSnapshot(
        c_store_id=competitor.id,
        captured_at=captured_at,
        rating=4.7,
        review_count=875,
        price_band_min=25,
        price_band_max=36,
    )
    db.add_all([previous_snapshot, latest_snapshot])
    db.flush()
    db.add_all(
        [
            CompetitorMenuItem(
                snapshot_id=previous_snapshot.id,
                name="招牌鸡腿饭",
                category="主食",
                price=30,
                image_url="https://example.com/chicken-v1.jpg",
                rating=4.5,
            ),
            CompetitorMenuItem(
                snapshot_id=previous_snapshot.id,
                name="鸡腿饭+饮料套餐",
                category="套餐",
                price=36,
                image_url="https://example.com/combo-v1.jpg",
                rating=4.4,
            ),
            CompetitorMenuItem(
                snapshot_id=latest_snapshot.id,
                name="招牌鸡腿饭",
                category="主食",
                price=29,
                image_url="https://example.com/chicken-v2.jpg",
                rating=4.8,
            ),
            CompetitorMenuItem(
                snapshot_id=latest_snapshot.id,
                name="鸡腿饭+饮料套餐",
                category="套餐",
                price=35,
                image_url="https://example.com/combo-v1.jpg",
                rating=4.6,
            ),
            CompetitorMenuItem(
                snapshot_id=latest_snapshot.id,
                name="双拼午餐套餐",
                category="套餐",
                price=36,
                image_url="https://example.com/lunch-combo.jpg",
                rating=4.7,
            ),
        ]
    )

    menu = Menu(store_id=store.id, name="默认菜单", version=1, status="active")
    db.add(menu)
    db.flush()

    item = MenuItem(store_id=store.id, menu_id=menu.id, is_active=True)
    db.add(item)
    db.flush()

    v1 = MenuItemVersion(
        item_id=item.id,
        name="黑椒牛肉饭",
        category="主食",
        price=32.0,
        description="厚切牛肉，现炒锅气",
        source="seed",
    )
    db.add(v1)
    db.flush()
    item.current_version_id = v1.id

    today = date.today()
    # build 14 days: last 7 is worse (ctr down)
    # PRE-PROD-GATE-01 P0-7 / Truth Contract：demo funnel 数据显式标 "synthetic"。
    # NULL=历史未知来源；synthetic=明确知道是假数据。两者都不进 production_funnel_clause，
    # 但 synthetic 审计语义更清楚：demo 永不伪装成真实平台导出，永不成为 production Truth。
    for i in range(14):
        d = today - timedelta(days=i + 1)
        in_last7 = i < 7
        impressions = 1200 if in_last7 else 1100
        visits = int(impressions * (0.04 if in_last7 else 0.048))  # ctr down
        orders = int(visits * (0.18 if in_last7 else 0.19))
        gmv = float(orders * 32.0)

        db.add(
            ShopFunnelDaily(
                store_id=store.id,
                day=d,
                impressions=impressions,
                visits=visits,
                payments=orders,
                orders=orders,
                gmv=gmv,
                aov=32.0,
                data_source="synthetic",
            )
        )

        db.add(
            ItemFunnelDaily(
                item_id=item.id,
                day=d,
                impressions=impressions,
                visits=visits,
                orders=orders,
                payments=orders,
                gmv=gmv,
                ctr=(visits / impressions) if impressions else None,
                cvr=(orders / visits) if visits else None,
                data_source="synthetic",
            )
        )

    db.commit()
    return {"merchant_id": merchant.id, "store_id": store.id, "item_id": item.id}


def _render_daily_report_test_view(stores: list[dict]) -> str:
    rows: list[str] = []
    for store in stores:
        connections_html = "".join(
            f"""
            <li>
              <strong>{escape(str(conn.get("platform") or "--"))}</strong>
              <span>{escape(str(conn.get("latest_record_date") or "--"))}</span>
              <span>{int(conn.get("record_count") or 0)} 条</span>
              <pre>{escape(str(conn.get("latest_record") or {}))}</pre>
            </li>
            """
            for conn in store.get("connections") or []
        )
        rows.append(
            f"""
            <section class="store-card">
              <h2>{escape(str(store.get("store_name") or "--"))}</h2>
              <p>本地 store_id：<code>{escape(str(store.get("store_id") or "--"))}</code></p>
              <p>远端 store_id：<code>{escape(str(store.get("remote_store_id") or "--"))}</code></p>
              <p>最近日期：{escape(str(store.get("latest_record_date") or "--"))}，累计 {int(store.get("record_count") or 0)} 条</p>
              <ul>{connections_html or "<li>暂无连接</li>"}</ul>
            </section>
            """
        )
    body = "".join(rows) or "<p>还没有导入任何测试日报门店。</p>"
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>日报测试源调试页</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 24px; background: #0f172a; color: #e2e8f0; }}
      a {{ color: #93c5fd; }}
      code, pre {{ background: #111827; color: #e5e7eb; border-radius: 6px; padding: 4px 6px; }}
      pre {{ white-space: pre-wrap; word-break: break-word; padding: 12px; }}
      .store-card {{ border: 1px solid #334155; border-radius: 12px; padding: 16px; margin: 12px 0; background: #111827; }}
      ul {{ padding-left: 20px; }}
      li {{ margin: 12px 0; }}
      .hint {{ color: #94a3b8; }}
    </style>
  </head>
  <body>
    <h1>日报测试源调试页</h1>
    <p class="hint">这里只展示落到本地的 TEST_ONLY 门店与原始预览记录，不写入首页经营真相。</p>
    <p>JSON 接口：<a href="/dev/daily-report-test/stores">/dev/daily-report-test/stores</a></p>
    {body}
  </body>
</html>
"""


@router.post("/daily-report-test/import")
def import_daily_report_test(
    page_size: int = Query(default=100, ge=1, le=500),
    page: int = Query(default=1, ge=1),
    remote_store_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """DEV only: 把测试日报记录落成本地调试门店，但不写生产漏斗。"""
    if not settings.is_dev:
        raise HTTPException(status_code=403, detail="daily-report-test import is only available in development")
    result = import_daily_report_test_records(
        db,
        page_size=page_size,
        page=page,
        remote_store_id=(remote_store_id or None),
    )
    db.commit()
    return result


@router.get("/daily-report-test/stores")
def get_daily_report_test_stores(db: Session = Depends(get_db)):
    if not settings.is_dev:
        raise HTTPException(status_code=403, detail="daily-report-test view is only available in development")
    return {"stores": list_daily_report_test_stores(db)}


@router.get("/daily-report-test/view", response_class=HTMLResponse)
def view_daily_report_test_stores(db: Session = Depends(get_db)):
    if not settings.is_dev:
        raise HTTPException(status_code=403, detail="daily-report-test view is only available in development")
    return HTMLResponse(_render_daily_report_test_view(list_daily_report_test_stores(db)))


@router.post("/open-test-access")
def open_test_access(store_id: str = "", db: Session = Depends(get_db)):
    """用户测试门店：开通 MOS / 自动权限 / 订阅 / mock 平台连接。生产环境不可用。"""
    if not settings.is_dev:
        raise HTTPException(status_code=403, detail="open-test-access is only available in development")
    from app.services.test_store_access import open_all_test_stores, open_test_store_access

    sid = (store_id or "").strip()
    if sid:
        store = db.execute(select(Store).where(Store.id == sid)).scalar_one_or_none()
        if store is None:
            raise HTTPException(status_code=404, detail="store not found")
        return {"count": 1, "stores": [open_test_store_access(db, store)]}
    return open_all_test_stores(db)


@router.post("/attribute-experiments/{store_id}")
def attribute_store_experiments(
    store_id: str,
    days: int = 7,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """手动触发实验归因（无 celery 环境也可跑通闭环）。

    - 默认 only_observed=True：只处理观察窗已结束的 pending 实验；
    - force=True：处理该店所有 pending 实验（含观察窗未结束的，用于演示/调试）。
    """
    if not settings.is_dev and not force:
        raise HTTPException(status_code=403, detail="manual attribution is dev-only; use force=true to override")
    from app.services.experiment_attribution import attribute_store_experiments as _run

    outcomes = _run(db, store_id, days=days, only_observed=not force)
    return {
        "store_id": store_id,
        "total": len(outcomes),
        "evaluated": sum(1 for o in outcomes if not o.skipped),
        "skipped": sum(1 for o in outcomes if o.skipped),
        "results": [o.__dict__ for o in outcomes],
    }


@router.post("/sandbox/golden-path")
def sandbox_golden_path(world_id: str = "sb01", db: Session = Depends(get_db)):
    """PLATFORM-SB-01：Twin 改标题黄金路径。结果永远 L0，不进生产 Truth。"""
    if not settings.is_dev:
        raise HTTPException(status_code=403, detail="sandbox is only available in development")
    from app.services.sandbox_golden_path import run_title_golden_path

    return run_title_golden_path(db, world_id=world_id)


@router.post("/attribute-experiments")
def attribute_all_experiments(days: int = 7, db: Session = Depends(get_db)):
    """手动触发全店实验归因。"""
    if not settings.is_dev:
        raise HTTPException(status_code=403, detail="manual attribution is dev-only")
    from app.services.experiment_attribution import attribute_all_stores_experiments

    return attribute_all_stores_experiments(db, days=days)

