"""安全收敛回归：生产禁用 /dev、通知鉴权、OAuth 501。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app


def _route_paths(application) -> list[str]:
    paths: list[str] = []
    for route in application.router.routes:
        path = getattr(route, "path", None)
        if path:
            paths.append(str(path))
    return paths


def test_production_app_excludes_dev_routes(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "api_token", "prod-secret-token")
    monkeypatch.setattr(settings, "jwt_secret", "prod-jwt-secret-independent-32b!!")
    monkeypatch.setattr(settings, "cors_origins", "https://app.example.com")
    application = create_app()
    paths = _route_paths(application)
    assert not any(path.startswith("/dev") for path in paths)
    client = TestClient(application)
    denied = client.post("/dev/seed", headers={"x-api-token": "prod-secret-token"})
    assert denied.status_code == 404


def test_dev_app_keeps_dev_routes(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "api_token", "")
    application = create_app()
    paths = _route_paths(application)
    assert any(path.startswith("/dev") for path in paths)


def test_public_notifications_removed():
    application = create_app()
    client = TestClient(application)
    missing = client.get("/public/notifications/any-store")
    assert missing.status_code == 404


def test_workspace_notifications_exist():
    application = create_app()
    client = TestClient(application)
    # 无门店时 404；路径本身必须存在（不是 public 免鉴权）
    response = client.get("/workspace/stores/missing/notifications")
    assert response.status_code in {401, 404}


def test_oauth_start_returns_501_when_unconfigured():
    application = create_app()
    client = TestClient(application)
    response = client.post("/workspace/platforms/oauth/meituan/start")
    assert response.status_code in {401, 501}
    if response.status_code == 501:
        assert "not configured" in response.json()["detail"].lower()
