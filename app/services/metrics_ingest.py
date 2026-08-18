"""把 CSV / 导出表写入 ShopFunnelDaily，让真实读数进入 StoreState。"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.entities import ShopFunnelDaily


_HEADER_MAP = {
    "day": "day",
    "日期": "day",
    "date": "day",
    "impressions": "impressions",
    "曝光": "impressions",
    "曝光量": "impressions",
    "visits": "visits",
    "访问": "visits",
    "进店": "visits",
    "点击": "visits",
    "orders": "orders",
    "订单": "orders",
    "订单量": "orders",
    "gmv": "gmv",
    "销售额": "gmv",
    "成交额": "gmv",
}


def ingest_funnel_csv(db: Session, store_id: str, text: str) -> dict[str, Any]:
    rows = _parse_rows(text)
    written = 0
    for row in rows:
        day = row.get("day")
        if day is None:
            continue
        db.merge(
            ShopFunnelDaily(
                store_id=store_id,
                day=day,
                impressions=row.get("impressions"),
                visits=row.get("visits"),
                orders=row.get("orders"),
                gmv=row.get("gmv"),
                data_source="file_import",
            )
        )
        written += 1
    if written:
        db.commit()
    return {"rows": written, "store_id": store_id}


def ingest_funnel_from_attachments(db: Session, store_id: str, parsed_files: list[Any]) -> dict[str, Any]:
    chunks: list[str] = []
    for item in parsed_files or []:
        name = str(getattr(item, "filename", "") or getattr(item, "name", "") or "")
        text = str(getattr(item, "extracted_text", "") or "")
        if re.search(r"\.csv|\.xlsx|曝光|订单|gmv|点击率", f"{name} {text}", re.I):
            chunks.append(text)
    if not chunks:
        return {"rows": 0, "store_id": store_id}
    return ingest_funnel_csv(db, store_id, "\n".join(chunks))


def _parse_rows(text: str) -> list[dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return []
    sample = raw.splitlines()[0] if raw else ""
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []
    headers = [_normalize_header(cell) for cell in rows[0]]
    if not any(headers):
        return []
    parsed: list[dict[str, Any]] = []
    for cells in rows[1:]:
        item: dict[str, Any] = {}
        for index, key in enumerate(headers):
            if not key or index >= len(cells):
                continue
            value = cells[index].strip()
            if not value:
                continue
            if key == "day":
                day = _parse_day(value)
                if day:
                    item["day"] = day
            else:
                number = _parse_number(value)
                if number is not None:
                    item[key] = int(number) if key != "gmv" else float(number)
        if "day" in item:
            parsed.append(item)
    return parsed


def _normalize_header(cell: str) -> str:
    token = re.sub(r"\s+", "", (cell or "").strip().lower())
    return _HEADER_MAP.get(token) or _HEADER_MAP.get(cell.strip()) or ""


def _parse_day(value: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_number(value: str) -> Optional[float]:
    cleaned = value.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None
