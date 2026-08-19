from __future__ import annotations

from fastapi import APIRouter

from app.api.routes_auth import router as auth_router
from app.api.routes_competition import router as competition_router
from app.api.routes_cost import router as cost_router
from app.api.routes_commercial import router as commercial_router
from app.api.routes_decision_core import router as decision_core_router
from app.api.routes_benchmark import router as benchmark_router
from app.api.routes_cases import router as cases_router
from app.api.routes_dev import router as dev_router
from app.api.routes_governance import router as governance_router
from app.api.routes_goal import router as goal_router
from app.api.routes_import import router as import_router
from app.api.routes_mue import router as mue_router
from app.api.routes_ops import router as ops_router
from app.api.routes_operating_demands import router as operating_demands_router
from app.api.routes_platform_intel import router as platform_intel_router
from app.api.routes_oci import router as oci_router
from app.api.routes_public import router as public_router
from app.api.routes_runtime import router as runtime_router
from app.api.routes_settings import router as settings_router
from app.api.routes_speech import router as speech_router
from app.api.routes_store import router as store_router
from app.api.routes_workspace import router as workspace_router
from app.api.routes_data_acquisition import router as data_acquisition_router
from app.api.routes_growth import router as growth_router
from app.core.config import settings


def iter_api_routers() -> list[tuple[APIRouter, str, list[str]]]:
    routers: list[tuple[APIRouter, str, list[str]]] = [
        (auth_router, "/auth", ["auth"]),
        (store_router, "/stores", ["stores"]),
        (competition_router, "/stores", ["competition"]),
        (goal_router, "", ["goals"]),
        (mue_router, "", ["understanding"]),
        (workspace_router, "/workspace", ["workspace"]),
        (speech_router, "/speech", ["speech"]),
        (settings_router, "/settings", ["settings"]),
        (public_router, "/public", ["public"]),
        (runtime_router, "/v1", ["runtime"]),
        (decision_core_router, "", ["decision-core"]),
        (cost_router, "", ["cost"]),
        (commercial_router, "/v1", ["commercial"]),
        (operating_demands_router, "/v1", ["operating-demands"]),
        (platform_intel_router, "/v1", ["platform-intel"]),
        (oci_router, "/v1", ["operating-cases"]),
        (import_router, "", ["import"]),
        (data_acquisition_router, "/v1", ["data-acquisition"]),
        (benchmark_router, "", ["benchmark"]),
        (cases_router, "", ["cases"]),
        (governance_router, "", ["governance"]),
        (ops_router, "", ["ops-diagnosis"]),
        (growth_router, "", ["growth"]),
    ]
    if settings.is_dev:
        routers.insert(3, (dev_router, "/dev", ["dev"]))
    return routers


def build_api_router() -> APIRouter:
    """按当前环境动态组装路由（生产永不挂载 /dev）。"""
    api = APIRouter()
    for router_obj, prefix, tags in iter_api_routers():
        api.include_router(router_obj, prefix=prefix, tags=tags)
    return api


# 兼容旧 import：默认按当前 settings 构建一次
router = build_api_router()
