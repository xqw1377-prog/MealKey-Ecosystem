"""PRE-PROD-GATE-01 安全修复回归测试。

P0-1: /settings/system PUT 只允许 admin
P0-2: Query 传 store_id 的路由必须在 handler 层校验门店作用域
P0-3: operator 空 store_ids 必须 DENY（见 test_auth_jwt.py）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "master-secret")
    monkeypatch.setattr(settings, "jwt_secret", "jwt-test-secret-32bytes-minimum!!")
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "jwt_enforce_store_scope", True)
    return TestClient(create_app())


def _operator_jwt(store_ids: list[str]) -> str:
    return create_access_token(
        subject="op1",
        tenant_id="t1",
        store_ids=store_ids,
        role="operator",
        expires_minutes=30,
    )


def _admin_jwt() -> str:
    return create_access_token(
        subject="admin",
        tenant_id=None,
        store_ids=[],
        role="admin",
        expires_minutes=30,
    )


# ── P0-1: 全局系统配置只能 admin 写 ──

def test_p0_1_operator_cannot_put_system_settings(client):
    """operator 不得改写全局平台密钥。"""
    token = _operator_jwt(["s1"])
    resp = client.put(
        "/settings/system",
        json={"settings": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


def test_p0_1_admin_can_put_system_settings(client):
    """admin 可写（空 patch 列表，不实际改配置）。"""
    token = _admin_jwt()
    resp = client.put(
        "/settings/system",
        json={"settings": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


def test_p0_1_api_token_can_put_system_settings(client):
    """主 API token（admin 等价）可写。"""
    resp = client.put(
        "/settings/system",
        json={"settings": []},
        headers={"x-api-token": "master-secret"},
    )
    assert resp.status_code == 200, resp.text


# ── P0-2: Query store_id 路由必须 handler 层校验作用域 ──

def test_p0_2_operator_cannot_read_other_store_settings_overview(client):
    """operator A 不得通过 Query 读取他店 settings overview。"""
    token = _operator_jwt(["s_own"])
    resp = client.get(
        "/settings/overview",
        params={"store_id": "s_victim"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


def test_p0_2_operator_cannot_read_other_store_platform_assist(client):
    token = _operator_jwt(["s_own"])
    resp = client.get(
        "/settings/assist/platform",
        params={"store_id": "s_victim"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


def test_p0_2_operator_cannot_collect_other_store_platform_intel(client):
    token = _operator_jwt(["s_own"])
    resp = client.post(
        "/v1/platform-intel/collect",
        params={"store_id": "s_victim"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


def test_p0_2_operator_cannot_start_oauth_for_other_store(client):
    token = _operator_jwt(["s_own"])
    resp = client.post(
        "/workspace/platforms/oauth/meituan/start",
        params={"store_id": "s_victim"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # 403 必须早于 OAuth 是否配置的 501 检查
    assert resp.status_code == 403, resp.text


def test_p0_2_admin_can_pass_store_scope(client):
    """admin 不受 store scope 限制（即便 store 不存在也应是 404，不是 403）。"""
    token = _admin_jwt()
    resp = client.get(
        "/settings/overview",
        params={"store_id": "s_nonexistent"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text


# ── P0-4: 生产强制独立 JWT_SECRET ──

def test_p0_4_production_without_jwt_secret_exits(monkeypatch):
    """生产环境仅设 API_TOKEN 无 JWT_SECRET → SystemExit(1)。"""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "api_token", "prod-secret-token")
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "cors_origins", "https://app.example.com")
    with pytest.raises(SystemExit):
        create_app()


def test_p0_4_production_with_jwt_secret_starts(monkeypatch):
    """生产环境设独立 JWT_SECRET + 合法 CORS → 正常启动。"""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "api_token", "prod-secret-token")
    monkeypatch.setattr(settings, "jwt_secret", "prod-jwt-secret-independent-32b!!")
    monkeypatch.setattr(settings, "cors_origins", "https://app.example.com")
    app = create_app()
    # jwt_secret() 在生产不得走 api_token 派生回退
    from app.core.security import jwt_secret
    assert jwt_secret() == "prod-jwt-secret-independent-32b!!"


# ── P0-7: seed_demo 幂等 ──

def test_p0_7_seed_demo_is_idempotent(client):
    """连续两次 seed 不报错，返回相同 store_id（幂等，不重复创建）。"""
    first = client.post("/dev/seed", headers={"x-api-token": "master-secret"})
    assert first.status_code == 200, first.text
    first_store = first.json()["store_id"]

    second = client.post("/dev/seed", headers={"x-api-token": "master-secret"})
    assert second.status_code == 200, second.text
    second_store = second.json()["store_id"]

    assert first_store == second_store, "seed_demo 非幂等：第二次返回了不同的 store"
