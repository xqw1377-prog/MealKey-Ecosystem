"""Vercel 识别的 FastAPI 入口：复用 app.main.app。"""

from app.main import app

__all__ = ["app"]
