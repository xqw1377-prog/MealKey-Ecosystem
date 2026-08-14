from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match

from app.api.routes import iter_api_routers
from app.core.config import settings
from app.core.cors import cors_allows_credentials
from app.core.logging import configure_logging, init_sentry, install_request_id_middleware
from app.core.security import (
    AuthPrincipal,
    decode_access_token,
    extract_bearer,
    verify_api_token,
)
from app.db.session import SessionLocal, engine
from app.services.competition_collection import (
    backfill_legacy_competitor_watches,
)

# Import models so SQLAlchemy knows them
import app.models  # noqa: F401

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
# /public 仅 health/config；/auth/token 需在无会话时可用
PUBLIC_PATH_PREFIXES = ("/public/", "/static/", "/auth/token", "/r/")

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
    clock_stop = None
    try:
        from app.services.operating_clock import start_inprocess_clock

        clock_stop = start_inprocess_clock()
    except Exception as exc:  # noqa: BLE001
        logger.warning("in-process clock failed to start: %s", exc)
    yield
    if clock_stop is not None:
        try:
            clock_stop.set()
        except Exception:  # noqa: BLE001
            pass


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


class _RoutePathPlaceholder:
    """仅用于让嵌套路由路径在审计/测试里可见，不参与真实匹配。"""

    def __init__(self, path: str) -> None:
        self.path = path

    def matches(self, scope):  # type: ignore[no-untyped-def]
        return Match.NONE, scope


def _expose_included_router_paths(app: FastAPI) -> None:
    seen = {str(getattr(route, "path", "")) for route in app.router.routes if getattr(route, "path", None)}
    placeholders = []
    for route in app.router.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if not callable(contexts):
            continue
        for ctx in contexts():
            path = str(getattr(ctx, "path", "") or "").strip()
            if not path or path in seen:
                continue
            placeholders.append(_RoutePathPlaceholder(path))
            seen.add(path)
    app.router.routes.extend(placeholders)


def create_app() -> FastAPI:
    configure_logging(json_logs=settings.json_logs_enabled)
    init_sentry(dsn=settings.sentry_dsn, environment=str(settings.app_env))

    app = FastAPI(
        title="MealKey 餐启 · 外卖智能经营系统",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_dev else None,
        redoc_url="/redoc" if settings.is_dev else None,
        openapi_url="/openapi.json" if settings.is_dev else None,
    )

    if settings.is_dev:
        from app.db.base import Base
        from app.db.schema_backfill import apply_schema_backfill

        Base.metadata.create_all(bind=engine)
        apply_schema_backfill(engine)
    elif settings.run_schema_sync_on_startup:
        logger.error("FATAL: RUN_SCHEMA_SYNC_ON_STARTUP is not allowed in production; run alembic")
        raise SystemExit(1)
    elif settings.run_alembic_on_startup:
        from app.db.migration_runner import run_alembic_upgrade_head

        run_alembic_upgrade_head()

    # 生产环境强制要求 token 或 jwt_secret
    if not settings.is_dev and not settings.api_token and not settings.jwt_secret:
        logger.error("FATAL: API_TOKEN or JWT_SECRET must be set in production")
        raise SystemExit(1)

    from fastapi.middleware.cors import CORSMiddleware

    cors_origins = settings.cors_origin_list or (["*"] if settings.is_dev else [])
    if not settings.is_dev and (not cors_origins or "*" in cors_origins):
        logger.error("FATAL: production CORS_ORIGINS must be an explicit allowlist, not *")
        raise SystemExit(1)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_allows_credentials(cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_request_id_middleware(app)

    @app.middleware("http")
    async def api_auth_guard(request: Request, call_next):
        path = request.url.path

        # 生产已关闭文档路由：放行以便返回 404，而不是被鉴权拦成 401
        if not settings.is_dev and path in {"/docs", "/redoc", "/openapi.json", "/docs/", "/redoc/"}:
            return await call_next(request)

        # 公开路径：首页 / 静态 / 公开图片代理 / 换票
        if (
            path == "/"
            or path == "/commercial-os"
            or path == "/competitive-strategy"
            or path == "/operating-demands"
            or path == "/store-tasks"
            or path.startswith("/r/")
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

    for router_obj, prefix, tags in iter_api_routers():
        app.include_router(router_obj, prefix=prefix, tags=tags)
    _expose_included_router_paths(app)

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

        @app.get("/commercial-os", include_in_schema=False)
        def commercial_os_v1():
            return FileResponse(STATIC_DIR / "commercial-os-v1.html")

        @app.get("/competitive-strategy", include_in_schema=False)
        def competitive_strategy_v1():
            return FileResponse(STATIC_DIR / "competitive-strategy-v1.html")

        @app.get("/operating-demands", include_in_schema=False)
        def operating_demand_library():
            return FileResponse(STATIC_DIR / "operating-demands-v1.html")

        @app.get("/store-tasks", include_in_schema=False)
        def store_task_board():
            return FileResponse(STATIC_DIR / "store-tasks.html")

        @app.get("/r/{artifact_id}", include_in_schema=False)
        def result_share_card(artifact_id: str):
            return FileResponse(STATIC_DIR / "result-card.html")

    return app


app = create_app()
