"""多租户 JWT 签发、作用域与兼容主 token。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.main import create_app
from app.services.tenant_service import create_tenant, ensure_default_tenant


def test_decode_access_token_roundtrip():
    token = create_access_token(
        subject="op1",
        tenant_id="t1",
        store_ids=["s1", "s2"],
        role="operator",
        expires_minutes=30,
    )
    principal = decode_access_token(token)
    assert principal.subject == "op1"
    assert principal.tenant_id == "t1"
    assert principal.store_ids == ("s1", "s2")
    assert principal.can_access_store("s1")
    assert not principal.can_access_store("s9")


def test_operator_with_empty_store_ids_is_denied_everywhere():
    """P0-3: operator 空授权门店必须 fail closed，不得 fail open 成全店权限。"""
    token = create_access_token(
        subject="op_empty",
        tenant_id="t1",
        store_ids=[],
        role="operator",
        expires_minutes=30,
    )
    principal = decode_access_token(token)
    assert principal.store_ids == ()
    assert principal.role == "operator"
    assert not principal.is_admin
    # 空 store_ids 的 operator 不得访问任意门店
    assert not principal.can_access_store("s1")
    assert not principal.can_access_store("s9")
    assert not principal.can_access_store("anything")


def test_issue_admin_jwt_with_api_token(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "master-secret")
    monkeypatch.setattr(settings, "jwt_secret", "jwt-test-secret-32bytes-minimum!!")
    monkeypatch.setattr(settings, "app_env", "dev")
    client = TestClient(create_app())
    seed = client.post("/dev/seed", headers={"x-api-token": "master-secret"})
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]

    issued = client.post(
        "/auth/token",
        json={"api_token": "master-secret", "store_id": store_id},
    )
    assert issued.status_code == 200
    body = issued.json()
    assert body["token_type"] == "bearer"
    assert store_id in body["store_ids"]
    assert body["role"] == "admin"

    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["is_admin"] is True


def test_tenant_jwt_store_scope_enforced(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "master-secret")
    monkeypatch.setattr(settings, "jwt_secret", "jwt-test-secret-32bytes-minimum!!")
    monkeypatch.setattr(settings, "jwt_enforce_store_scope", True)
    monkeypatch.setattr(settings, "app_env", "dev")
    app = create_app()
    client = TestClient(app)
    seed = client.post("/dev/seed", headers={"x-api-token": "master-secret"})
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]

    from uuid import uuid4

    from app.db.session import SessionLocal

    client_id = f"tenant_scoped_{uuid4().hex[:10]}"
    with SessionLocal() as db:
        ensure_default_tenant(db)
        tenant, secret = create_tenant(
            db,
            name="限权租户",
            store_ids=[store_id],
            client_id=client_id,
        )
        assert secret

    issued = client.post(
        "/auth/token",
        json={
            "client_id": client_id,
            "client_secret": secret,
            "store_id": store_id,
        },
    )
    assert issued.status_code == 200
    jwt = issued.json()["access_token"]

    ok = client.get(
        f"/v1/stores/{store_id}/workspace",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert ok.status_code == 200

    denied = client.get(
        "/v1/stores/not-your-store/workspace",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert denied.status_code == 403


def test_legacy_api_token_still_works(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "master-secret")
    monkeypatch.setattr(settings, "jwt_secret", "jwt-test-secret-32bytes-minimum!!")
    monkeypatch.setattr(settings, "app_env", "dev")
    client = TestClient(create_app())
    seed = client.post("/dev/seed", headers={"x-api-token": "master-secret"})
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]
    brief = client.get(
        f"/stores/{store_id}/manager_brief",
        headers={"x-api-token": "master-secret"},
    )
    assert brief.status_code == 200
