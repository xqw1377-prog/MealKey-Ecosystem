"""统一业务数据导入引擎 — 补足平台真实数据短板。

支持 4 种数据导入:
1. 每日经营数据(曝光/访问/订单/GMV) → ShopFunnelDaily
2. 推广投流数据(CPC/花费/点击) → AdSpendDaily
3. 评价数据(评分/内容/回复) → ReviewImport + ReviewFact
4. 活动数据(活动规则/补贴) → CampaignRecord

所有导入都有 source/confidence/batch_id,每条事实可溯源。
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.business_facts import AdSpendDaily, CampaignRecord, OpsMetricDaily, ReviewImport
from app.models.entities import MenuItem, OrderFact, OrderItemFact, ReviewFact, ShopFunnelDaily


# ── 通用解析工具 ──────────────────────────────────────────────

def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "").replace("　", "")


def _parse_csv_rows(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """解析 CSV/TSV,返回 (headers, rows)。"""
    text = _decode(content)
    # 自动检测分隔符
    delimiter = "\t" if "\t" in text.split("\n")[0] else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    rows = [dict(row) for row in reader if any(v and v.strip() for v in row.values())]
    return headers, rows


def _parse_json_rows(content: bytes) -> list[dict[str, Any]]:
    data = json.loads(_decode(content))
    if isinstance(data, dict):
        data = data.get("items") or data.get("data") or data.get("rows") or [data]
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _parse_date(val: Any) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # 尝试 ISO 解析
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_datetime(val: Any) -> Optional[datetime]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    d = _parse_date(s)
    return datetime(d.year, d.month, d.day) if d else None


def _parse_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in {"-", "—", "N/A", "n/a"}:
        return None
    for ch in "¥￥元,% ":
        s = s.replace(ch, "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(val: Any) -> Optional[int]:
    f = _parse_float(val)
    return int(f) if f is not None else None


def _find_col(headers: list[str], aliases: set[str]) -> Optional[str]:
    normed = {_normalize_header(h): h for h in headers}
    for alias in aliases:
        if alias in normed:
            return normed[alias]
    for alias in aliases:
        for norm, orig in normed.items():
            if alias in norm:
                return orig
    return None


# ── 列名别名映射 ──────────────────────────────────────────────

_DAY_ALIASES = {"日期", "date", "day", "时间", "统计日期"}
_IMP_ALIASES = {"曝光量", "曝光", "impressions", "展现量", "展现"}
_VISIT_ALIASES = {"访问量", "访问", "visits", "入店量", "入店", "visitors"}
_ORDER_ALIASES = {"订单量", "订单", "orders", "下单量", "有效订单"}
_GMV_ALIASES = {"营业额", "gmv", "交易额", "成交额", "销售额", "revenue", "总价"}
_AOV_ALIASES = {"客单价", "aov", "均价", "平均客单"}
_CART_ALIASES = {"加购量", "购物车", "add_to_cart", "addtocart"}
_PAY_ALIASES = {"支付量", "支付订单", "payments", "paid_orders"}

_COST_ALIASES = {"花费", "消耗", "cost", "推广费", "投入", "spend"}
_CLICK_ALIASES = {"点击量", "点击", "clicks", "click"}
_ADS_IMP_ALIASES = {"展现量", "广告曝光", "ad_impressions", "广告展现"}
_ADS_ORDER_ALIASES = {"推广订单", "广告订单", "ads_orders", "orders_from_ads"}
_ADS_GMV_ALIASES = {"推广交易额", "广告gmv", "ads_gmv", "gmv_from_ads"}
_PLATFORM_ALIASES = {"平台", "platform", "来源平台"}

_RATING_ALIASES = {"评分", "星级", "rating", "score", "star"}
_CONTENT_ALIASES = {"评价内容", "内容", "content", "评论", "评价", "text"}
_REVIEWER_ALIASES = {"评价人", "用户", "reviewer", "user", "nickname", "昵称"}
_REVIEW_DATE_ALIASES = {"评价时间", "评价日期", "reviewed_at", "date", "时间"}
_REPLY_ALIASES = {"商家回复", "回复", "reply", "reply_text"}

_CAMP_NAME_ALIASES = {"活动名称", "活动", "name", "campaign", "活动类型"}
_CAMP_TYPE_ALIASES = {"活动类型", "类型", "type", "campaign_type"}
_CAMP_START_ALIASES = {"开始日期", "开始时间", "start_date", "start", "生效时间"}
_CAMP_END_ALIASES = {"结束日期", "结束时间", "end_date", "end", "到期时间"}
_CAMP_DISCOUNT_ALIASES = {"优惠金额", "折扣", "discount", "减免", "优惠"}
_CAMP_PLAT_SUB_ALIASES = {"平台承担", "平台补贴", "platform_subsidy", "platform_share"}
_CAMP_MERCH_SUB_ALIASES = {"商家承担", "商家补贴", "merchant_subsidy", "merchant_share"}
_CAMP_MIN_ALIASES = {"满减门槛", "门槛", "min_order", "满"}

_ORDER_KEY_ALIASES = {"订单号", "订单编号", "order_id", "platform_order_key", "order_no"}
_ORDER_TIME_ALIASES = {"下单时间", "下单日期", "ordered_at", "order_time", "时间"}
_ORDER_STATUS_ALIASES = {"订单状态", "状态", "status"}
_ITEM_NAME_ALIASES = {"商品名", "商品名称", "菜品", "sku", "item_name", "name"}
_QTY_ALIASES = {"数量", "份数", "qty", "quantity", "count"}
_PRICE_ALIASES = {"单价", "价格", "price", "unit_price"}

_IM_ALIASES = {"im回复率", "im_reply_rate", "回复率", "客服回复率"}
_PREP_ALIASES = {"出餐率", "meal_prep_rate", "出餐准时率"}
_ONTIME_ALIASES = {"配送准时率", "准时率", "on_time_delivery_rate", "准时送达率"}
_CANCEL_ALIASES = {"商责取消率", "取消率", "merchant_cancel_rate", "商家取消率"}


# ═══════════════════════════════════════════════════════════
# 1. 每日经营数据导入 → ShopFunnelDaily
# ═══════════════════════════════════════════════════════════


def import_funnel_data(
    db: Session,
    store_id: str,
    content: bytes,
    filename: str,
    *,
    source: str = "platform_export",
    confidence: str = "high",
) -> dict[str, Any]:
    """导入每日经营数据(曝光/访问/订单/GMV/推广费)。

    兼容美团/饿了么/抖音等平台导出的 CSV/Excel/JSON。
    """
    rows = _parse_json_rows(content) if filename.lower().endswith(".json") else _parse_csv_rows(content)[1]

    if not rows:
        # 尝试 Excel
        if filename.lower().endswith((".xlsx", ".xls")):
            rows = _parse_excel_rows(content)
        if not rows:
            return {"error": "未能解析出任何数据行", "imported": 0}

    # 检测列
    headers = list(rows[0].keys()) if rows else []
    day_col = _find_col(headers, _DAY_ALIASES)
    if not day_col:
        return {"error": "找不到日期列(需要: 日期/date/day)", "imported": 0}

    imp_col = _find_col(headers, _IMP_ALIASES)
    vis_col = _find_col(headers, _VISIT_ALIASES)
    order_col = _find_col(headers, _ORDER_ALIASES)
    gmv_col = _find_col(headers, _GMV_ALIASES)
    aov_col = _find_col(headers, _AOV_ALIASES)
    cart_col = _find_col(headers, _CART_ALIASES)
    pay_col = _find_col(headers, _PAY_ALIASES)
    cost_col = _find_col(headers, _COST_ALIASES)

    batch_id = str(uuid.uuid4())[:12]
    imported = 0

    for row in rows:
        d = _parse_date(row.get(day_col))
        if not d:
            continue

        funnel = db.get(ShopFunnelDaily, {"store_id": store_id, "day": d})
        if not funnel:
            funnel = ShopFunnelDaily(store_id=store_id, day=d)
            db.add(funnel)

        # 更新字段(有值才覆盖)
        if imp_col:
            v = _parse_int(row.get(imp_col))
            if v is not None:
                funnel.impressions = v
        if vis_col:
            v = _parse_int(row.get(vis_col))
            if v is not None:
                funnel.visits = v
        if order_col:
            v = _parse_int(row.get(order_col))
            if v is not None:
                funnel.orders = v
        if gmv_col:
            v = _parse_float(row.get(gmv_col))
            if v is not None:
                funnel.gmv = v
        if aov_col:
            v = _parse_float(row.get(aov_col))
            if v is not None:
                funnel.aov = v
        if cart_col:
            v = _parse_int(row.get(cart_col))
            if v is not None:
                funnel.add_to_cart = v
        if pay_col:
            v = _parse_int(row.get(pay_col))
            if v is not None:
                funnel.payments = v
        if cost_col:
            v = _parse_float(row.get(cost_col))
            if v is not None:
                funnel.ads_spend = v

        funnel.data_source = source
        imported += 1

    db.commit()
    return {
        "imported": imported,
        "batch_id": batch_id,
        "source": source,
        "message": f"已导入 {imported} 天经营数据",
    }


# ═══════════════════════════════════════════════════════════
# 2. 推广投流数据导入 → AdSpendDaily
# ═══════════════════════════════════════════════════════════


def import_ads_data(
    db: Session,
    store_id: str,
    content: bytes,
    filename: str,
    *,
    source: str = "platform_export",
    confidence: str = "high",
) -> dict[str, Any]:
    """导入推广投流数据(花费/曝光/点击/订单)。"""
    rows = _parse_json_rows(content) if filename.lower().endswith(".json") else _parse_csv_rows(content)[1]
    if not rows:
        if filename.lower().endswith((".xlsx", ".xls")):
            rows = _parse_excel_rows(content)
        if not rows:
            return {"error": "未能解析出任何数据行", "imported": 0}

    headers = list(rows[0].keys()) if rows else []
    day_col = _find_col(headers, _DAY_ALIASES)
    if not day_col:
        return {"error": "找不到日期列", "imported": 0}

    cost_col = _find_col(headers, _COST_ALIASES)
    click_col = _find_col(headers, _CLICK_ALIASES)
    imp_col = _find_col(headers, _ADS_IMP_ALIASES) or _find_col(headers, _IMP_ALIASES)
    order_col = _find_col(headers, _ADS_ORDER_ALIASES)
    gmv_col = _find_col(headers, _ADS_GMV_ALIASES)
    plat_col = _find_col(headers, _PLATFORM_ALIASES)

    batch_id = str(uuid.uuid4())[:12]
    imported = 0

    for row in rows:
        d = _parse_date(row.get(day_col))
        if not d:
            continue

        platform = str(row.get(plat_col, "")).strip().lower() if plat_col else None
        # 查或建
        existing = db.execute(
            select(AdSpendDaily).where(
                AdSpendDaily.store_id == store_id,
                AdSpendDaily.day == d,
            ).limit(1)
        ).scalar_one_or_none()

        record = existing or AdSpendDaily(
            store_id=store_id, day=d, platform=platform, batch_id=batch_id
        )
        if not existing:
            db.add(record)

        if cost_col:
            record.cost = _parse_float(row.get(cost_col))
        if click_col:
            record.clicks = _parse_int(row.get(click_col))
        if imp_col:
            record.impressions = _parse_int(row.get(imp_col))
        if order_col:
            record.orders_from_ads = _parse_int(row.get(order_col))
        if gmv_col:
            record.gmv_from_ads = _parse_float(row.get(gmv_col))

        # 派生指标
        if record.cost and record.clicks:
            record.cpc = round(record.cost / record.clicks, 2)
        if record.clicks and record.impressions:
            record.ctr = round(record.clicks / record.impressions, 4)
        if record.gmv_from_ads and record.cost:
            record.roas = round(record.gmv_from_ads / record.cost, 2)

        record.source = source
        record.confidence = confidence
        imported += 1

    db.commit()
    return {
        "imported": imported,
        "batch_id": batch_id,
        "source": source,
        "message": f"已导入 {imported} 天投流数据",
    }


# ═══════════════════════════════════════════════════════════
# 3. 评价数据导入 → ReviewImport + ReviewFact
# ═══════════════════════════════════════════════════════════


def import_reviews(
    db: Session,
    store_id: str,
    content: bytes,
    filename: str,
    *,
    source: str = "platform_export",
    confidence: str = "high",
) -> dict[str, Any]:
    """导入评价数据(评分/内容/回复),同步写入 ReviewFact。"""
    rows = _parse_json_rows(content) if filename.lower().endswith(".json") else _parse_csv_rows(content)[1]
    if not rows:
        if filename.lower().endswith((".xlsx", ".xls")):
            rows = _parse_excel_rows(content)
        if not rows:
            return {"error": "未能解析出任何数据行", "imported": 0}

    headers = list(rows[0].keys()) if rows else []
    rating_col = _find_col(headers, _RATING_ALIASES)
    content_col = _find_col(headers, _CONTENT_ALIASES)
    date_col = _find_col(headers, _REVIEW_DATE_ALIASES)
    reviewer_col = _find_col(headers, _REVIEWER_ALIASES)
    reply_col = _find_col(headers, _REPLY_ALIASES)

    if not content_col and not rating_col:
        return {"error": "找不到评分或评价内容列", "imported": 0}

    batch_id = str(uuid.uuid4())[:12]
    imported = 0

    for row in rows:
        rating = _parse_float(row.get(rating_col)) if rating_col else None
        text = str(row.get(content_col, "")).strip() if content_col else ""
        reviewed_at = _parse_datetime(row.get(date_col)) if date_col else utc_now()
        reviewer = str(row.get(reviewer_col, "")).strip() if reviewer_col else None
        reply = str(row.get(reply_col, "")).strip() if reply_col else None

        if not text and rating is None:
            continue

        # 写 ReviewImport (导入层)
        ri = ReviewImport(
            store_id=store_id,
            reviewer_name=reviewer,
            rating=rating,
            content=text,
            reviewed_at=reviewed_at,
            reply_text=reply or None,
            replied_at=utc_now() if reply else None,
            source=source,
            confidence=confidence,
            batch_id=batch_id,
        )
        db.add(ri)
        db.flush()

        # 同步写入 ReviewFact (诊断层)
        rf = ReviewFact(
            store_id=store_id,
            rating=rating,
            content=text,
            reviewed_at=reviewed_at or utc_now(),
            source=source,
            reply_text=reply or None,
            replied_at=utc_now() if reply else None,
        )
        db.add(rf)
        db.flush()
        ri.review_fact_id = rf.id
        imported += 1

    db.commit()
    return {
        "imported": imported,
        "batch_id": batch_id,
        "source": source,
        "message": f"已导入 {imported} 条评价",
    }


# ═══════════════════════════════════════════════════════════
# 4. 活动数据导入 → CampaignRecord
# ═══════════════════════════════════════════════════════════


def import_campaigns(
    db: Session,
    store_id: str,
    content: bytes,
    filename: str,
    *,
    source: str = "manual_input",
    confidence: str = "medium",
) -> dict[str, Any]:
    """导入活动数据(活动名称/类型/时间/补贴)。"""
    rows = _parse_json_rows(content) if filename.lower().endswith(".json") else _parse_csv_rows(content)[1]
    if not rows:
        if filename.lower().endswith((".xlsx", ".xls")):
            rows = _parse_excel_rows(content)
        if not rows:
            return {"error": "未能解析出任何数据行", "imported": 0}

    headers = list(rows[0].keys()) if rows else []
    name_col = _find_col(headers, _CAMP_NAME_ALIASES)
    type_col = _find_col(headers, _CAMP_TYPE_ALIASES)
    start_col = _find_col(headers, _CAMP_START_ALIASES)
    end_col = _find_col(headers, _CAMP_END_ALIASES)
    disc_col = _find_col(headers, _CAMP_DISCOUNT_ALIASES)
    plat_sub_col = _find_col(headers, _CAMP_PLAT_SUB_ALIASES)
    merch_sub_col = _find_col(headers, _CAMP_MERCH_SUB_ALIASES)
    min_col = _find_col(headers, _CAMP_MIN_ALIASES)

    if not name_col:
        return {"error": "找不到活动名称列", "imported": 0}

    imported = 0
    for row in rows:
        name = str(row.get(name_col, "")).strip()
        if not name:
            continue

        record = CampaignRecord(
            store_id=store_id,
            name=name,
            campaign_type=str(row.get(type_col, "")).strip() if type_col else None,
            start_date=_parse_date(row.get(start_col)) if start_col else None,
            end_date=_parse_date(row.get(end_col)) if end_col else None,
            discount_value=_parse_float(row.get(disc_col)) if disc_col else None,
            discount_type="amount",
            platform_subsidy=_parse_float(row.get(plat_sub_col)) if plat_sub_col else None,
            merchant_subsidy=_parse_float(row.get(merch_sub_col)) if merch_sub_col else None,
            min_order_value=_parse_float(row.get(min_col)) if min_col else None,
            status="active",
            source=source,
            confidence=confidence,
        )
        db.add(record)
        imported += 1

    db.commit()
    return {
        "imported": imported,
        "source": source,
        "message": f"已导入 {imported} 条活动记录",
    }


def _load_rows(content: bytes, filename: str) -> list[dict[str, Any]]:
    rows = _parse_json_rows(content) if filename.lower().endswith(".json") else _parse_csv_rows(content)[1]
    if not rows and filename.lower().endswith((".xlsx", ".xls")):
        rows = _parse_excel_rows(content)
    return rows


def _item_name_map(db: Session, store_id: str) -> dict[str, str]:
    items = db.execute(select(MenuItem).where(MenuItem.store_id == store_id)).scalars().all()
    mapping: dict[str, str] = {}
    for item in items:
        version = item.current_version
        if version and version.name:
            mapping[version.name.strip()] = item.id
    return mapping


# ═══════════════════════════════════════════════════════════
# 5. 订单明细导入 → OrderFact + OrderItemFact
# ═══════════════════════════════════════════════════════════


def import_orders(
    db: Session,
    store_id: str,
    content: bytes,
    filename: str,
    *,
    source: str = "platform_export",
    confidence: str = "high",
) -> dict[str, Any]:
    """导入订单/明细。有商品名则写入 OrderItemFact，供利润按真实销量加权。"""
    rows = _load_rows(content, filename)
    if not rows:
        return {"error": "未能解析出任何数据行", "imported": 0}

    headers = list(rows[0].keys())
    key_col = _find_col(headers, _ORDER_KEY_ALIASES)
    time_col = _find_col(headers, _ORDER_TIME_ALIASES) or _find_col(headers, _DAY_ALIASES)
    gmv_col = _find_col(headers, _GMV_ALIASES)
    status_col = _find_col(headers, _ORDER_STATUS_ALIASES)
    name_col = _find_col(headers, _ITEM_NAME_ALIASES)
    qty_col = _find_col(headers, _QTY_ALIASES)
    price_col = _find_col(headers, _PRICE_ALIASES)

    if not time_col and not key_col:
        return {"error": "找不到订单号或下单时间列", "imported": 0}

    name_map = _item_name_map(db, store_id)
    order_cache: dict[str, OrderFact] = {}
    imported_orders = 0
    imported_items = 0

    for index, row in enumerate(rows):
        ordered_at = _parse_datetime(row.get(time_col)) if time_col else None
        if ordered_at is None and time_col:
            day = _parse_date(row.get(time_col))
            ordered_at = datetime(day.year, day.month, day.day) if day else None
        if ordered_at is None:
            continue
        if ordered_at.tzinfo is None:
            ordered_at = ordered_at.replace(tzinfo=timezone.utc)
        order_key = str(row.get(key_col) or "").strip() if key_col else f"row-{index}"
        cache_key = order_key or f"row-{index}"
        order = order_cache.get(cache_key)
        if order is None:
            existing = None
            if order_key:
                existing = db.execute(
                    select(OrderFact).where(
                        OrderFact.store_id == store_id,
                        OrderFact.platform_order_key == order_key,
                    ).limit(1)
                ).scalar_one_or_none()
            order = existing or OrderFact(
                store_id=store_id,
                platform_order_key=order_key or None,
                ordered_at=ordered_at,
                source=source,
            )
            if existing is None:
                db.add(order)
                db.flush()
                imported_orders += 1
            order.ordered_at = ordered_at
            if gmv_col and order.gmv is None:
                order.gmv = _parse_float(row.get(gmv_col))
            if status_col:
                order.status = str(row.get(status_col) or "").strip() or order.status
            order.source = source
            order_cache[cache_key] = order

        if not name_col:
            continue
        item_name = str(row.get(name_col) or "").strip()
        if not item_name:
            continue
        qty = _parse_int(row.get(qty_col)) if qty_col else 1
        price = _parse_float(row.get(price_col)) if price_col else None
        line = OrderItemFact(
            order_id=order.id,
            item_id=name_map.get(item_name),
            qty=qty or 1,
            price=price,
        )
        db.add(line)
        imported_items += 1

    db.commit()
    return {
        "imported": imported_orders,
        "imported_items": imported_items,
        "source": source,
        "confidence": confidence,
        "message": f"已导入 {imported_orders} 笔订单、{imported_items} 条明细",
    }


# ═══════════════════════════════════════════════════════════
# 6. 运营指标导入 → OpsMetricDaily
# ═══════════════════════════════════════════════════════════


def import_ops_metrics(
    db: Session,
    store_id: str,
    content: bytes,
    filename: str,
    *,
    source: str = "platform_export",
    confidence: str = "medium",
) -> dict[str, Any]:
    """导入 IM 回复率等运营指标。没有的列保持空，不编造。"""
    rows = _load_rows(content, filename)
    if not rows:
        return {"error": "未能解析出任何数据行", "imported": 0}

    headers = list(rows[0].keys())
    day_col = _find_col(headers, _DAY_ALIASES)
    if not day_col:
        return {"error": "找不到日期列", "imported": 0}

    im_col = _find_col(headers, _IM_ALIASES)
    prep_col = _find_col(headers, _PREP_ALIASES)
    ontime_col = _find_col(headers, _ONTIME_ALIASES)
    cancel_col = _find_col(headers, _CANCEL_ALIASES)
    plat_col = _find_col(headers, _PLATFORM_ALIASES)
    if not any([im_col, prep_col, ontime_col, cancel_col]):
        return {"error": "找不到 IM回复率/出餐率/准时率/商责取消率 列", "imported": 0}

    batch_id = str(uuid.uuid4())[:12]
    imported = 0
    for row in rows:
        d = _parse_date(row.get(day_col))
        if not d:
            continue
        existing = db.execute(
            select(OpsMetricDaily).where(
                OpsMetricDaily.store_id == store_id,
                OpsMetricDaily.day == d,
            ).limit(1)
        ).scalar_one_or_none()
        record = existing or OpsMetricDaily(store_id=store_id, day=d, batch_id=batch_id)
        if existing is None:
            db.add(record)
        if plat_col:
            record.platform = str(row.get(plat_col) or "").strip() or record.platform
        if im_col:
            record.im_reply_rate = _parse_rate(row.get(im_col))
        if prep_col:
            record.meal_prep_rate = _parse_rate(row.get(prep_col))
        if ontime_col:
            record.on_time_delivery_rate = _parse_rate(row.get(ontime_col))
        if cancel_col:
            record.merchant_cancel_rate = _parse_rate(row.get(cancel_col))
        record.source = source
        record.confidence = confidence
        imported += 1

    db.commit()
    return {
        "imported": imported,
        "batch_id": batch_id,
        "source": source,
        "message": f"已导入 {imported} 天运营指标",
    }


def _parse_rate(val: Any) -> Optional[float]:
    """把 92 / 92% / 0.92 统一成 0-1 比例。"""
    raw = _parse_float(val)
    if raw is None:
        return None
    if raw > 1.0:
        raw = raw / 100.0
    return max(0.0, min(1.0, raw))


# ── Excel 解析 ───────────────────────────────────────────────


def _parse_excel_rows(content: bytes) -> list[dict[str, Any]]:
    try:
        import openpyxl  # type: ignore[import-untyped]
    except ImportError:
        return []

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
        result: list[dict[str, Any]] = []
        for row in rows_iter:
            row_dict = {}
            for i, val in enumerate(row):
                if i < len(headers) and headers[i]:
                    row_dict[headers[i]] = val
            if any(v is not None for v in row_dict.values()):
                result.append(row_dict)
        return result
    except Exception:  # noqa: BLE001
        return []


# ── 查询辅助 ─────────────────────────────────────────────────


def get_data_coverage(db: Session, store_id: str) -> dict[str, Any]:
    """门店各维度数据覆盖度。"""
    from sqlalchemy import func
    from app.models.entities import ItemFunnelDaily, MenuItem

    funnel_count = db.execute(
        select(func.count()).select_from(ShopFunnelDaily).where(ShopFunnelDaily.store_id == store_id)
    ).scalar() or 0

    ads_count = db.execute(
        select(func.count()).select_from(AdSpendDaily).where(AdSpendDaily.store_id == store_id)
    ).scalar() or 0

    review_count = db.execute(
        select(func.count()).select_from(ReviewFact).where(ReviewFact.store_id == store_id)
    ).scalar() or 0

    campaign_count = db.execute(
        select(func.count()).select_from(CampaignRecord).where(CampaignRecord.store_id == store_id)
    ).scalar() or 0

    order_count = db.execute(
        select(func.count()).select_from(OrderFact).where(OrderFact.store_id == store_id)
    ).scalar() or 0

    ops_count = db.execute(
        select(func.count()).select_from(OpsMetricDaily).where(OpsMetricDaily.store_id == store_id)
    ).scalar() or 0

    item_count = db.execute(
        select(func.count()).select_from(MenuItem).where(MenuItem.store_id == store_id, MenuItem.is_active.is_(True))
    ).scalar() or 0

    cost_count = db.execute(
        select(func.count()).select_from(MenuItem).where(
            MenuItem.store_id == store_id,
            MenuItem.is_active.is_(True),
            MenuItem.food_cost.is_not(None),
        )
    ).scalar() or 0

    synthetic_item = db.execute(
        select(func.count()).select_from(ItemFunnelDaily).where(ItemFunnelDaily.data_source == "synthetic")
    ).scalar() or 0

    return {
        "funnel_days": funnel_count,
        "ads_days": ads_count,
        "reviews": review_count,
        "campaigns": campaign_count,
        "order_rows": order_count,
        "ops_days": ops_count,
        "menu_items": item_count,
        "items_with_cost": cost_count,
        "cost_coverage_pct": round(cost_count / item_count * 100, 1) if item_count else 0,
        "synthetic_item_funnel": synthetic_item > 0,
        "ads_observed": ads_count > 0,
        "orders_observed": order_count > 0,
    }
