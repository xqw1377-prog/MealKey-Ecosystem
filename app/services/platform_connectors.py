from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from app.core.config import settings
from app.services.settings_store import get_setting


SUPPORTED_PLATFORMS = (
    {"key": "meituan", "label": "美团外卖", "modes": ["mock", "http", "mobile"]},
    {"key": "eleme", "label": "饿了么", "modes": ["mock", "http", "mobile"]},
    {"key": "dianping", "label": "大众点评", "modes": ["mock", "mobile"]},
    {"key": "douyin", "label": "抖音生活服务", "modes": ["mock", "mobile"]},
)


@dataclass
class PlatformMenuItem:
    name: str
    category: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None


@dataclass
class PlatformDailyMetric:
    day: date
    impressions: int = 0
    visits: int = 0
    add_to_cart: int = 0
    payments: int = 0
    orders: int = 0
    gmv: float = 0.0
    aov: float = 0.0


@dataclass
class PlatformSnapshot:
    platform: str
    external_store_id: str
    store_name: Optional[str] = None
    menu_items: list[PlatformMenuItem] = field(default_factory=list)
    daily_metrics: list[PlatformDailyMetric] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = False


def list_platforms() -> list[dict[str, Any]]:
    return [
        {
            **row,
            "http_ready": bool(_connector_url()),
            "mock_ready": True,
        }
        for row in SUPPORTED_PLATFORMS
    ]


def _connector_url() -> str:
    return (get_setting("platform_connector_url") or settings.platform_connector_url or "").strip()


def _connector_token() -> str:
    return (get_setting("platform_connector_token") or settings.platform_connector_token or "").strip()


def _mock_metrics(days: int = 14) -> list[PlatformDailyMetric]:
    today = date.today()
    rows: list[PlatformDailyMetric] = []
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        # 近 7 天略差，方便诊断演示
        fade = 0.86 if offset <= 7 else 1.0
        impressions = int(4200 * fade)
        visits = int(980 * fade)
        orders = int(126 * fade)
        gmv = round(orders * 38.5, 2)
        rows.append(
            PlatformDailyMetric(
                day=day,
                impressions=impressions,
                visits=visits,
                add_to_cart=int(visits * 0.42),
                payments=orders,
                orders=orders,
                gmv=gmv,
                aov=round(gmv / orders, 2) if orders else 0,
            )
        )
    return rows


def fetch_mock_snapshot(platform: str, store_name: str | None = None) -> PlatformSnapshot:
    menus = {
        "meituan": [
            PlatformMenuItem("招牌牛肉盖饭", "主食", 28, "份量足，适合白领午餐"),
            PlatformMenuItem("番茄牛腩饭", "主食", 32, "汤汁浓郁"),
            PlatformMenuItem("双人工作日套餐", "套餐", 49, "两荤一素+饮品"),
            PlatformMenuItem("米饭加量", "加购", 2, "配主食加购"),
        ],
        "eleme": [
            PlatformMenuItem("黄焖鸡米饭", "主食", 26),
            PlatformMenuItem("香辣鸡腿堡套餐", "套餐", 29),
            PlatformMenuItem("酸辣土豆丝", "小菜", 12),
        ],
        "dianping": [
            PlatformMenuItem("店内招牌双人餐", "套餐", 88),
            PlatformMenuItem("时令凉菜拼盘", "小菜", 36),
        ],
        "douyin": [
            PlatformMenuItem("直播同款套餐", "套餐", 39),
            PlatformMenuItem("人气单人餐", "主食", 25),
        ],
    }
    key = platform if platform in menus else "meituan"
    return PlatformSnapshot(
        platform=key,
        external_store_id=f"demo_{key}_001",
        store_name=store_name or f"演示门店·{key}",
        menu_items=menus[key],
        daily_metrics=_mock_metrics(),
        raw={"source": "mock", "platform": key},
        synthetic=True,
    )


def fetch_http_snapshot(platform: str, store_id: str, external_store_id: str | None = None) -> PlatformSnapshot:
    url = _connector_url()
    if not url:
        raise ValueError("尚未配置 platform_connector_url，请在设置里填写平台对接地址，或先用演示模式。")

    body = json.dumps(
        {
            "platform": platform,
            "store_id": store_id,
            "external_store_id": external_store_id,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = _connector_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Token"] = token

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"平台对接接口返回 {exc.code}: {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"无法访问平台对接接口：{exc.reason}") from exc

    menu_items = [
        PlatformMenuItem(
            name=str(row.get("name") or "").strip(),
            category=row.get("category"),
            price=float(row["price"]) if row.get("price") is not None else None,
            description=row.get("description"),
        )
        for row in (payload.get("menu_items") or [])
        if str(row.get("name") or "").strip()
    ]
    metrics: list[PlatformDailyMetric] = []
    for row in payload.get("daily_metrics") or []:
        day_raw = row.get("day")
        if not day_raw:
            continue
        day = date.fromisoformat(str(day_raw)[:10])
        metrics.append(
            PlatformDailyMetric(
                day=day,
                impressions=int(row.get("impressions") or 0),
                visits=int(row.get("visits") or 0),
                add_to_cart=int(row.get("add_to_cart") or 0),
                payments=int(row.get("payments") or row.get("orders") or 0),
                orders=int(row.get("orders") or 0),
                gmv=float(row.get("gmv") or 0),
                aov=float(row.get("aov") or 0),
            )
        )
    return PlatformSnapshot(
        platform=platform,
        external_store_id=str(payload.get("external_store_id") or external_store_id or f"{platform}_store"),
        store_name=payload.get("store_name"),
        menu_items=menu_items,
        daily_metrics=metrics,
        raw=payload if isinstance(payload, dict) else {"payload": payload},
        synthetic=bool(payload.get("synthetic")),
    )


def fetch_mobile_snapshot(platform: str, store_id: str) -> PlatformSnapshot:
    """mobile 模式：从商家手机采集的 IntakeSubmission 读取数据。

    商家通过手机连接码采集公开页截图/报表 → 上传 → 系统解析落库。
    这里把最新的 IntakeSubmission 转成 PlatformSnapshot。
    无采集数据时 fallback 到 mock。
    """
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.intake import IntakeSubmission, IntakeRawAsset

    db = SessionLocal()
    try:
        submission = db.execute(
            select(IntakeSubmission)
            .where(IntakeSubmission.store_id == store_id)
            .order_by(IntakeSubmission.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if submission is None:
            return fetch_mock_snapshot(platform, store_name=None)

        # 从 submission 的结构化字段 + raw assets 构造 snapshot
        import json
        menu_items: list[PlatformMenuItem] = []

        # 先初始化 parsed（修复 P0-3: 之前在使用前未定义导致 NameError）
        parsed: dict = {}

        # 从 IntakeRawAsset.parsed_json 读（OCR/解析 pipeline 产出）
        raw_assets = db.execute(
            select(IntakeRawAsset)
            .where(IntakeRawAsset.submission_id == submission.id)
            .order_by(IntakeRawAsset.created_at.desc())
            .limit(10)
        ).scalars().all()
        for asset in raw_assets:
            if asset.parsed_json:
                try:
                    asset_data = json.loads(asset.parsed_json)
                    if isinstance(asset_data, dict):
                        parsed.update(asset_data)
                except Exception:  # noqa: BLE001
                    pass

        # 再从 submission 的 JSON 字段补充
        for json_field in ("parsed_json", "source_types_json", "missing_fields_json"):
            raw = getattr(submission, json_field, None)
            if raw:
                try:
                    val = json.loads(raw)
                    if isinstance(val, dict):
                        parsed.update(val)
                except Exception:  # noqa: BLE001
                    pass

        # 从 parsed 里提取菜单和指标（如果 intake pipeline 解析过）
        for item in (parsed.get("menu_items") or [])[:30]:
            menu_items.append(
                PlatformMenuItem(
                    name=item.get("name", ""),
                    price=float(item.get("price", 0)),
                    category=item.get("category"),
                )
            )

        daily_metrics = []
        for metric in (parsed.get("daily_metrics") or [])[:14]:
            raw_day = metric.get("day")
            # 修复 P0-3: day 可能是字符串，尝试转为 date
            day_value = None
            if raw_day:
                try:
                    from datetime import date as date_type
                    if isinstance(raw_day, date_type):
                        day_value = raw_day
                    else:
                        day_value = date_type.fromisoformat(str(raw_day)[:10])
                except Exception:  # noqa: BLE001
                    day_value = None
            daily_metrics.append(
                PlatformDailyMetric(
                    day=day_value,
                    impressions=int(metric.get("impressions", 0)),
                    visits=int(metric.get("visits", 0)),
                    orders=int(metric.get("orders", 0)),
                    gmv=float(metric.get("gmv", 0)),
                )
            )

        # 即使没有详细 metrics，也返回基础门店信息（非 mock）
        return PlatformSnapshot(
            platform=platform,
            external_store_id=str(submission.store_id or store_id),
            store_name=submission.store_name or "",
            menu_items=menu_items,
            daily_metrics=daily_metrics,
            synthetic=True,
        )
    finally:
        db.close()


def fetch_platform_snapshot(
    platform: str,
    *,
    store_id: str,
    mode: str = "mock",
    store_name: str | None = None,
    external_store_id: str | None = None,
) -> PlatformSnapshot:
    normalized = (platform or "meituan").strip().lower()
    if mode == "http":
        return fetch_http_snapshot(normalized, store_id=store_id, external_store_id=external_store_id)
    if mode == "mobile":
        return fetch_mobile_snapshot(normalized, store_id=store_id)
    return fetch_mock_snapshot(normalized, store_name=store_name)
