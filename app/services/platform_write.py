"""Phase C：低风险平台写回。

ODO → Permission → Tool Call → Platform → Read Back → 复用 mark_loop_executed。
当前开放：改标题、换主图、普通好评回复。不自动改价，不回复差评，不接入 Autopilot。
老板点确认才触发；失败则闭环停在 now，并把原因记在执行包上。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.closed_loop import ClosedLoopItem
from app.models.entities import MenuItem, MenuItemVersion, ReviewFact
from app.models.settings import PlatformConnection
from app.services.platform_connectors import (
    post_platform_write,
    read_back_review_appeal,
    read_back_product_image,
    read_back_product_title,
    read_back_review_reply,
)

PLATFORM_WRITE_ALLOWLIST = {"change_title", "change_main_image", "reply_ordinary_reviews", "appeal_pack"}
PLATFORM_WRITE_BLOCKLIST = {
    "adjust_price_value",
    "boost_hero_item_ads",
    "adjust_ad_budget",
    "join_lunch_campaign",
    "match_competitor_promo",
    "store_discount",
    "launch_value_bundle_promo",
    "run_platform_promo",
    "menu_cleanup",
    "batch_reply_negative_reviews",
    "issue_repurchase_coupon",
    "reactivate_dormant_customer",
    "referral_share",
}

ORDINARY_REVIEW_MIN_RATING = 4.0
DEFAULT_ORDINARY_REPLY = "感谢您的认可，我们会继续保持口味和出餐速度。欢迎再来。"


class WritePermissionError(PermissionError):
    pass


class WriteFailedError(RuntimeError):
    pass


class ReadBackMismatchError(RuntimeError):
    pass


@dataclass
class ConnectorTarget:
    platform: str
    mode: str
    external_store_id: Optional[str] = None


@dataclass
class PlatformWriteResult:
    ok: bool
    op: str
    mode: str
    object_name: str = ""
    expected_title: str = ""
    applied_title: str = ""
    read_back_title: str = ""
    review_id: str = ""
    ticket_id: str = ""
    applied_reply: str = ""
    appeal_text: str = ""
    evidence_count: int = 0
    applied_image_url: str = ""
    read_back_image_url: str = ""
    external_ref: str = ""
    summary: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_pack(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "op": self.op,
            "mode": self.mode,
            "object_name": self.object_name,
            "applied_title": self.applied_title,
            "read_back_title": self.read_back_title,
            "review_id": self.review_id,
            "ticket_id": self.ticket_id,
            "applied_reply": self.applied_reply,
            "appeal_text": self.appeal_text,
            "evidence_count": self.evidence_count,
            "applied_image_url": self.applied_image_url,
            "read_back_image_url": self.read_back_image_url,
            "external_ref": self.external_ref,
            "summary": self.summary,
            "platform_changed": self.mode != "human_paste",
        }
        payload.update(self.extra)
        return payload


def is_platform_writeable(action_type: str) -> bool:
    return str(action_type or "").strip() in PLATFORM_WRITE_ALLOWLIST


def check_write_permission(action_type: str, *, confirmed: bool = True) -> None:
    kind = str(action_type or "").strip()
    if kind in PLATFORM_WRITE_BLOCKLIST or kind.startswith("adjust_price"):
        raise WritePermissionError("这条动作不能自动写回平台。改价、投流、活动和差评仍由你在后台确认。")
    if kind not in PLATFORM_WRITE_ALLOWLIST:
        raise WritePermissionError("现在只开放改标题、换主图、普通好评回复和评价申诉提交。其他事项请在平台改完后点「已修改」。")
    if not confirmed:
        raise WritePermissionError("需要你确认后，我才会改到平台。")


def suggested_title_from_pack(pack: dict[str, Any], *, object_name: str = "") -> str:
    explicit = str(pack.get("suggested_title") or "").strip()
    if explicit:
        return explicit
    copy = str(pack.get("copy_text") or "")
    matched = re.search(r"建议标题[：:]\s*(.+)", copy)
    if matched:
        return matched.group(1).strip().split("\n")[0].strip()
    name = object_name or str(pack.get("object_name") or "").strip()
    return f"{name}｜现炒·足量热饭" if name else ""


def suggested_image_from_pack(pack: dict[str, Any], *, object_name: str = "") -> str:
    explicit = str(pack.get("suggested_image_url") or pack.get("image_url") or "").strip()
    if explicit:
        return explicit
    name = object_name or str(pack.get("object_name") or "").strip() or "hero"
    slug = "".join(ch for ch in name if ch.isalnum()) or "item"
    return f"https://cdn.mealky.local/hero/{slug}.jpg"


def ordinary_reply_from_pack(pack: dict[str, Any]) -> str:
    explicit = str(pack.get("reply_text") or "").strip()
    if explicit:
        return explicit
    copy = str(pack.get("copy_text") or "")
    matched = re.search(r"建议回复[：:]\s*(.+)", copy)
    if matched:
        return matched.group(1).strip().split("\n")[0].strip()
    return DEFAULT_ORDINARY_REPLY


def _env_writeback_mode() -> str:
    from app.core.config import settings

    if str(settings.platform_connector_url or "").strip():
        return "http"
    return "mock" if settings.is_dev else "human_paste"


def resolve_connector(db: Session, store_id: str) -> ConnectorTarget:
    from app.core.config import settings

    conn = db.execute(
        select(PlatformConnection)
        .where(PlatformConnection.store_id == store_id)
        .order_by(PlatformConnection.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    platform = "meituan"
    external_store_id = None
    requested = ""
    if conn is not None:
        platform = (conn.platform or "meituan").strip().lower() or "meituan"
        external_store_id = conn.external_store_id
        requested = (conn.connector_mode or "").strip().lower()
    connector_url = str(settings.platform_connector_url or "").strip()
    from app.services.seed_store import is_seed_store

    if is_seed_store(db, store_id):
        mode = "human_paste"
    elif requested == "human_paste":
        mode = "human_paste"
    elif requested == "http" and connector_url:
        mode = "http"
    elif requested == "mock":
        mode = "mock" if settings.is_dev else "human_paste"
    elif connector_url:
        mode = "http"
    else:
        mode = "mock" if settings.is_dev else "human_paste"
    return ConnectorTarget(
        platform=platform,
        mode=mode,
        external_store_id=external_store_id,
    )


def _human_paste_result(item: ClosedLoopItem, pack: dict[str, Any]) -> PlatformWriteResult:
    copy_text = str(pack.get("copy_text") or "").strip()
    return PlatformWriteResult(
        ok=True,
        op="human_paste",
        mode="human_paste",
        object_name=str(item.object_name or pack.get("object_name") or ""),
        summary="稿已经给你了。请复制到美团商家端改完，再点「已修改」。现在还没写到平台。",
        extra={
            "copy_text": copy_text,
            "platform_changed": False,
            "how_to_use": "先复制到美团，改完回来点「已修改」。没有连接器时不会假装已经写上平台。",
        },
    )


def execute_confirmed_writeback(
    db: Session,
    store_id: str,
    item: ClosedLoopItem,
    pack: dict[str, Any],
) -> PlatformWriteResult:
    from app.services.seed_store import SeedStoreError, assert_writeback_allowed

    try:
        assert_writeback_allowed(db, store_id)
    except SeedStoreError as exc:
        raise WritePermissionError(f"{exc.code}: {exc}") from exc
    check_write_permission(item.action_type, confirmed=True)
    target = resolve_connector(db, store_id)
    if target.mode == "human_paste":
        return _human_paste_result(item, pack)
    if item.action_type == "change_title":
        return execute_confirmed_title_writeback(db, store_id, item, pack)
    if item.action_type == "change_main_image":
        return execute_confirmed_image_writeback(db, store_id, item, pack)
    if item.action_type == "reply_ordinary_reviews":
        return execute_confirmed_review_writeback(db, store_id, item, pack)
    if item.action_type == "appeal_pack":
        return execute_confirmed_appeal_writeback(db, store_id, item, pack)
    raise WritePermissionError("现在只开放改标题、换主图、普通好评回复和评价申诉提交。")


def execute_confirmed_title_writeback(
    db: Session,
    store_id: str,
    item: ClosedLoopItem,
    pack: dict[str, Any],
) -> PlatformWriteResult:
    check_write_permission("change_title", confirmed=True)
    object_name = str(item.object_name or pack.get("object_name") or "").strip()
    if not object_name:
        object_name = str(pack.get("title") or item.title or "").strip()
    new_title = suggested_title_from_pack(pack, object_name=object_name)
    if not object_name or not new_title:
        raise WriteFailedError("执行包里没有可写回的商品名或新标题。")

    target = resolve_connector(db, store_id)
    payload = {"object_name": object_name, "new_title": new_title}
    try:
        written = post_platform_write(
            "update_product_title",
            platform=target.platform,
            store_id=store_id,
            payload=payload,
            mode=target.mode,
            external_store_id=target.external_store_id,
        )
    except ValueError as exc:
        raise WriteFailedError(str(exc)) from exc

    applied = str(written.get("applied_title") or new_title).strip()
    read_back = read_back_product_title(
        platform=target.platform,
        store_id=store_id,
        expected_title=applied,
        mode=target.mode,
        external_store_id=target.external_store_id,
    )
    if not read_back:
        raise ReadBackMismatchError("平台写回后读回对不上新标题，这件事还不能算已执行。")

    _apply_local_title(db, store_id, object_name, applied)
    summary = f"已把「{object_name}」标题改成「{applied}」，读回确认一致。进入观察窗。"
    return PlatformWriteResult(
        ok=True,
        op="update_product_title",
        mode=target.mode,
        object_name=object_name,
        expected_title=new_title,
        applied_title=applied,
        read_back_title=read_back,
        external_ref=str(written.get("external_ref") or ""),
        summary=summary,
    )


def execute_confirmed_image_writeback(
    db: Session,
    store_id: str,
    item: ClosedLoopItem,
    pack: dict[str, Any],
) -> PlatformWriteResult:
    check_write_permission("change_main_image", confirmed=True)
    object_name = str(item.object_name or pack.get("object_name") or "").strip()
    if not object_name:
        object_name = str(pack.get("title") or item.title or "").strip()
    new_image = suggested_image_from_pack(pack, object_name=object_name)
    if not object_name or not new_image:
        raise WriteFailedError("执行包里没有可写回的商品名或主图。")

    target = resolve_connector(db, store_id)
    payload = {"object_name": object_name, "new_image_url": new_image}
    try:
        written = post_platform_write(
            "update_product_image",
            platform=target.platform,
            store_id=store_id,
            payload=payload,
            mode=target.mode,
            external_store_id=target.external_store_id,
        )
    except ValueError as exc:
        raise WriteFailedError(str(exc)) from exc

    applied = str(written.get("applied_image_url") or new_image).strip()
    read_back = read_back_product_image(
        platform=target.platform,
        store_id=store_id,
        object_name=object_name,
        expected_image_url=applied,
        mode=target.mode,
        external_store_id=target.external_store_id,
    )
    if not read_back:
        raise ReadBackMismatchError("平台写回后读回对不上新主图，这件事还不能算已执行。")

    _apply_local_image(db, store_id, object_name, applied)
    summary = f"已把「{object_name}」主图换成新图，读回确认一致。进入观察窗。"
    return PlatformWriteResult(
        ok=True,
        op="update_product_image",
        mode=target.mode,
        object_name=object_name,
        applied_image_url=applied,
        read_back_image_url=read_back,
        external_ref=str(written.get("external_ref") or ""),
        summary=summary,
    )


def execute_confirmed_review_writeback(
    db: Session,
    store_id: str,
    item: ClosedLoopItem,
    pack: dict[str, Any],
) -> PlatformWriteResult:
    check_write_permission("reply_ordinary_reviews", confirmed=True)
    reply_text = ordinary_reply_from_pack(pack)
    review_id = str(pack.get("review_id") or "").strip()
    local = _next_ordinary_review(db, store_id, review_id=review_id)
    if local is not None:
        if float(local.rating or 0) < ORDINARY_REVIEW_MIN_RATING:
            raise WritePermissionError("普通评价回复不能用于差评。")
        review_id = local.id

    target = resolve_connector(db, store_id)
    payload = {
        "review_id": review_id,
        "reply_text": reply_text,
        "min_rating": ORDINARY_REVIEW_MIN_RATING,
    }
    try:
        written = post_platform_write(
            "reply_review",
            platform=target.platform,
            store_id=store_id,
            payload=payload,
            mode=target.mode,
            external_store_id=target.external_store_id,
        )
    except ValueError as exc:
        raise WriteFailedError(str(exc)) from exc

    applied_id = str(written.get("review_id") or written.get("external_ref") or review_id).strip()
    applied_reply = str(written.get("applied_reply") or reply_text).strip()
    if not applied_id:
        raise WriteFailedError("平台没有返回被回复的评价。")
    read_back = read_back_review_reply(
        platform=target.platform,
        store_id=store_id,
        review_id=applied_id,
        expected_text=applied_reply,
        mode=target.mode,
        external_store_id=target.external_store_id,
    )
    if not read_back:
        raise ReadBackMismatchError("评价回复写回后读回对不上，这件事还不能算已执行。")

    _apply_local_reply(db, store_id, applied_id, applied_reply)
    summary = "已回复一条普通好评，读回确认一致。进入观察窗。"
    return PlatformWriteResult(
        ok=True,
        op="reply_review",
        mode=target.mode,
        object_name=str(item.object_name or "普通好评"),
        review_id=applied_id,
        applied_reply=applied_reply,
        external_ref=str(written.get("external_ref") or applied_id),
        summary=summary,
    )


def execute_confirmed_appeal_writeback(
    db: Session,
    store_id: str,
    item: ClosedLoopItem,
    pack: dict[str, Any],
) -> PlatformWriteResult:
    check_write_permission("appeal_pack", confirmed=True)
    evidence = _appeal_evidence(item, pack)
    if not evidence:
        raise WriteFailedError("没有证据不要提交申诉。请先补订单记录、聊天截图或现场说明。")
    appeal_text = str(pack.get("appeal_template") or pack.get("appeal_reason") or "").strip()
    if not appeal_text:
        raise WriteFailedError("执行包里没有申诉说明。")
    review_id = str(pack.get("review_id") or "").strip()
    if not review_id:
        review = _next_appealable_review(db, store_id)
        if review is not None:
            review_id = review.id

    target = resolve_connector(db, store_id)
    payload = {
        "review_id": review_id,
        "appeal_text": appeal_text,
        "evidence": evidence,
    }
    try:
        written = post_platform_write(
            "submit_review_appeal",
            platform=target.platform,
            store_id=store_id,
            payload=payload,
            mode=target.mode,
            external_store_id=target.external_store_id,
        )
    except ValueError as exc:
        raise WriteFailedError(str(exc)) from exc

    ticket_id = str(written.get("ticket_id") or written.get("external_ref") or "").strip()
    if not ticket_id:
        raise WriteFailedError("平台没有返回申诉工单号。")
    read_back = read_back_review_appeal(
        platform=target.platform,
        store_id=store_id,
        ticket_id=ticket_id,
        mode=target.mode,
        external_store_id=target.external_store_id,
    )
    if not read_back:
        raise ReadBackMismatchError("申诉提交后没有读回工单状态，这件事还不能算已执行。")

    review_label = review_id or str(read_back.get("review_id") or "")
    evidence_count = int(read_back.get("evidence_count") or len(evidence))
    summary = (
        f"已提交评价申诉并读回工单号 {ticket_id}。"
        f"{f' 关联评价 {review_label}。' if review_label else ''}"
        f"本次附了 {evidence_count} 份证据，继续等平台处理结果。"
    )
    return PlatformWriteResult(
        ok=True,
        op="submit_review_appeal",
        mode=target.mode,
        object_name=str(item.object_name or "评价申诉"),
        review_id=review_label,
        ticket_id=ticket_id,
        appeal_text=appeal_text,
        evidence_count=evidence_count,
        external_ref=ticket_id,
        summary=summary,
    )


def _next_ordinary_review(
    db: Session,
    store_id: str,
    *,
    review_id: str = "",
) -> Optional[ReviewFact]:
    if review_id:
        review = db.get(ReviewFact, review_id)
        if review is None or review.store_id != store_id:
            return None
        return review
    return db.execute(
        select(ReviewFact)
        .where(
            ReviewFact.store_id == store_id,
            ReviewFact.rating >= ORDINARY_REVIEW_MIN_RATING,
            or_(ReviewFact.reply_text.is_(None), ReviewFact.reply_text == ""),
        )
        .order_by(ReviewFact.reviewed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _next_appealable_review(db: Session, store_id: str) -> Optional[ReviewFact]:
    return db.execute(
        select(ReviewFact)
        .where(
            ReviewFact.store_id == store_id,
            ReviewFact.rating <= 2.5,
        )
        .order_by(ReviewFact.reviewed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _appeal_evidence(item: ClosedLoopItem, pack: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    rows = pack.get("appeal_evidence")
    if isinstance(rows, list):
        evidence.extend(row for row in rows if isinstance(row, dict))
    if item.evidence_json:
        try:
            stored = json.loads(item.evidence_json)
        except Exception:  # noqa: BLE001
            stored = []
        if isinstance(stored, list):
            evidence.extend(row for row in stored if isinstance(row, dict))
    clean: list[dict[str, Any]] = []
    for row in evidence:
        note = str(row.get("note") or "").strip()
        data_url = str(row.get("data_url") or row.get("url") or "").strip()
        if not note and not data_url:
            continue
        clean.append(
            {
                "kind": str(row.get("kind") or "note"),
                "note": note,
                "data_url": data_url,
                "by": str(row.get("by") or ""),
            }
        )
    return clean


def _apply_local_title(db: Session, store_id: str, object_name: str, new_title: str) -> bool:
    items = db.execute(select(MenuItem).where(MenuItem.store_id == store_id)).scalars().all()
    for menu_item in items:
        version = menu_item.current_version
        if version is None or str(version.name or "").strip() != object_name:
            continue
        new_version = MenuItemVersion(
            item_id=menu_item.id,
            name=new_title,
            category=version.category,
            price=version.price,
            description=version.description,
            image_url=version.image_url,
            source="platform_write:change_title",
        )
        db.add(new_version)
        db.flush()
        menu_item.current_version_id = new_version.id
        return True
    return False


def _apply_local_image(db: Session, store_id: str, object_name: str, image_url: str) -> bool:
    items = db.execute(select(MenuItem).where(MenuItem.store_id == store_id)).scalars().all()
    for menu_item in items:
        version = menu_item.current_version
        if version is None or str(version.name or "").strip() != object_name:
            continue
        new_version = MenuItemVersion(
            item_id=menu_item.id,
            name=version.name,
            category=version.category,
            price=version.price,
            description=version.description,
            image_url=image_url,
            source="platform_write:change_main_image",
        )
        db.add(new_version)
        db.flush()
        menu_item.current_version_id = new_version.id
        return True
    return False


def _apply_local_reply(db: Session, store_id: str, review_id: str, reply_text: str) -> bool:
    review = db.get(ReviewFact, review_id)
    if review is None or review.store_id != store_id:
        return False
    review.reply_text = reply_text
    review.replied_at = datetime.now(timezone.utc)
    return True
