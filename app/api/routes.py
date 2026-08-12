from __future__ import annotations

from fastapi import APIRouter

from app.api.routes_competition import router as competition_router
from app.api.routes_dev import router as dev_router
from app.api.routes_goal import router as goal_router
from app.api.routes_mue import router as mue_router
from app.api.routes_public import router as public_router
from app.api.routes_runtime import router as runtime_router
from app.api.routes_settings import router as settings_router
from app.api.routes_speech import router as speech_router
from app.api.routes_store import router as store_router
from app.api.routes_workspace import router as workspace_router

router = APIRouter()

router.include_router(store_router, prefix="/stores", tags=["stores"])
router.include_router(
    competition_router,
    prefix="/stores",
    tags=["competition"],
)
router.include_router(dev_router, prefix="/dev", tags=["dev"])
router.include_router(goal_router, tags=["goals"])
router.include_router(mue_router, tags=["understanding"])
router.include_router(workspace_router, prefix="/workspace", tags=["workspace"])
router.include_router(speech_router, prefix="/speech", tags=["speech"])
router.include_router(settings_router, prefix="/settings", tags=["settings"])
router.include_router(public_router, prefix="/public", tags=["public"])
router.include_router(runtime_router, prefix="/v1", tags=["runtime"])
