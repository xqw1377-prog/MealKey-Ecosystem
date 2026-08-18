"""上线审计回归：CORS / docs / 时钟 / readiness 真检查。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import adapt_database_url, settings
from app.core.cors import cors_allows_credentials, parse_cors_origins
from app.main import create_app
from app.services.operating_clock import should_run_inprocess_clock
from app.services.seed_launch import production_readiness


def test_cors_origins_parse_comma_and_json() -> None:
    assert parse_cors_origins("https://a.example.com,https://b.example.com") == [
        "https://a.example.com",
        "https://b.example.com",
    ]
    assert parse_cors_origins('["https://a.example.com"]') == ["https://a.example.com"]
    assert parse_cors_origins(["https://a.example.com"]) == ["https://a.example.com"]
    assert cors_allows_credentials(["*"]) is False
    assert cors_allows_credentials(["https://a.example.com"]) is True


def test_production_rejects_wildcard_cors(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "api_token", "prod-secret-token")
    monkeypatch.setattr(settings, "jwt_secret", "prod-jwt-secret-independent-32b!!")
    monkeypatch.setattr(settings, "cors_origins", "*")
    with pytest.raises(SystemExit):
        create_app()


def test_production_hides_openapi_and_keeps_health(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "api_token", "prod-secret-token")
    monkeypatch.setattr(settings, "jwt_secret", "prod-jwt-secret-independent-32b!!")
    monkeypatch.setattr(settings, "cors_origins", "https://app.example.com")
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    health = client.get("/public/health")
    assert health.status_code == 200
    assert health.headers.get("x-request-id")


def test_dev_keeps_docs(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "dev")
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_inprocess_clock_off_in_production() -> None:
    assert should_run_inprocess_clock({}, is_dev=False) is False
    assert should_run_inprocess_clock({}, is_dev=True) is True
    assert should_run_inprocess_clock({"MEALKEY_DISABLE_CLOCK": "1"}, is_dev=True) is False
    assert should_run_inprocess_clock({"MEALKEY_ENABLE_INPROCESS_CLOCK": "1"}, is_dev=False) is True
    assert should_run_inprocess_clock({"VERCEL": "1"}, is_dev=True) is False


def test_vercel_sqlite_uses_tmp() -> None:
    assert adapt_database_url("sqlite:///./mealky.db", {}) == "sqlite:///./mealky.db"
    assert adapt_database_url("sqlite:///./mealky.db", {"VERCEL": "1"}) == "sqlite:////tmp/mealky.db"
    assert adapt_database_url("postgresql://user:pass@host/db", {"VERCEL": "1"}).startswith("postgresql://")


def test_production_readiness_checks_are_real(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "database_url", "sqlite:///./mealky.db")
    monkeypatch.setattr(settings, "api_token", "")
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "cors_origins", "*")
    monkeypatch.setattr(settings, "run_schema_sync_on_startup", True)
    payload = production_readiness()
    assert payload["ready"] is False
    ids = {item["id"]: item["ok"] for item in payload["checks"]}
    assert ids["not_sqlite_in_prod"] is False
    assert ids["cors_allowlist"] is False
    assert ids["no_create_all_in_prod"] is False
    assert ids["secrets_not_in_repo"] is True
    assert ids["human_paste_without_connector"] is True
    assert ids["inprocess_clock_off"] is True
