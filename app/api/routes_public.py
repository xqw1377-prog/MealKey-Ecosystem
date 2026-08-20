from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
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
        "deployment_tier": settings.deployment_tier or settings.app_env,
    }


@router.get("/readiness")
def public_readiness():
    """生产探活：Postgres / 密钥 / 备份脚本 / 商户隔离。不返回密钥值。"""
    from app.services.seed_launch import production_readiness

    payload = production_readiness()
    return {
        "ok": payload["ready"] or settings.is_dev,
        "ready": payload["ready"],
        "app_env": payload["app_env"],
        "database": payload["database"],
        "https_note": payload["https_note"],
        "checks": [{"id": item["id"], "ok": item["ok"]} for item in payload["checks"]],
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
        "deployment_tier": settings.deployment_tier or settings.app_env,
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
        "auth": {
            "required": bool(settings.api_token),
            "mode": "api_token" if settings.api_token else "dev_open",
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
        "platform_intel": {
            "enabled": True,
            "schedule": (
                f"{settings.platform_intel_hour:02d}:"
                f"{settings.platform_intel_minute:02d}"
            ),
            "timezone": "Asia/Shanghai",
            "scope": "official_public_pages",
        },
    }


class FreeAuditRequest(BaseModel):
    store_name: str = Field(min_length=1, max_length=80)
    city: str = ""
    category: str = ""
    pain: str = ""


@router.get("/artifacts/{artifact_id}")
def get_public_artifact(artifact_id: str, db: Session = Depends(get_db)):
    from app.services.commercial.growth import bump_views, get_artifact, public_card, share_url_for

    artifact = get_artifact(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="结果卡不存在")
    bump_views(db, artifact)
    db.commit()
    return public_card(artifact, share_url=share_url_for(artifact.id))


@router.post("/artifacts/{artifact_id}/audit")
def post_public_free_audit(
    artifact_id: str,
    payload: FreeAuditRequest,
    db: Session = Depends(get_db),
):
    from app.services.commercial.growth import get_artifact, run_free_audit

    artifact = get_artifact(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="结果卡不存在")
    result = run_free_audit(
        db,
        artifact,
        store_name=payload.store_name,
        city=payload.city,
        category=payload.category,
        pain=payload.pain,
    )
    db.commit()
    return result


class StoreTaskEvidenceInput(BaseModel):
    kind: str = "note"
    note: str = ""
    data_url: str = ""


def _store_tasks_payload(db: Session, token: str) -> dict:
    from app.services.store_ops import list_open_human_tasks, load_roster, project_task, store_id_for_token

    store_id = store_id_for_token(db, token)
    if not store_id:
        raise HTTPException(status_code=404, detail="门店任务页无效或已过期")
    roster = load_roster(db, store_id)
    tasks = [project_task(item) for item in list_open_human_tasks(db, store_id)]
    return {
        "ok": True,
        "store_id": store_id,
        "manager_name": roster.get("manager_name") or "店长",
        "tasks": tasks,
    }


@router.get("/store-tasks/{token}")
def public_store_tasks(token: str, db: Session = Depends(get_db)):
    return _store_tasks_payload(db, token)


@router.post("/store-tasks/{token}/{loop_id}/evidence")
def public_store_task_evidence(
    token: str,
    loop_id: str,
    payload: StoreTaskEvidenceInput,
    db: Session = Depends(get_db),
):
    from app.services.store_ops import attach_evidence, store_id_for_token

    store_id = store_id_for_token(db, token)
    if not store_id:
        raise HTTPException(status_code=404, detail="门店任务页无效或已过期")
    try:
        item = attach_evidence(
            db,
            store_id,
            loop_id,
            kind=payload.kind,
            note=payload.note,
            data_url=payload.data_url,
            by="STORE",
        )
    except ValueError as exc:
        message = str(exc)
        code = 404 if "not found" in message else 409
        raise HTTPException(status_code=code, detail=message) from exc
    from app.services.store_ops import project_task

    return {"ok": True, "task": project_task(item)}


@router.post("/store-tasks/{token}/{loop_id}/done")
def public_store_task_done(token: str, loop_id: str, db: Session = Depends(get_db)):
    from app.services.closed_loop import mark_loop_executed, project_loop
    from app.services.store_ops import store_id_for_token

    store_id = store_id_for_token(db, token)
    if not store_id:
        raise HTTPException(status_code=404, detail="门店任务页无效或已过期")
    try:
        item = mark_loop_executed(db, store_id, loop_id, executor="STORE")
    except ValueError as exc:
        message = str(exc)
        code = 404 if "not found" in message else 409
        raise HTTPException(status_code=code, detail=message) from exc
    return {"ok": True, "loop": project_loop(item)}
