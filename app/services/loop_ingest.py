"""A 期窄通道：人工/半自动真实数据进入 Signal → Now。

不要求平台 API。CSV、Excel 导出、截图识别出的文字都可以。
目标是验证：真实数据能变成同一条 ClosedLoopItem，而不是停在聊天摘要。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.closed_loop import ClosedLoopItem
from app.models.runtime_v1 import BusinessEventRecord, SignalRecord
from app.services.copy_humanize import humanize_operator_text
from app.services.execution_pack import build_execution_pack
from app.services.operating_rhythm import local_now


def ingest_operating_attachments(db: Session, store_id: str, parsed_files: list[Any]) -> Optional[ClosedLoopItem]:
    chunks: list[str] = []
    filename = ""
    for item in parsed_files or []:
        text = str(getattr(item, "extracted_text", "") or "").strip()
        if not text:
            continue
        filename = str(getattr(item, "filename", "") or getattr(item, "name", "") or filename)
        chunks.append(text)
    if not chunks:
        return None
    return ingest_operating_text(db, store_id, "\n".join(chunks), filename=filename)


def ingest_operating_text(
    db: Session,
    store_id: str,
    text: str,
    *,
    filename: str = "",
) -> Optional[ClosedLoopItem]:
    blob = humanize_operator_text(text or "")
    if not blob.strip():
        return None
    inferred = infer_signal_from_text(blob, filename=filename)
    if inferred is None:
        return None
    now = datetime.now(timezone.utc)
    signal = SignalRecord(
        store_id=store_id,
        signal_type=inferred["signal_type"],
        subject_type="item" if inferred.get("object_name") else "store",
        subject_id=None,
        metric=inferred["metric"],
        value=inferred.get("value"),
        baseline=inferred.get("baseline"),
        payload_json=json.dumps(
            {"source": filename or "manual", "excerpt": blob[:800], "action_type": inferred["action_type"]},
            ensure_ascii=False,
        ),
        occurred_at=now,
    )
    db.add(signal)
    db.flush()
    event = BusinessEventRecord(
        store_id=store_id,
        source_signal_id=signal.id,
        event_type=inferred["event_type"],
        domain=inferred["domain"],
        subject_type=signal.subject_type,
        title=inferred["title"],
        observation_json=json.dumps({"finding": inferred["finding"]}, ensure_ascii=False),
        severity="high",
        status="OPEN",
        detected_at=now,
    )
    db.add(event)
    db.flush()
    pack = build_execution_pack(
        inferred["action_type"],
        object_name=inferred.get("object_name") or "",
        title=inferred["title"],
    ) or {}
    day = local_now().strftime("%Y-%m-%d")
    fingerprint = f"{store_id}:ingest:{inferred['action_type']}:{day}"
    existing = db.execute(
        select(ClosedLoopItem)
        .where(
            ClosedLoopItem.store_id == store_id,
            ClosedLoopItem.fingerprint == fingerprint,
            ClosedLoopItem.status.in_(("now", "executed", "observing", "result_ready")),
        )
        .order_by(ClosedLoopItem.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        db.commit()
        return existing
    item = ClosedLoopItem(
        store_id=store_id,
        fingerprint=fingerprint,
        source_card_id=f"ingest:{signal.id}",
        source_event_id=event.id,
        title=inferred["title"],
        finding=inferred["finding"],
        judgment=inferred["judgment"],
        action_type=inferred["action_type"],
        object_name=str(inferred.get("object_name") or "")[:80],
        pack_json=json.dumps(pack, ensure_ascii=False),
        status="now",
        observe_hours=int(pack.get("observe_hours") or 48),
        success_metric=str(pack.get("success_metric") or inferred["metric_label"]),
        success_target=str(pack.get("success_target") or ""),
        guardrail=str(pack.get("guardrail") or ""),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def infer_signal_from_text(text: str, *, filename: str = "") -> Optional[dict[str, Any]]:
    blob = f"{filename} {text}"
    object_name = _guess_item_name(text)
    drop = _first_float(blob)
    if re.search(r"差评|评分下滑|评分下降|1星|2星|差评突然", blob):
        name = object_name or "当前商品"
        return {
            "signal_type": "review_drop",
            "event_type": "RATING_DROP",
            "domain": "reputation",
            "metric": "rating",
            "metric_label": "评分",
            "action_type": "batch_reply_negative_reviews",
            "object_name": name,
            "value": drop,
            "title": f"{name}差评整改",
            "finding": humanize_operator_text(text)[:180] or f"{name}差评明显增加。",
            "judgment": "先按原因回复差评，再观察评分是否止跌。",
        }
    if re.search(r"好评未回|待回复好评|普通评价积压|好评积压|未回复好评", blob):
        name = object_name or "当前店铺"
        return {
            "signal_type": "review_backlog",
            "event_type": "REVIEW_BACKLOG",
            "domain": "reputation",
            "metric": "rating",
            "metric_label": "待回复好评",
            "action_type": "reply_ordinary_reviews",
            "object_name": name,
            "value": drop,
            "title": f"{name}普通好评待回复",
            "finding": humanize_operator_text(text)[:180] or f"{name}有普通好评还没回。",
            "judgment": "先把普通好评回掉，差评仍要你看过再回。",
        }
    if re.search(r"标题|品名", blob) and not re.search(r"主图|首图", blob):
        name = object_name or "当前商品"
        return {
            "signal_type": "title_weak",
            "event_type": "CTR_DROP",
            "domain": "product",
            "metric": "ctr",
            "metric_label": "点击率",
            "action_type": "change_title",
            "object_name": name,
            "value": drop,
            "title": f"改{name}标题",
            "finding": humanize_operator_text(text)[:180] or f"{name}标题信息弱，第一眼看不出卖点。",
            "judgment": "先换一版强调份量或卖点的标题，观察点击率。",
        }
    if re.search(r"点击率|ctr|主图|首图|曝光", blob, re.I):
        name = object_name or "当前商品"
        return {
            "signal_type": "ctr_drop",
            "event_type": "CTR_DROP",
            "domain": "product",
            "metric": "ctr",
            "metric_label": "点击率",
            "action_type": "change_main_image",
            "object_name": name,
            "value": drop,
            "title": f"换{name}主图",
            "finding": humanize_operator_text(text)[:180] or f"{name}点击率下滑，份量感偏弱。",
            "judgment": "先换强调份量的主图，观察点击率，转化率不能明显下降。",
        }
    return None


def _guess_item_name(text: str) -> str:
    matched = re.search(r"([\u4e00-\u9fff]{2,12}(?:饭|面|粉|套餐|汉堡|鸡|牛|鱼|粥))", text)
    if matched:
        return matched.group(1)
    return ""


def _first_float(text: str) -> Optional[float]:
    matched = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if matched:
        return float(matched.group(1))
    return None
