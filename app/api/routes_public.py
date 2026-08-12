from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.services.llm_engine import is_llm_configured, llm_status
from app.services.settings_store import get_setting

router = APIRouter()


@router.get("/health")
def public_health():
    """独立部署探活：不依赖主仓。"""
    status = llm_status()
    return {
        "ok": True,
        "service": "mealky-ai-backend",
        "standalone": True,
        "llm": {
            "configured": status["configured"],
            "engine": status["engine"],
            "depends_on_main_repo": False,
        },
        "app_env": settings.app_env,
    }


@router.get("/config")
def public_config():
    amap_js_key = get_setting("amap_js_api_key") or settings.amap_js_api_key
    amap_security_raw = get_setting("amap_js_security_code") or settings.amap_js_security_code
    amap_web = get_setting("amap_web_service_key") or settings.amap_web_service_key
    partner_url = get_setting("competition_partner_api_url") or settings.competition_partner_api_url
    partner_token = get_setting("competition_partner_api_token") or settings.competition_partner_api_token
    connector_url = get_setting("platform_connector_url") or settings.platform_connector_url

    # security_code 仅在开发环境下发给前端；生产环境应走受控注入，避免公开接口泄露。
    amap_security = amap_security_raw if settings.is_dev else ""
    return {
        "app_env": settings.app_env,
        "brand": {
            "name_en": "MealKey",
            "name_zh": "餐启",
            "positioning": "外卖智能经营系统",
        },
        "amap": {
            "enabled": bool(amap_js_key),
            "js_api_key": amap_js_key,
            "security_code": amap_security,
            "security_code_required": bool(amap_security_raw),
        },
        "platform": {
            "connector_configured": bool(connector_url),
            "demo_sync_enabled": True,
        },
        "llm": {
            "configured": is_llm_configured() or settings.llm_configured,
            "engine": "mealky-llm-engine-v1",
            "standalone": True,
            "depends_on_main_repo": False,
        },
        "competition_collection": {
            "enabled": bool(amap_web or (partner_url and partner_token)),
            "providers": [
                provider
                for provider, enabled in (
                    ("amap", bool(amap_web)),
                    ("licensed_partner", bool(partner_url and partner_token)),
                )
                if enabled
            ],
            "default_provider": (
                "amap"
                if amap_web
                else "licensed_partner"
                if (partner_url and partner_token)
                else None
            ),
            "schedule": (
                f"{settings.competition_collection_hour:02d}:"
                f"{settings.competition_collection_minute:02d}"
            ),
            "timezone": "Asia/Shanghai",
        },
    }


# ═══ 通知端点（受 token 保护，但放在 public 方便前端路径） ═══

from fastapi import Depends, Query
from sqlalchemy.orm import Session
from app.db.session import get_db


@router.get("/notifications/{store_id}")
def get_notifications(store_id: str, limit: int = Query(default=20, ge=1, le=50), db: Session = Depends(get_db)):
    """获取门店未读通知。"""
    from app.services.notification_service import get_unread_notifications
    return {"notifications": get_unread_notifications(db, store_id, limit)}


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: str, db: Session = Depends(get_db)):
    """标记通知已读。"""
    from app.services.notification_service import mark_notification_read
    ok = mark_notification_read(db, notification_id)
    return {"ok": ok}
