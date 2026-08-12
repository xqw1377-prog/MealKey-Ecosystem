from __future__ import annotations

import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.competition_collection import (
    backfill_legacy_competitor_watches,
)

# Import models so SQLAlchemy knows them
import app.models  # noqa: F401

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
PUBLIC_PATH_PREFIXES = ("/public/", "/static/", "/docs", "/openapi.json", "/redoc")

# P2-13: 需要放开但无需 token 的公开图片路径（<img src> 无法带 header）
_PUBLIC_IMAGE_PATHS = ("/item-image", "/food-image")


def create_app() -> FastAPI:
    app = FastAPI(title="MealKey 餐启 · 外卖智能经营系统", version="0.1.0")

    # V1: auto create tables for easy local start; replace with Alembic later
    Base.metadata.create_all(bind=engine)

    # P2-13: backfill 移到 startup（不在 import 时执行，多 worker 不重复）
    @app.on_event("startup")
    def _startup_backfill():
        try:
            with SessionLocal() as db:
                backfill_legacy_competitor_watches(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup backfill failed: %s", exc)

    # P0-2: 生产环境强制要求 token
    if not settings.is_dev and not settings.api_token:
        import sys
        logger.error("FATAL: API_TOKEN must be set in production (APP_ENV != dev)")
        sys.exit(1)

    @app.middleware("http")
    async def api_token_guard(request: Request, call_next):
        path = request.url.path

        # 公开路径：首页 / 静态 / 文档 / 公开图片代理
        if (
            path == "/"
            or any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)
            or any(path.endswith(suffix) for suffix in _PUBLIC_IMAGE_PATHS)
        ):
            return await call_next(request)

        # P0-2: 开发环境无 token 时放行
        if settings.is_dev and not settings.api_token:
            return await call_next(request)

        # P0-2: 生产环境必须有 token
        if not settings.api_token:
            return JSONResponse(status_code=401, content={"detail": "server not configured: API_TOKEN required"})

        # P0-2: 只接受 header，不接受 query 参数（防日志泄露）
        token = request.headers.get("x-api-token", "")

        # P0-2: 常量时间比较（防时序攻击）
        if not hmac.compare_digest(token, settings.api_token):
            return JSONResponse(status_code=401, content={"detail": "invalid api token"})

        return await call_next(request)

    # P0-2: 生产环境禁用 /dev 路由
    if not settings.is_dev:
        # 过滤掉 dev 路由
        app.router.routes = [
            r for r in app.router.routes
            if not (hasattr(r, "path") and "/dev/" in r.path)
        ]

    app.include_router(api_router)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def product_home():
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
