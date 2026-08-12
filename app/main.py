from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import build_api_router
from app.core.config import settings
from app.core.security import (
    AuthPrincipal,
    decode_access_token,
    extract_bearer,
    verify_api_token,
)
from app.db.base import Base
from app.db.schema_backfill import apply_sqlite_schema_backfill
from app.db.session import SessionLocal, engine
from app.services.competition_collection import (
    backfill_legacy_competitor_watches,
)

# Import models so SQLAlchemy knows them
import app.models  # noqa: F401

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
# /public 仅 health/config；/auth/token 需在无会话时可用
PUBLIC_PATH_PREFIXES = ("/public/", "/static/", "/docs", "/openapi.json", "/redoc", "/auth/token")

# <img src> 无法带 header：仅菜品示意图代理免 token
_PUBLIC_IMAGE_PATHS = ("/item-image", "/food-image")

_STORE_PATH_RE = re.compile(
    r"^/(?:stores|workspace/stores|v1/stores|settings/stores)/([^/]+)"
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        with SessionLocal() as db:
            backfill_legacy_competitor_watches(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("startup backfill failed: %s", exc)
    yield


def _resolve_principal(request: Request) -> AuthPrincipal | None:
    bearer = extract_bearer(request.headers.get("authorization"))
    if bearer:
        try:
            return decode_access_token(bearer)
        except ValueError:
            return None

    api_token = request.headers.get("x-api-token", "")
    if api_token and verify_api_token(api_token):
        return AuthPrincipal(
            subject="api_token",
            role="admin",
            tenant_id=None,
            store_ids=(),
            auth_mode="api_token",
        )
    return None


def _store_id_from_path(path: str) -> str | None:
    match = _STORE_PATH_RE.match(path)
    if not match:
        return None
    store_id = match.group(1)
    # 排除非门店段
    if store_id in {"bootstrap", "intake", "recommendations", "experiments", "notifications"}:
        return None
    return store_id


def create_app() -> FastAPI:
    app = FastAPI(
        title="MealKey 餐启 · 外卖智能经营系统",
        version="0.1.0",
        lifespan=lifespan,
    )

    # V1: auto create tables for easy local start; replace with Alembic later
    Base.metadata.create_all(bind=engine)
    apply_sqlite_schema_backfill(engine)

    # 生产环境强制要求 token 或 jwt_secret
    if not settings.is_dev and not settings.api_token and not settings.jwt_secret:
        import sys

        logger.error("FATAL: API_TOKEN or JWT_SECRET must be set in production")
        sys.exit(1)

    @app.middleware("http")
    async def api_auth_guard(request: Request, call_next):
        path = request.url.path

        # 公开路径：首页 / 静态 / 文档 / 公开图片代理 / 换票
        if (
            path == "/"
            or any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)
            or any(path.endswith(suffix) for suffix in _PUBLIC_IMAGE_PATHS)
        ):
            return await call_next(request)

        # 开发环境无凭证时放行（方便本地与测试）
        if settings.is_dev and not settings.api_token and not settings.jwt_secret:
            request.state.principal = AuthPrincipal(
                subject="dev",
                role="admin",
                tenant_id=None,
                store_ids=(),
                auth_mode="api_token",
            )
            return await call_next(request)

        principal = _resolve_principal(request)
        if principal is None:
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})

        # 门店作用域：JWT operator 不得跨店
        if settings.jwt_enforce_store_scope:
            store_id = _store_id_from_path(path)
            if store_id and not principal.can_access_store(store_id):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "store out of tenant scope"},
                )

        request.state.principal = principal
        return await call_next(request)

    app.include_router(build_api_router())

    # 双保险：生产环境若仍残留 /dev 路由则剔除
    if not settings.is_dev:
        app.router.routes = [
            r
            for r in app.router.routes
            if not (hasattr(r, "path") and str(getattr(r, "path", "")).startswith("/dev"))
        ]

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def product_home():
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
