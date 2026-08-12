from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.session import get_db
from app.models.entities import Menu, MenuItem, MenuItemVersion, Store
from app.models.settings import PlatformConnection
from app.schemas.settings import (
    AssistAskRequest,
    MenuSettingsUpdate,
    OwnerProfileUpdate,
    PlatformConnectRequest,
    StoreSettingsUpdate,
    SystemSettingsUpdate,
)
from app.services.ai_assist import answer_assist_question, assist_deploy, assist_platform, build_setup_checklist
from app.services.daily_job import run_daily_job
from app.services.llm_engine.gateway import llm_status
from app.services.platform_connectors import list_platforms
from app.services.platform_sync import sync_store_platform
from app.services.settings_store import EDITABLE_KEYS, get_setting, list_system_settings, upsert_setting

router = APIRouter()


def _load_store(db: Session, store_id: str) -> Store | None:
    return db.execute(
        select(Store).options(joinedload(Store.merchant), joinedload(Store.items)).where(Store.id == store_id)
    ).unique().scalar_one_or_none()


def _store_settings_payload(store: Store) -> dict[str, Any]:
    merchant = store.merchant
    return {
        "store_id": store.id,
        "name": store.name,
        "city": store.city,
        "area": store.area,
        "address": store.address,
        "category": getattr(merchant, "category", None),
        "cuisine_type": getattr(merchant, "cuisine_type", None),
        "business_hours": getattr(merchant, "business_hours", None),
        "audience": store.primary_audience,
        "pain": store.primary_pain,
        "latitude": store.latitude,
        "longitude": store.longitude,
        "delivery_radius_m": store.delivery_radius_m,
        "platform": store.platform,
        "platform_store_key": store.platform_store_key,
        "merchant_name": getattr(merchant, "name", None),
    }


def _menu_settings_payload(db: Session, store_id: str) -> dict[str, Any]:
    items = db.execute(
        select(MenuItem).where(MenuItem.store_id == store_id).order_by(MenuItem.created_at.asc())
    ).scalars().all()
    rows = []
    for item in items:
        version = item.current_version
        if version is None:
            continue
        rows.append(
            {
                "item_id": item.id,
                "name": version.name,
                "category": version.category,
                "price": version.price,
                "description": version.description,
                "is_active": item.is_active,
            }
        )
    return {"store_id": store_id, "items": rows, "count": len(rows)}


def _owner_profile_key(store_id: str) -> str:
    return f"owner_profile:{store_id}"


def _default_owner_profile(store: Store | None = None) -> dict[str, Any]:
    store_name = store.name if store else ""
    return {
        "store_id": store.id if store else None,
        "store_name": store_name,
        "display_name": "老板",
        "phone": "",
        "role": "老板",
        "avatar_initial": "王",
        "avatar_data_url": None,
    }


def _load_owner_profile(db: Session, store: Store) -> dict[str, Any]:
    raw = get_setting(_owner_profile_key(store.id), db)
    base = _default_owner_profile(store)
    if not raw:
        return base
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return base
    if not isinstance(data, dict):
        return base
    display_name = str(data.get("display_name") or base["display_name"]).strip() or "老板"
    phone = str(data.get("phone") or "").strip()
    role = str(data.get("role") or base["role"]).strip() or "老板"
    avatar_data_url = data.get("avatar_data_url")
    if avatar_data_url is not None:
        avatar_data_url = str(avatar_data_url).strip() or None
        if avatar_data_url and not avatar_data_url.startswith("data:image/"):
            avatar_data_url = None
        if avatar_data_url and len(avatar_data_url) > 240_000:
            avatar_data_url = None
    initial = display_name[:1] if display_name else "王"
    return {
        "store_id": store.id,
        "store_name": store.name,
        "display_name": display_name,
        "phone": phone,
        "role": role,
        "avatar_initial": initial,
        "avatar_data_url": avatar_data_url,
    }


def _env_fallback() -> dict[str, str | None]:
    return {
        "amap_web_service_key": settings.amap_web_service_key,
        "amap_js_api_key": settings.amap_js_api_key,
        "amap_js_security_code": settings.amap_js_security_code,
        "platform_connector_url": settings.platform_connector_url,
        "platform_connector_token": settings.platform_connector_token,
        "competition_partner_api_url": settings.competition_partner_api_url,
        "competition_partner_api_token": settings.competition_partner_api_token,
        "deepseek_api_key": settings.deepseek_api_key,
        "qwen_api_key": settings.qwen_api_key,
        "dashscope_api_key": settings.dashscope_api_key,
        "moonshot_api_key": settings.moonshot_api_key,
        "ark_api_key": settings.ark_api_key,
        "asr_service_url": settings.asr_service_url,
        "asr_service_token": settings.asr_service_token,
        "asr_api_key": settings.asr_api_key,
        "asr_base_url": settings.asr_base_url,
        "asr_model": settings.asr_model,
        "DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "QWEN_API_KEY": settings.qwen_api_key,
        "DASHSCOPE_API_KEY": settings.dashscope_api_key,
        "MOONSHOT_API_KEY": settings.moonshot_api_key,
        "ARK_API_KEY": settings.ark_api_key,
        "ASR_SERVICE_URL": settings.asr_service_url,
        "ASR_SERVICE_TOKEN": settings.asr_service_token,
        "ASR_API_KEY": settings.asr_api_key,
        "ASR_BASE_URL": settings.asr_base_url,
        "ASR_MODEL": settings.asr_model,
    }


@router.get("/overview")
def settings_overview(store_id: str | None = Query(default=None), db: Session = Depends(get_db)):
    store = _load_store(db, store_id) if store_id else None
    if store_id and store is None:
        raise HTTPException(status_code=404, detail="store not found")
    checklist = build_setup_checklist(db, store)
    platforms = []
    if store:
        connections = db.execute(
            select(PlatformConnection).where(PlatformConnection.store_id == store.id)
        ).scalars().all()
        platforms = [
            {
                "platform": row.platform,
                "status": row.status,
                "connector_mode": row.connector_mode,
                "external_store_id": row.external_store_id,
                "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
                "last_error": row.last_error,
            }
            for row in connections
        ]
    return {
        "checklist": checklist,
        "store": _store_settings_payload(store) if store else None,
        "menu": _menu_settings_payload(db, store.id) if store else None,
        "owner": _load_owner_profile(db, store) if store else None,
        "system": list_system_settings(db, _env_fallback()),
        "platforms": platforms,
        "available_platforms": list_platforms(),
        "ai": {
            "deploy": assist_deploy(),
            "platform": assist_platform(db, store),
        },
        "llm": llm_status(),
    }


@router.get("/llm/status")
def get_llm_status():
    return llm_status()


@router.get("/stores/{store_id}")
def get_store_settings(store_id: str, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return _store_settings_payload(store)


@router.put("/stores/{store_id}")
def update_store_settings(store_id: str, payload: StoreSettingsUpdate, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "city", "area", "address", "latitude", "longitude", "delivery_radius_m", "platform", "platform_store_key"):
        if field in data:
            setattr(store, field, data[field])
    if "audience" in data:
        store.primary_audience = data["audience"]
    if "pain" in data:
        store.primary_pain = data["pain"]
    merchant = store.merchant
    if merchant is not None:
        if "category" in data:
            merchant.category = data["category"]
        if "cuisine_type" in data:
            merchant.cuisine_type = data["cuisine_type"]
        if "business_hours" in data:
            merchant.business_hours = data["business_hours"]
        if "name" in data and not merchant.brand_name:
            merchant.name = data["name"]
        db.add(merchant)
    db.add(store)
    db.commit()
    db.refresh(store)
    return {
        "store": _store_settings_payload(store),
        "checklist": build_setup_checklist(db, store),
    }


@router.get("/stores/{store_id}/owner")
def get_owner_profile(store_id: str, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return _load_owner_profile(db, store)


@router.put("/stores/{store_id}/owner")
def update_owner_profile(store_id: str, payload: OwnerProfileUpdate, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")

    display_name = payload.display_name.strip() or "老板"
    phone = (payload.phone or "").strip()
    role = (payload.role or "老板").strip() or "老板"
    avatar_data_url = (payload.avatar_data_url or "").strip() or None
    if avatar_data_url:
        if not avatar_data_url.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="头像格式无效，请上传图片")
        if len(avatar_data_url) > 240_000:
            raise HTTPException(status_code=400, detail="头像太大，请换一张更小的图片")

    profile = {
        "display_name": display_name,
        "phone": phone,
        "role": role,
        "avatar_data_url": avatar_data_url,
    }
    upsert_setting(
        db,
        _owner_profile_key(store_id),
        json.dumps(profile, ensure_ascii=False),
        is_secret=False,
        description="门店操作者个人资料",
    )
    db.commit()
    return _load_owner_profile(db, store)


@router.get("/stores/{store_id}/menu")
def get_menu_settings(store_id: str, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return _menu_settings_payload(db, store_id)


@router.put("/stores/{store_id}/menu")
def replace_menu_settings(store_id: str, payload: MenuSettingsUpdate, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    if not payload.items:
        raise HTTPException(status_code=400, detail="至少保留 1 个菜单商品")

    menu = db.execute(
        select(Menu).where(Menu.store_id == store_id, Menu.status == "active").limit(1)
    ).scalar_one_or_none()
    if menu is None:
        menu = Menu(store_id=store_id, name="默认菜单", type="delivery", version=1, status="active")
        db.add(menu)
        db.flush()

    existing = db.execute(select(MenuItem).where(MenuItem.store_id == store_id)).scalars().all()
    for item in existing:
        item.is_active = False
        db.add(item)

    for row in payload.items:
        item = MenuItem(store_id=store_id, menu_id=menu.id, is_active=row.is_active)
        db.add(item)
        db.flush()
        version = MenuItemVersion(
            item_id=item.id,
            name=row.name.strip(),
            category=row.category,
            price=row.price,
            description=row.description,
            source="settings",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        db.add(item)

    db.commit()
    return {
        "menu": _menu_settings_payload(db, store_id),
        "checklist": build_setup_checklist(db, store),
    }


@router.get("/system")
def get_system_settings(db: Session = Depends(get_db)):
    return {"settings": list_system_settings(db, _env_fallback()), "app_env": settings.app_env}


@router.put("/system")
def update_system_settings(payload: SystemSettingsUpdate, db: Session = Depends(get_db)):
    if not settings.is_dev and settings.api_token == "":
        # 生产未设 token 时仍允许改非密钥业务项；密钥建议走环境变量
        pass
    for patch in payload.settings:
        meta = EDITABLE_KEYS.get(patch.key)
        if meta is None:
            raise HTTPException(status_code=400, detail=f"unsupported setting: {patch.key}")
        upsert_setting(
            db,
            patch.key,
            patch.value,
            is_secret=meta["is_secret"],
            description=meta["description"],
        )
    db.commit()
    return {"settings": list_system_settings(db, _env_fallback())}


@router.get("/platforms")
def get_platforms():
    return {"platforms": list_platforms()}


@router.post("/stores/{store_id}/platforms/connect")
def connect_platform(store_id: str, payload: PlatformConnectRequest, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    if payload.mode == "mobile":
        connection = db.execute(
            select(PlatformConnection).where(
                PlatformConnection.store_id == store_id,
                PlatformConnection.platform == payload.platform,
            )
        ).scalar_one_or_none()
        if connection is None:
            connection = PlatformConnection(
                store_id=store_id,
                platform=payload.platform,
                status="pending",
                connector_mode="mobile",
            )
            db.add(connection)
        else:
            connection.status = "pending"
            connection.connector_mode = "mobile"
            db.add(connection)
        db.commit()
        return {
            "mode": "mobile",
            "status": "pending",
            "message": "已创建手机连接待确认。请生成连接码，或在开发环境使用演示对接。",
            "checklist": build_setup_checklist(db, store),
        }

    try:
        result = sync_store_platform(db, store, payload.platform, mode=payload.mode)
    except ValueError as exc:
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    daily = None
    if payload.run_daily_job:
        daily = run_daily_job(db=db, store_id=store_id, days=7)
    db.commit()
    return {
        "sync": result,
        "daily_job": {
            "observations": len(daily.observations) if daily else 0,
            "top_actions": len(daily.top_actions) if daily else 0,
        }
        if daily
        else None,
        "checklist": build_setup_checklist(db, store),
        "message": "平台数据已同步" + ("，并完成诊断刷新" if daily else ""),
    }


@router.get("/stores/{store_id}/platforms")
def list_store_platforms(store_id: str, db: Session = Depends(get_db)):
    store = _load_store(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    rows = db.execute(select(PlatformConnection).where(PlatformConnection.store_id == store_id)).scalars().all()
    return {
        "store_id": store_id,
        "links": [
            {
                "platform": row.platform,
                "status": row.status,
                "connector_mode": row.connector_mode,
                "external_store_id": row.external_store_id,
                "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
                "last_error": row.last_error,
                "meta": json.loads(row.meta_json) if row.meta_json else {},
            }
            for row in rows
        ],
    }


@router.get("/assist/deploy")
def get_deploy_assist():
    return assist_deploy()


@router.get("/assist/platform")
def get_platform_assist(store_id: str | None = Query(default=None), db: Session = Depends(get_db)):
    store = _load_store(db, store_id) if store_id else None
    if store_id and store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return assist_platform(db, store)


@router.post("/assist/ask")
def ask_assist(payload: AssistAskRequest, db: Session = Depends(get_db)):
    store = _load_store(db, payload.store_id) if payload.store_id else None
    if payload.store_id and store is None:
        raise HTTPException(status_code=404, detail="store not found")
    answered = answer_assist_question(payload.question, db=db, store=store)
    if answered is None:
        return {
            "intent": "general",
            "conclusion": "我可以协助：1）部署启动 2）外卖平台对接 3）基础数据设置。直接问其中一件即可。",
            "actions": ["打开设置补齐门店资料", "一键演示对接美团", "查看部署命令"],
            "guide": {"setup": build_setup_checklist(db, store)},
        }
    return answered
