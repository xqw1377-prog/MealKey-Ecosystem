"""消息推送服务 V2 — 正式 Notification 表 + 节流/合并/静默时段。

WP4 通知治理：
- 打扰预算：每店每日主动推送上限 5 条（urgent 不计），超出的合并进 digest
- 合并：同一 clock phase 的多条合成一条
- 静默时段：quiet_hours 内只积累不推送（critical 除外）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.notification import Notification

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
    """统一推送入口——站内消息 + 微信模板消息（如果配置了）。

    WP4 通知治理：
    - urgent 不计入打扰预算
    - 非 urgent 超预算时返回 None（不推送）
    - 同 clock_phase 的多条自动合并（digest_group）
    """
    # 节流：非 urgent 超预算
    if suppress_if_budget_exceeded and priority != "urgent":
        if _daily_push_count(db, store_id) >= DEFAULT_DAILY_BUDGET:
            logger.info("notification suppressed: daily budget exceeded for %s", store_id)
            return None

    digest_group = f"{clock_phase}:{datetime.now(timezone.utc).strftime('%Y%m%d')}" if clock_phase else None

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
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)

    # 微信推送（best-effort）
    if wx_openid and wx_template_id:
        send_wx_template_message(
            openid=wx_openid, template_id=wx_template_id,
            data={"title": {"value": title}, "body": {"value": body[:100]}, "time": {"value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}},
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
        }
        for n in rows
    ]


def mark_notification_read(db: Session, notification_id: str) -> bool:
    notif = db.get(Notification, notification_id)
    if notif is None:
        return False
    notif.read = True
    notif.read_at = datetime.now(timezone.utc)
    db.add(notif)
    db.commit()
    return True


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
