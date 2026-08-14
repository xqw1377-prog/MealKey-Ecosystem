"""成本导入引擎 — Business Truth Track B 的核心。

流程:
    上传成本表 (Excel/CSV/JSON)
    ↓
    解析为统一行结构 [{item_name, food_cost, packaging_cost, ...}]
    ↓
    模糊匹配门店现有 MenuItem (按名称)
    ↓
    写入 CostRecord (审计层) + 同步 MenuItem 缓存列 (读取层)
    ↓
    返回报告: matched / unmatched / updated

每个事实都有 source + confidence + observed_at,绝不 AI 硬猜。
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.cost import CostRecord
from app.models.entities import MenuItem, MenuItemVersion


# ── 列名别名映射(兼容各种成本表表头) ──────────────────────────────

_NAME_ALIASES = {"name", "商品名", "菜品", "菜品名称", "品名", "sku", "商品", "产品名称"}
_FOOD_ALIASES = {"food_cost", "食材成本", "原料成本", "食材", "成本", "物料成本", "成本价"}
_PACK_ALIASES = {"packaging_cost", "包装成本", "打包费", "包材", "包装"}
_PRICE_ALIASES = {"price", "售价", "价格", "单价"}


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "").replace("　", "")


def _find_column(headers: list[str], aliases: set[str]) -> str | None:
    normed = {_normalize_header(h): h for h in headers}
    for alias in aliases:
        if alias in normed:
            return normed[alias]
    # 模糊包含
    for alias in aliases:
        for norm, orig in normed.items():
            if alias in norm:
                return orig
    return None


def _parse_float(val: Any) -> float | None:
    """从各种格式提取数字: '¥14.6' / '14.6元' / '14.6' / 14.6"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in {"-", "—", "N/A", "n/a", "未知"}:
        return None
    # 去掉货币符号和单位
    for ch in "¥￥元,rmbRMB ":
        s = s.replace(ch, "")
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return None


# ── 文件解析 ──────────────────────────────────────────────────

def parse_cost_file(content: bytes, filename: str) -> list[dict[str, Any]]:
    """解析上传的成本表,返回统一行结构。

    支持 .csv / .json / .xlsx / .xls。
    每行: {item_name, food_cost, packaging_cost, price}
    """
    fname = filename.lower()

    if fname.endswith(".json"):
        return _parse_json(content)

    if fname.endswith(".csv"):
        return _parse_csv(content)

    if fname.endswith((".xlsx", ".xls")):
        return _parse_excel(content)

    # 兜底:尝试当 CSV 解
    return _parse_csv(content)


def _parse_csv(content: bytes) -> list[dict[str, Any]]:
    # 尝试多种编码
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        text = content.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    return _rows_to_items(reader, headers)


def _parse_json(content: bytes) -> list[dict[str, Any]]:
    data = json.loads(content.decode("utf-8", errors="replace"))
    if isinstance(data, dict):
        data = data.get("items") or data.get("data") or [data]
    if not isinstance(data, list):
        return []

    items: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        name = (
            row.get("item_name")
            or row.get("name")
            or row.get("商品名")
            or row.get("菜品")
            or row.get("品名")
        )
        if not name:
            continue
        items.append({
            "item_name": str(name).strip(),
            "food_cost": _parse_float(row.get("food_cost") or row.get("食材成本") or row.get("成本")),
            "packaging_cost": _parse_float(
                row.get("packaging_cost") or row.get("包装成本") or row.get("打包费")
            ),
            "price": _parse_float(row.get("price") or row.get("售价")),
        })
    return items


def _parse_excel(content: bytes) -> list[dict[str, Any]]:
    try:
        import openpyxl  # type: ignore[import-untyped]
    except ImportError:
        # 没有 openpyxl,尝试当 CSV
        return _parse_csv(content)

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        headers = [str(h) if h is not None else "" for h in next(rows_iter)]
    except StopIteration:
        return []

    name_col = _find_column(headers, _NAME_ALIASES)
    food_col = _find_column(headers, _FOOD_ALIASES)
    pack_col = _find_column(headers, _PACK_ALIASES)
    price_col = _find_column(headers, _PRICE_ALIASES)

    if not name_col:
        return []

    items: list[dict[str, Any]] = []
    for row in rows_iter:
        name = row[headers.index(name_col)] if name_col else None
        if not name or not str(name).strip():
            continue
        items.append({
            "item_name": str(name).strip(),
            "food_cost": _parse_float(row[headers.index(food_col)] if food_col else None),
            "packaging_cost": _parse_float(row[headers.index(pack_col)] if pack_col else None),
            "price": _parse_float(row[headers.index(price_col)] if price_col else None),
        })
    return items


def _rows_to_items(
    reader: csv.DictReader, headers: list[str]
) -> list[dict[str, Any]]:
    name_col = _find_column(headers, _NAME_ALIASES)
    food_col = _find_column(headers, _FOOD_ALIASES)
    pack_col = _find_column(headers, _PACK_ALIASES)
    price_col = _find_column(headers, _PRICE_ALIASES)

    if not name_col:
        return []

    items: list[dict[str, Any]] = []
    for row in reader:
        name = row.get(name_col, "").strip()
        if not name:
            continue
        items.append({
            "item_name": name,
            "food_cost": _parse_float(row.get(food_col) if food_col else None),
            "packaging_cost": _parse_float(row.get(pack_col) if pack_col else None),
            "price": _parse_float(row.get(price_col) if price_col else None),
        })
    return items


# ── 名称匹配 ──────────────────────────────────────────────────

def _names_match(cost_name: str, menu_name: str) -> bool:
    """简单但实用的名称匹配:
    - 完全匹配(忽略大小写/空格)
    - 包含关系
    - 去掉常见后缀(套餐/份/个)后匹配
    """
    a = cost_name.lower().replace(" ", "").replace("　", "")
    b = menu_name.lower().replace(" ", "").replace("　", "")
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    # 去掉常见后缀
    for suffix in ("套餐", "份", "个", "(小)", "(大)", "（小）", "（大）", "小份", "大份"):
        a2 = a.replace(suffix.lower(), "")
        b2 = b.replace(suffix.lower(), "")
        if a2 == b2 and a2:
            return True
    return False


def _find_menu_item(
    db: Session, store_id: str, item_name: str
) -> MenuItem | None:
    """在门店菜单里找最匹配的 MenuItem。"""
    stmt = select(MenuItem).where(
        MenuItem.store_id == store_id,
        MenuItem.is_active.is_(True),
    )
    items = list(db.execute(stmt).scalars())
    # 优先精确匹配
    for item in items:
        version = _get_current_version(db, item)
        if version and _names_match(item_name, version.name or ""):
            return item
    return None


def _get_current_version(db: Session, item: MenuItem) -> MenuItemVersion | None:
    if not item.current_version_id:
        stmt = (
            select(MenuItemVersion)
            .where(MenuItemVersion.item_id == item.id)
            .order_by(MenuItemVersion.captured_at.desc())
            .limit(1)
        )
        return db.execute(stmt).scalar_one_or_none()
    return db.get(MenuItemVersion, item.current_version_id)


# ── 主入口 ────────────────────────────────────────────────────

def import_cost_sheet(
    db: Session,
    store_id: str,
    content: bytes,
    filename: str,
    *,
    source: str = "owner_cost_sheet",
    confidence: str = "high",
    effective_from: date | None = None,
) -> dict[str, Any]:
    """导入成本表,返回报告。

    Returns:
        {
            "batch_id": "...",
            "total_rows": 20,
            "matched": 15,       # 成功匹配到 MenuItem
            "unmatched": 5,      # 未匹配(需人工映射)
            "updated_items": 15, # MenuItem 缓存被更新
            "unmatched_items": [{"name": "...", "food_cost": 14.6}, ...],
        }
    """
    rows = parse_cost_file(content, filename)
    if not rows:
        return {
            "batch_id": None,
            "total_rows": 0,
            "matched": 0,
            "unmatched": 0,
            "updated_items": 0,
            "error": "未能从文件中解析出任何成本行,请检查格式。",
        }

    batch_id = str(uuid.uuid4())[:12]
    now = utc_now()
    matched_count = 0
    unmatched_list: list[dict[str, Any]] = []
    updated_item_ids: set[str] = set()

    for row in rows:
        item_name = row["item_name"]
        food_cost = row.get("food_cost")
        packaging_cost = row.get("packaging_cost")

        # 即使两个成本都没有,也记录一条(表示"该商品在表里但成本为空")
        item = _find_menu_item(db, store_id, item_name)

        record = CostRecord(
            store_id=store_id,
            item_id=item.id if item else None,
            item_name=item_name,
            food_cost=food_cost,
            packaging_cost=packaging_cost,
            source=source,
            confidence=confidence,
            observed_at=now,
            effective_from=effective_from,
            batch_id=batch_id,
        )
        db.add(record)

        if item:
            matched_count += 1
            # 同步缓存列(只在有实际成本值时更新)
            if food_cost is not None or packaging_cost is not None:
                if food_cost is not None:
                    item.food_cost = food_cost
                if packaging_cost is not None:
                    item.packaging_cost = packaging_cost
                item.cost_source = source
                item.cost_confidence = confidence
                item.cost_updated_at = now
                updated_item_ids.add(item.id)
        else:
            unmatched_list.append({
                "name": item_name,
                "food_cost": food_cost,
                "packaging_cost": packaging_cost,
            })

    db.commit()

    return {
        "batch_id": batch_id,
        "total_rows": len(rows),
        "matched": matched_count,
        "unmatched": len(unmatched_list),
        "updated_items": len(updated_item_ids),
        "unmatched_items": unmatched_list,
    }


def get_store_cost_coverage(db: Session, store_id: str) -> dict[str, Any]:
    """门店成本覆盖度:有多少 SKU 有真实成本,多少还 UNKNOWN。"""
    stmt = select(MenuItem).where(
        MenuItem.store_id == store_id,
        MenuItem.is_active.is_(True),
    )
    items = list(db.execute(stmt).scalars())
    total = len(items)
    has_food = sum(1 for i in items if i.food_cost is not None)
    has_pack = sum(1 for i in items if i.packaging_cost is not None)
    has_both = sum(
        1 for i in items if i.food_cost is not None and i.packaging_cost is not None
    )
    return {
        "total_items": total,
        "has_food_cost": has_food,
        "has_packaging_cost": has_pack,
        "has_both_cost": has_both,
        "missing_cost": total - has_both,
        "coverage_pct": round(has_both / total * 100, 1) if total else 0.0,
    }


def get_item_costs(db: Session, store_id: str) -> list[dict[str, Any]]:
    """列出门店所有商品的成本状态(用于前端展示 + 人工补录)。"""
    stmt = select(MenuItem).where(
        MenuItem.store_id == store_id,
        MenuItem.is_active.is_(True),
    )
    items = list(db.execute(stmt).scalars())
    result: list[dict[str, Any]] = []
    for item in items:
        version = _get_current_version(db, item)
        result.append({
            "item_id": item.id,
            "name": version.name if version else "(未命名)",
            "price": version.price if version else None,
            "food_cost": item.food_cost,
            "packaging_cost": item.packaging_cost,
            "cost_source": item.cost_source,
            "cost_confidence": item.cost_confidence,
            "cost_updated_at": item.cost_updated_at.isoformat() if item.cost_updated_at else None,
            "has_cost": item.food_cost is not None or item.packaging_cost is not None,
        })
    return result


def update_single_item_cost(
    db: Session,
    store_id: str,
    item_id: str,
    food_cost: float | None = None,
    packaging_cost: float | None = None,
    *,
    source: str = "manual_input",
    confidence: str = "high",
) -> dict[str, Any]:
    """手动更新单个商品成本(用于中栏 [填写成本] 按钮)。"""
    item = db.get(MenuItem, item_id)
    if not item or item.store_id != store_id:
        return {"error": "商品不存在"}

    now = utc_now()
    version = _get_current_version(db, item)
    item_name = version.name if version else item_id

    record = CostRecord(
        store_id=store_id,
        item_id=item_id,
        item_name=item_name,
        food_cost=food_cost,
        packaging_cost=packaging_cost,
        source=source,
        confidence=confidence,
        observed_at=now,
    )
    db.add(record)

    if food_cost is not None:
        item.food_cost = food_cost
    if packaging_cost is not None:
        item.packaging_cost = packaging_cost
    item.cost_source = source
    item.cost_confidence = confidence
    item.cost_updated_at = now
    db.commit()

    return {"item_id": item_id, "updated": True}
