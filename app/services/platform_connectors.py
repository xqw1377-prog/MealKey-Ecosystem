from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.settings import PlatformConnection
from app.services.settings_store import get_setting


SUPPORTED_PLATFORMS = (
    {"key": "meituan", "label": "美团外卖", "modes": ["mock", "http", "mobile", "oauth"]},
    {"key": "eleme", "label": "饿了么", "modes": ["mock", "http", "mobile", "oauth"]},
    {"key": "dianping", "label": "大众点评", "modes": ["mock", "mobile"]},
    {"key": "douyin", "label": "抖音生活服务", "modes": ["mock", "mobile"]},
)


@dataclass
class PlatformMenuItem:
    name: str
    category: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


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
class PlatformReview:
    review_id: str
    rating: float = 5.0
    content: str = ""
    replied: bool = False
    reply_text: str = ""


@dataclass
class PlatformSnapshot:
    platform: str
    external_store_id: str
    store_name: Optional[str] = None
    menu_items: list[PlatformMenuItem] = field(default_factory=list)
    daily_metrics: list[PlatformDailyMetric] = field(default_factory=list)
    reviews: list[PlatformReview] = field(default_factory=list)
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


def _connector_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = _connector_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-API-Token"] = token
    return headers


def _write_url() -> str:
    url = _connector_url().rstrip("/")
    if not url:
        return ""
    if url.endswith("/sync"):
        return url[: -len("/sync")] + "/write"
    if url.endswith("/read"):
        return url[: -len("/read")] + "/write"
    return url + "/write"


# 演示/测试用的内存菜单与评价。HTTP 连接器未接上时，写回仍走同一套 op 契约，并可用读回校验。
_MOCK_MENUS: dict[str, list[dict[str, Any]]] = {}
_MOCK_REVIEWS: dict[str, list[dict[str, Any]]] = {}
_MOCK_APPEALS: dict[str, list[dict[str, Any]]] = {}


def reset_mock_platform_state() -> None:
    _MOCK_MENUS.clear()
    _MOCK_REVIEWS.clear()
    _MOCK_APPEALS.clear()


def _ensure_mock_menu(store_id: str, platform: str) -> list[dict[str, Any]]:
    if store_id not in _MOCK_MENUS:
        snap = fetch_mock_snapshot(platform)
        _MOCK_MENUS[store_id] = [
            {
                "name": item.name,
                "category": item.category,
                "price": item.price,
                "description": item.description,
                "image_url": item.image_url,
            }
            for item in snap.menu_items
        ]
    return _MOCK_MENUS[store_id]


def mock_write_product_title(
    store_id: str,
    *,
    platform: str,
    object_name: str,
    new_title: str,
) -> dict[str, Any]:
    menu = _ensure_mock_menu(store_id, platform)
    for row in menu:
        if str(row.get("name") or "").strip() == object_name:
            row["name"] = new_title
            return {
                "ok": True,
                "op": "update_product_title",
                "external_ref": f"mock:{store_id}:{object_name}",
                "applied_title": new_title,
            }
    menu.append({"name": new_title, "category": "主食", "price": None, "description": None, "image_url": None})
    return {
        "ok": True,
        "op": "update_product_title",
        "external_ref": f"mock:{store_id}:{object_name}",
        "applied_title": new_title,
    }


def mock_read_product_title(store_id: str, *, platform: str, expected_title: str) -> Optional[str]:
    menu = _ensure_mock_menu(store_id, platform)
    for row in menu:
        name = str(row.get("name") or "").strip()
        if name == expected_title:
            return name
    return None


def mock_write_product_image(
    store_id: str,
    *,
    platform: str,
    object_name: str,
    new_image_url: str,
) -> dict[str, Any]:
    menu = _ensure_mock_menu(store_id, platform)
    for row in menu:
        if str(row.get("name") or "").strip() == object_name:
            row["image_url"] = new_image_url
            return {
                "ok": True,
                "op": "update_product_image",
                "external_ref": f"mock:{store_id}:{object_name}",
                "applied_image_url": new_image_url,
            }
    menu.append(
        {
            "name": object_name,
            "category": "主食",
            "price": None,
            "description": None,
            "image_url": new_image_url,
        }
    )
    return {
        "ok": True,
        "op": "update_product_image",
        "external_ref": f"mock:{store_id}:{object_name}",
        "applied_image_url": new_image_url,
    }


def mock_read_product_image(
    store_id: str, *, platform: str, object_name: str, expected_image_url: str
) -> Optional[str]:
    menu = _ensure_mock_menu(store_id, platform)
    for row in menu:
        if str(row.get("name") or "").strip() != object_name:
            continue
        url = str(row.get("image_url") or "").strip()
        if url == expected_image_url.strip():
            return url
        return None
    return None


def _ensure_mock_reviews(store_id: str) -> list[dict[str, Any]]:
    if store_id not in _MOCK_REVIEWS:
        short = (store_id or "demo")[:8]
        _MOCK_REVIEWS[store_id] = [
            {
                "review_id": f"mock-good-{short}-1",
                "rating": 5,
                "content": "味道不错，会再点",
                "replied": False,
                "reply_text": "",
            },
            {
                "review_id": f"mock-good-{short}-2",
                "rating": 4,
                "content": "送得挺快，包装也好",
                "replied": False,
                "reply_text": "",
            },
            {
                "review_id": f"mock-bad-{short}-1",
                "rating": 2,
                "content": "肉有点少",
                "replied": False,
                "reply_text": "",
            },
        ]
    return _MOCK_REVIEWS[store_id]


def mock_write_review_reply(
    store_id: str,
    *,
    review_id: str = "",
    reply_text: str = "",
    min_rating: float = 4.0,
) -> dict[str, Any]:
    reviews = _ensure_mock_reviews(store_id)
    target = None
    if review_id:
        target = next((row for row in reviews if str(row.get("review_id")) == review_id), None)
        if target is None:
            raise ValueError("找不到这条评价，无法回复。")
        if float(target.get("rating") or 0) < min_rating:
            raise ValueError("普通评价回复不能用于差评。")
    else:
        target = next(
            (
                row
                for row in reviews
                if not row.get("replied") and float(row.get("rating") or 0) >= min_rating
            ),
            None,
        )
        if target is None:
            raise ValueError("没有待回复的普通好评。")
    text = (reply_text or "").strip()
    if not text:
        raise ValueError("回复内容是空的。")
    target["replied"] = True
    target["reply_text"] = text
    return {
        "ok": True,
        "op": "reply_review",
        "external_ref": str(target["review_id"]),
        "review_id": str(target["review_id"]),
        "applied_reply": text,
        "rating": float(target.get("rating") or 0),
    }


def mock_read_review_reply(store_id: str, *, review_id: str, expected_text: str) -> Optional[str]:
    reviews = _ensure_mock_reviews(store_id)
    for row in reviews:
        if str(row.get("review_id")) != review_id:
            continue
        if not row.get("replied"):
            return None
        text = str(row.get("reply_text") or "").strip()
        if text == expected_text.strip():
            return text
        return None
    return None


def _ensure_mock_appeals(store_id: str) -> list[dict[str, Any]]:
    if store_id not in _MOCK_APPEALS:
        _MOCK_APPEALS[store_id] = []
    return _MOCK_APPEALS[store_id]


def mock_write_review_appeal(
    store_id: str,
    *,
    review_id: str = "",
    appeal_text: str = "",
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reviews = _ensure_mock_reviews(store_id)
    target = None
    if review_id:
        target = next((row for row in reviews if str(row.get("review_id")) == review_id), None)
    else:
        target = next((row for row in reviews if float(row.get("rating") or 0) <= 2.5), None)
    if target is None:
        raise ValueError("没有找到可申诉的评价。")
    evidence_rows = [row for row in (evidence or []) if isinstance(row, dict)]
    valid_rows = [
        row
        for row in evidence_rows
        if str(row.get("note") or "").strip() or str(row.get("data_url") or row.get("url") or "").strip()
    ]
    if not valid_rows:
        raise ValueError("没有证据不要提交申诉。")
    text = (appeal_text or "").strip()
    if not text:
        raise ValueError("申诉说明不能为空。")
    ticket_id = f"appeal:{store_id[:8]}:{len(_ensure_mock_appeals(store_id)) + 1}"
    record = {
        "ticket_id": ticket_id,
        "review_id": str(target.get("review_id") or ""),
        "appeal_text": text,
        "evidence_count": len(valid_rows),
        "status": "submitted",
    }
    _ensure_mock_appeals(store_id).append(record)
    return {
        "ok": True,
        "op": "submit_review_appeal",
        "external_ref": ticket_id,
        "ticket_id": ticket_id,
        "review_id": record["review_id"],
        "appeal_text": text,
        "evidence_count": record["evidence_count"],
        "status": record["status"],
    }


def mock_read_review_appeal(store_id: str, *, ticket_id: str) -> Optional[dict[str, Any]]:
    appeals = _ensure_mock_appeals(store_id)
    for row in appeals:
        if str(row.get("ticket_id")) == ticket_id and str(row.get("status")) == "submitted":
            return {
                "ticket_id": str(row.get("ticket_id") or ""),
                "review_id": str(row.get("review_id") or ""),
                "status": str(row.get("status") or ""),
                "evidence_count": int(row.get("evidence_count") or 0),
            }
    return None


def post_platform_write(
    op: str,
    *,
    platform: str,
    store_id: str,
    payload: dict[str, Any],
    mode: str = "mock",
    external_store_id: str | None = None,
) -> dict[str, Any]:
    """统一写回入口。mock 走内存菜单；http 打到对接层 /write。生产禁止 mock。"""
    from app.services.connector_mode import assert_mode_allowed

    mode = assert_mode_allowed(mode, explicit=True)
    if mode == "mock":
        if op == "update_product_title":
            return mock_write_product_title(
                store_id,
                platform=platform,
                object_name=str(payload.get("object_name") or ""),
                new_title=str(payload.get("new_title") or ""),
            )
        if op == "update_product_image":
            return mock_write_product_image(
                store_id,
                platform=platform,
                object_name=str(payload.get("object_name") or ""),
                new_image_url=str(payload.get("new_image_url") or ""),
            )
        if op == "reply_review":
            return mock_write_review_reply(
                store_id,
                review_id=str(payload.get("review_id") or ""),
                reply_text=str(payload.get("reply_text") or ""),
                min_rating=float(payload.get("min_rating") or 4),
            )
        if op == "submit_review_appeal":
            return mock_write_review_appeal(
                store_id,
                review_id=str(payload.get("review_id") or ""),
                appeal_text=str(payload.get("appeal_text") or ""),
                evidence=payload.get("evidence") if isinstance(payload.get("evidence"), list) else [],
            )
        raise ValueError(f"演示写回暂不支持 {op}")

    url = _write_url()
    if not url:
        raise ValueError("尚未配置 platform_connector_url，无法写回平台。")
    body = json.dumps(
        {
            "op": op,
            "platform": platform,
            "store_id": store_id,
            "external_store_id": external_store_id,
            "payload": payload,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=_connector_headers(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"平台写回接口返回 {exc.code}: {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"无法访问平台写回接口：{exc.reason}") from exc
    if not isinstance(result, dict):
        raise ValueError("平台写回接口返回格式无效")
    if result.get("ok") is False:
        raise ValueError(str(result.get("error") or "平台写回失败"))
    return result


def read_back_product_title(
    *,
    platform: str,
    store_id: str,
    expected_title: str,
    mode: str = "mock",
    external_store_id: str | None = None,
) -> Optional[str]:
    if mode == "mock":
        return mock_read_product_title(store_id, platform=platform, expected_title=expected_title)
    snapshot = fetch_http_snapshot(platform, store_id=store_id, external_store_id=external_store_id)
    for item in snapshot.menu_items:
        if item.name == expected_title:
            return item.name
    return None


def read_back_product_image(
    *,
    platform: str,
    store_id: str,
    object_name: str,
    expected_image_url: str,
    mode: str = "mock",
    external_store_id: str | None = None,
) -> Optional[str]:
    if mode == "mock":
        return mock_read_product_image(
            store_id,
            platform=platform,
            object_name=object_name,
            expected_image_url=expected_image_url,
        )
    snapshot = fetch_http_snapshot(platform, store_id=store_id, external_store_id=external_store_id)
    expected = expected_image_url.strip()
    for item in snapshot.menu_items:
        if item.name != object_name:
            continue
        url = str(item.image_url or "").strip()
        if url == expected:
            return url
        return None
    return None


def read_back_review_reply(
    *,
    platform: str,
    store_id: str,
    review_id: str,
    expected_text: str,
    mode: str = "mock",
    external_store_id: str | None = None,
) -> Optional[str]:
    if mode == "mock":
        return mock_read_review_reply(store_id, review_id=review_id, expected_text=expected_text)
    snapshot = fetch_http_snapshot(platform, store_id=store_id, external_store_id=external_store_id)
    expected = expected_text.strip()
    for review in snapshot.reviews:
        if review.review_id != review_id:
            continue
        if review.replied and review.reply_text.strip() == expected:
            return review.reply_text.strip()
        return None


def read_back_review_appeal(
    *,
    platform: str,
    store_id: str,
    ticket_id: str,
    mode: str = "mock",
    external_store_id: str | None = None,
) -> Optional[dict[str, Any]]:
    if mode == "mock":
        return mock_read_review_appeal(store_id, ticket_id=ticket_id)
    snapshot = fetch_http_snapshot(platform, store_id=store_id, external_store_id=external_store_id)
    appeals = snapshot.raw.get("appeals") if isinstance(snapshot.raw, dict) else None
    if not isinstance(appeals, list):
        return None
    for row in appeals:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticket_id") or "") != ticket_id:
            continue
        if str(row.get("status") or "").lower() != "submitted":
            return None
        return row
    return None
    return None


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
    short = (platform or "demo")[:8]
    reviews = [
        PlatformReview(review_id=f"mock-good-{short}-1", rating=5, content="味道不错，会再点"),
        PlatformReview(review_id=f"mock-good-{short}-2", rating=4, content="送得挺快，包装也好"),
        PlatformReview(review_id=f"mock-bad-{short}-1", rating=2, content="肉有点少"),
    ]
    return PlatformSnapshot(
        platform=key,
        external_store_id=f"demo_{key}_001",
        store_name=store_name or f"演示门店·{key}",
        menu_items=menus[key],
        daily_metrics=_mock_metrics(),
        reviews=reviews,
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
    request = urllib.request.Request(url, data=body, headers=_connector_headers(), method="POST")
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
            image_url=str(row.get("image_url") or "").strip() or None,
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
    reviews: list[PlatformReview] = []
    for row in payload.get("reviews") or []:
        review_id = str(row.get("review_id") or row.get("id") or "").strip()
        if not review_id:
            continue
        reviews.append(
            PlatformReview(
                review_id=review_id,
                rating=float(row.get("rating") or 0),
                content=str(row.get("content") or ""),
                replied=bool(row.get("replied") or row.get("reply_text")),
                reply_text=str(row.get("reply_text") or ""),
            )
        )
    return PlatformSnapshot(
        platform=platform,
        external_store_id=str(payload.get("external_store_id") or external_store_id or f"{platform}_store"),
        store_name=payload.get("store_name"),
        menu_items=menu_items,
        daily_metrics=metrics,
        reviews=reviews,
        raw=payload if isinstance(payload, dict) else {"payload": payload},
        synthetic=bool(payload.get("synthetic")),
    )


def fetch_oauth_snapshot(platform: str, store_id: str, external_store_id: str | None = None) -> PlatformSnapshot:
    url = _connector_url()
    if not url:
        raise ValueError("OAuth 已连通，但还没配置 platform_connector_url 来代拉平台数据。")
    oauth = _load_oauth_meta(store_id, platform)
    access_token = str(oauth.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("OAuth access_token 不存在，请重新授权。")
    body = json.dumps(
        {
            "platform": platform,
            "store_id": store_id,
            "external_store_id": external_store_id,
            "oauth": {
                "access_token": access_token,
                "refresh_token": str(oauth.get("refresh_token") or ""),
                "token_type": str(oauth.get("token_type") or "bearer"),
                "scope": str(oauth.get("scope") or ""),
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=_connector_headers(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"OAuth 平台拉数失败：{exc.code} {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"OAuth 平台拉数失败：{exc.reason}") from exc
    if not isinstance(payload, dict):
        raise ValueError("OAuth 平台拉数返回格式不正确。")
    payload.setdefault("synthetic", False)
    payload.setdefault("source", "oauth")
    return PlatformSnapshot(
        platform=platform,
        external_store_id=str(payload.get("external_store_id") or external_store_id or f"{platform}_store"),
        store_name=payload.get("store_name"),
        menu_items=[
            PlatformMenuItem(
                name=str(row.get("name") or "").strip(),
                category=row.get("category"),
                price=float(row["price"]) if row.get("price") is not None else None,
                description=row.get("description"),
                image_url=str(row.get("image_url") or "").strip() or None,
            )
            for row in (payload.get("menu_items") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ],
        daily_metrics=[
            PlatformDailyMetric(
                day=date.fromisoformat(str(row.get("day"))[:10]),
                impressions=int(row.get("impressions") or 0),
                visits=int(row.get("visits") or 0),
                add_to_cart=int(row.get("add_to_cart") or 0),
                payments=int(row.get("payments") or row.get("orders") or 0),
                orders=int(row.get("orders") or 0),
                gmv=float(row.get("gmv") or 0),
                aov=float(row.get("aov") or 0),
            )
            for row in (payload.get("daily_metrics") or [])
            if isinstance(row, dict) and row.get("day")
        ],
        reviews=[
            PlatformReview(
                review_id=str(row.get("review_id") or row.get("id") or "").strip(),
                rating=float(row.get("rating") or 0),
                content=str(row.get("content") or ""),
                replied=bool(row.get("replied") or row.get("reply_text")),
                reply_text=str(row.get("reply_text") or ""),
            )
            for row in (payload.get("reviews") or [])
            if isinstance(row, dict) and str(row.get("review_id") or row.get("id") or "").strip()
        ],
        raw=payload,
        synthetic=bool(payload.get("synthetic")),
    )


def fetch_mobile_snapshot(platform: str, store_id: str, db: "Session | None" = None) -> PlatformSnapshot:
    """mobile 模式：从商家手机采集的 IntakeSubmission 读取数据。

    商家通过手机连接码采集公开页截图/报表 → 上传 → 系统解析落库。
    这里把最新的 IntakeSubmission 转成 PlatformSnapshot。
    没有采集数据时明确报错，不再偷偷回退到 mock。
    """
    from sqlalchemy import select
    # 支持外部传入 db(测试用); 否则用生产 SessionLocal
    if db is not None:
        _db = db
        _should_close = False
    else:
        from app.db.session import SessionLocal
        _db = SessionLocal()
        _should_close = True
    from app.models.intake import IntakeSubmission, IntakeRawAsset

    try:
        submission = _db.execute(
            select(IntakeSubmission)
            .where(IntakeSubmission.store_id == store_id)
            .order_by(IntakeSubmission.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if submission is None:
            raise ValueError("手机连接已建立，但还没有采集到门店资料或报表。")

        # 从 submission 的结构化字段 + raw assets 构造 snapshot
        import json
        menu_items: list[PlatformMenuItem] = []

        # 先初始化 parsed（修复 P0-3: 之前在使用前未定义导致 NameError）
        parsed: dict = {}

        mobile_truth = True

        # 从 IntakeRawAsset.parsed_json 读（OCR/解析 pipeline 产出）
        raw_assets = _db.execute(
            select(IntakeRawAsset)
            .where(IntakeRawAsset.submission_id == submission.id)
            .order_by(IntakeRawAsset.created_at.desc())
            .limit(10)
        ).scalars().all()
        for asset in raw_assets:
            if str(asset.asset_type or "") == "synthetic_metric_note":
                mobile_truth = False
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

        if not menu_items:
            for item in (parsed.get("source_types", {}).get("menu_items") or parsed.get("menu_items") or [])[:30]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                menu_items.append(
                    PlatformMenuItem(
                        name=name,
                        price=float(item.get("price") or 0) if item.get("price") is not None else None,
                        category=item.get("category"),
                    )
                )

        # 即使没有完整 metrics，也返回真实采集到的基础门店信息
        return PlatformSnapshot(
            platform=platform,
            external_store_id=str(submission.store_id or store_id),
            store_name=submission.store_name or "",
            menu_items=menu_items,
            daily_metrics=daily_metrics,
            raw={
                "source": "mobile",
                "submission_id": submission.id,
                "readiness": submission.readiness,
                "truth_mode": "observed" if mobile_truth else "mixed",
            },
            synthetic=not mobile_truth,
        )
    finally:
        if _should_close:
            _db.close()


def fetch_platform_snapshot(
    platform: str,
    *,
    store_id: str,
    mode: str | None = None,
    store_name: str | None = None,
    external_store_id: str | None = None,
    db: "Session | None" = None,
) -> PlatformSnapshot:
    from app.services.connector_mode import assert_mode_allowed

    resolved = assert_mode_allowed(mode, explicit=True)
    normalized = (platform or "meituan").strip().lower()
    if resolved == "http":
        return fetch_http_snapshot(normalized, store_id=store_id, external_store_id=external_store_id)
    if resolved == "mobile":
        return fetch_mobile_snapshot(normalized, store_id=store_id, db=db)
    if resolved == "oauth":
        return fetch_oauth_snapshot(normalized, store_id=store_id, external_store_id=external_store_id)
    return fetch_mock_snapshot(normalized, store_name=store_name)


def _load_oauth_meta(store_id: str, platform: str) -> dict[str, Any]:
    from app.services.credential_store import load_oauth_credentials

    with SessionLocal() as db:
        row = (
            db.query(PlatformConnection)
            .filter(PlatformConnection.store_id == store_id, PlatformConnection.platform == platform)
            .order_by(PlatformConnection.created_at.desc())
            .first()
        )
        secret = load_oauth_credentials(db, store_id, platform, connection=row)
        if row is not None:
            db.commit()
        return secret
