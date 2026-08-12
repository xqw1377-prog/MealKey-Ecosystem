"""消息推送服务 — AI 主动经营需要能"找到老板"。

支持两种推送渠道：
1. 微信模板消息（需要微信公众号/小程序 access_token）
2. 站内消息（写入 Notification 表，前端轮询/SSE 拉取）

推送触发场景：
- POIE 仲裁后 need_you/need_assist 的决策卡
- Goal 偏差预警
- 实验结果通知
- Safe Mode 提醒
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

NotificationType = Literal[
    "need_you",        # 需要老板确认/协助
    "goal_deviation",  # 目标偏差预警
    "experiment_result",  # 实验结果
    "safe_mode",       # Safe Mode 提醒
    "opportunity",     # 机会提醒
]


def _wx_configured() -> bool:
    """检查微信推送是否配置。"""
    return bool(getattr(settings, "wechat_app_id", None) and getattr(settings, "wechat_app_secret", None))


def send_wx_template_message(
    *,
    openid: str,
    template_id: str,
    data: dict[str, Any],
    url: str = "",
    mini_program: dict | None = None,
) -> bool:
    """发送微信模板消息（需要先获取 access_token）。

    生产环境需要配置 wechat_app_id + wechat_app_secret。
    失败不阻塞主流程，只记日志。
    """
    if not _wx_configured():
        logger.info("wx push skipped: not configured")
        return False
    try:
        import urllib.request

        # 获取 access_token（生产应缓存）
        token_url = (
            f"https://api.weixin.qq.com/cgi-bin/token?"
            f"grant_type=client_credential&appid={settings.wechat_app_id}&secret={settings.wechat_app_secret}"
        )
        with urllib.request.urlopen(token_url, timeout=10) as resp:
            token_data = json.loads(resp.read())
        access_token = token_data.get("access_token")
        if not access_token:
            logger.warning("wx push: no access_token")
            return False

        payload = {"touser": openid, "template_id": template_id, "url": url, "data": data}
        if mini_program:
            payload["miniprogram"] = mini_program
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        return result.get("errcode") == 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("wx push failed: %s", exc)
        return False


def create_in_app_notification(
    db: Session,
    *,
    store_id: str,
    notification_type: NotificationType,
    title: str,
    body: str = "",
    priority: str = "normal",  # urgent / high / normal / low
    action_url: str = "",
) -> str:
    """创建站内消息（写入通知存储，前端轮询拉取）。

    返回 notification_id。这是最可靠的推送方式——不依赖微信配置。
    """
    # 用 AppSetting 表存通知（避免新加表）
    from app.models.settings import AppSetting

    notif_id = f"notif-{store_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    notif_data = {
        "id": notif_id,
        "store_id": store_id,
        "type": notification_type,
        "title": title,
        "body": body,
        "priority": priority,
        "action_url": action_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read": False,
    }
    # 写入 AppSetting（key=notification:{id}）
    setting = AppSetting(
        key=f"notification:{notif_id}",
        value=json.dumps(notif_data, ensure_ascii=False),
    )
    db.add(setting)
    db.commit()
    return notif_id


def get_unread_notifications(db: Session, store_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """获取门店未读通知。"""
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


def mark_notification_read(db: Session, notification_id: str) -> bool:
    """标记通知已读。"""
    from app.models.settings import AppSetting

    setting = db.execute(
        select(AppSetting).where(AppSetting.key == f"notification:{notification_id}")
    ).scalar_one_or_none()
    if setting is None:
        return False
    try:
        data = json.loads(setting.value)
        data["read"] = True
        setting.value = json.dumps(data, ensure_ascii=False)
        db.add(setting)
        db.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def notify_store_owner(
    db: Session,
    *,
    store_id: str,
    notification_type: NotificationType,
    title: str,
    body: str = "",
    priority: str = "normal",
    wx_openid: str | None = None,
    wx_template_id: str | None = None,
) -> str:
    """统一推送入口：站内消息 + 微信模板消息（如果配置了）。

    返回 notification_id。
    """
    notif_id = create_in_app_notification(
        db,
        store_id=store_id,
        notification_type=notification_type,
        title=title,
        body=body,
        priority=priority,
    )

    # 微信推送（best-effort）
    if wx_openid and wx_template_id:
        send_wx_template_message(
            openid=wx_openid,
            template_id=wx_template_id,
            data={
                "title": {"value": title},
                "body": {"value": body[:100]},
                "time": {"value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
            },
        )

    return notif_id
