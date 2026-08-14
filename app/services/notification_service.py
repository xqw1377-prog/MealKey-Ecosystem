"""消息推送服务 V2 — 正式 Notification 表 + 节流/合并/静默时段。

WP4 通知治理：
- 打扰预算：每店每日主动推送上限 5 条（urgent 不计），超出的合并进 digest
- 合并：同一 clock phase 的多条合成一条
- 静默时段：quiet_hours 内只积累不推送（critical 除外）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.notification import Notification
from app.services.operating_rhythm import is_in_quiet_hours, local_now, resolve_store_rhythm

logger = logging.getLogger(__name__)

NotificationType = Literal[
    "need_you", "goal_deviation", "experiment_result", "safe_mode", "opportunity", "auto_done"
]

# 默认打扰预算
DEFAULT_DAILY_BUDGET = 5


def _wx_configured() -> bool:
    return bool(getattr(settings, "wechat_app_id", None) and getattr(settings, "wechat_app_secret", None))


def send_wx_template_message(
    *, openid: str, template_id: str, data: dict[str, Any], url: str = "", mini_program: dict | None = None
) -> bool:
    if not _wx_configured():
        return False
    try:
        import urllib.request

        token_url = (
            f"https://api.weixin.qq.com/cgi-bin/token?"
            f"grant_type=client_credential&appid={settings.wechat_app_id}&secret={settings.wechat_app_secret}"
        )
        with urllib.request.urlopen(token_url, timeout=10) as resp:
            token_data = json.loads(resp.read())
        access_token = token_data.get("access_token")
        if not access_token:
            return False

        payload = {"touser": openid, "template_id": template_id, "url": url, "data": data}
        if mini_program:
            payload["miniprogram"] = mini_program
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}",
            data=body, method="POST", headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        return result.get("errcode") == 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("wx push failed: %s", exc)
        return False


def _daily_push_count(db: Session, store_id: str) -> int:
    """今天已推送的非 urgent 通知数。"""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(
        select(func.count(Notification.id)).where(
            Notification.store_id == store_id,
            Notification.created_at >= today_start,
            Notification.priority != "urgent",
            Notification.push_status == "delivered",
        )
    ).scalar_one()


def notify_store_owner(
    db: Session,
    *,
    store_id: str,
    notification_type: NotificationType,
    title: str,
    body: str = "",
    priority: str = "normal",
    action_url: str = "",
    clock_phase: str | None = None,
    related_decision_id: str | None = None,
    wx_openid: str | None = None,
    wx_template_id: str | None = None,
    suppress_if_budget_exceeded: bool = True,
) -> str | None:
    """统一推送入口——站内消息 + 微信模板消息（如果配置了）。"""
    now = datetime.now(timezone.utc)
    quiet_hours = False
    if priority != "urgent":
        try:
            rhythm = resolve_store_rhythm(db, store_id)
            quiet_hours = is_in_quiet_hours(rhythm, local_now().hour)
        except Exception:  # noqa: BLE001
            quiet_hours = False

    budget_exceeded = False
    if suppress_if_budget_exceeded and priority != "urgent":
        budget_exceeded = _daily_push_count(db, store_id) >= DEFAULT_DAILY_BUDGET
        if budget_exceeded:
            logger.info("notification queued: daily budget exceeded for %s", store_id)

    if related_decision_id:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        existing = db.execute(
            select(Notification.id).where(
                Notification.store_id == store_id,
                Notification.related_decision_id == related_decision_id[:64],
                Notification.created_at >= today_start,
            ).limit(1)
        ).scalar_one_or_none()
        if existing:
            return None

    digest_group = f"{clock_phase}:{now.strftime('%Y%m%d')}" if clock_phase else f"{notification_type}:{now.strftime('%Y%m%d')}"
    delivery_state = "queued" if (quiet_hours or budget_exceeded) and priority != "urgent" else "delivered"
    suppress_reason = "quiet_hours" if quiet_hours else ("daily_budget" if budget_exceeded else None)

    existing = db.execute(
        select(Notification)
        .where(
            Notification.store_id == store_id,
            Notification.read.is_(False),
            Notification.digest_group == digest_group,
        )
        .order_by(Notification.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if existing is not None:
        payload = _load_meta(existing.meta_json)
        count = int(payload.get("count") or 1) + 1
        payload["count"] = count
        payload["last_title"] = title[:200]
        existing.title = _merge_title(existing.title, title, count)
        existing.body = _merge_body(existing.body, body)
        existing.priority = _pick_priority(existing.priority, priority)
        existing.action_url = action_url or existing.action_url
        existing.push_status = delivery_state if delivery_state == "queued" else existing.push_status
        existing.push_suppressed_reason = suppress_reason or existing.push_suppressed_reason
        existing.meta_json = json.dumps(payload, ensure_ascii=False)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing.id

    notif = Notification(
        store_id=store_id,
        notification_type=notification_type,
        title=title[:200],
        body=body[:1000] if body else None,
        priority=priority,
        action_url=action_url or None,
        clock_phase=clock_phase,
        digest_group=digest_group,
        related_decision_id=related_decision_id,
        push_status=delivery_state,
        push_suppressed_reason=suppress_reason,
        pushed_at=now if delivery_state == "delivered" else None,
        meta_json=json.dumps({"count": 1}, ensure_ascii=False),
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)

    if delivery_state == "delivered" and wx_openid and wx_template_id:
        send_wx_template_message(
            openid=wx_openid,
            template_id=wx_template_id,
            data={
                "title": {"value": title},
                "body": {"value": body[:100]},
                "time": {"value": now.strftime("%Y-%m-%d %H:%M")},
            },
        )

    return notif.id


def get_unread_notifications(db: Session, store_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Notification)
        .where(Notification.store_id == store_id, Notification.read.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": n.id,
            "type": n.notification_type,
            "title": n.title,
            "body": n.body or "",
            "priority": n.priority,
            "action_url": n.action_url or "",
            "created_at": n.created_at.isoformat() if n.created_at else "",
            "read": n.read,
            "push_status": n.push_status,
            "push_suppressed_reason": n.push_suppressed_reason or "",
        }
        for n in rows
    ]


def mark_notification_read(db: Session, notification_id: str) -> bool:
    notif = db.get(Notification, notification_id)
    if notif is None:
        return False
    notif.read = True
    notif.read_at = datetime.now(timezone.utc)
    notif.push_status = "read"
    db.add(notif)
    db.commit()
    return True


def flush_queued_notifications(db: Session, store_id: str | None = None) -> int:
    """离开静默时段后，把 queued 通知切到 delivered。"""
    query = select(Notification).where(Notification.read.is_(False), Notification.push_status == "queued")
    if store_id:
        query = query.where(Notification.store_id == store_id)
    rows = db.execute(query.order_by(Notification.created_at.asc())).scalars().all()
    released = 0
    for row in rows:
        try:
            rhythm = resolve_store_rhythm(db, row.store_id)
            quiet = is_in_quiet_hours(rhythm, local_now().hour)
        except Exception:  # noqa: BLE001
            quiet = False
        if quiet:
            continue
        row.push_status = "delivered"
        row.push_suppressed_reason = None
        row.pushed_at = datetime.now(timezone.utc)
        db.add(row)
        released += 1
    if released:
        db.commit()
    return released


# 向下兼容旧 AppSetting 方式的读取（迁移期用）
def _get_unread_from_app_setting(db: Session, store_id: str, limit: int = 20) -> list[dict[str, Any]]:
    from app.models.settings import AppSetting

    rows = db.execute(
        select(AppSetting)
        .where(AppSetting.key.like(f"notification:notif-{store_id}-%"))
        .order_by(AppSetting.created_at.desc())
        .limit(limit)
    ).scalars().all()
    notifications = []
    for row in rows:
        try:
            data = json.loads(row.value)
            if not data.get("read"):
                notifications.append(data)
        except Exception:  # noqa: BLE001
            pass
    return notifications


def get_all_unread(db: Session, store_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """合并读 Notification 表 + 旧 AppSetting 通知。"""
    new_notifs = get_unread_notifications(db, store_id, limit)
    old_notifs = _get_unread_from_app_setting(db, store_id, limit)
    return new_notifs + old_notifs


def _merge_title(existing: str, incoming: str, count: int) -> str:
    base = (incoming or existing or "经营提醒").strip()[:180]
    return f"{base}（{count}）"


def _merge_body(existing: str | None, incoming: str | None) -> str | None:
    lines: list[str] = []
    for raw in (existing or "", incoming or ""):
        for line in str(raw).splitlines():
            value = line.strip()
            if value and value not in lines:
                lines.append(value)
    if not lines:
        return None
    return "\n".join(lines)[:1000]


def _pick_priority(left: str, right: str) -> str:
    rank = {"urgent": 4, "high": 3, "normal": 2, "low": 1}
    return left if rank.get(left, 0) >= rank.get(right, 0) else right


def _load_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
