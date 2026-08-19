"""OAuth state 签名 + 过期 + fail-closed 测试。"""
import base64
import json
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _signing_secret(monkeypatch):
    """注入签名密钥(独立于全局 settings 单例的创建时机)。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "jwt_secret", "test-jwt-secret", raising=False)
    monkeypatch.setattr(settings, "api_token", "test-api-token", raising=False)
    yield


def test_state_roundtrip_valid() -> None:
    from app.services.platform_oauth import build_oauth_state, parse_oauth_state

    state = build_oauth_state("meituan", store_id="s1")
    parsed = parse_oauth_state(state)
    assert parsed["platform"] == "meituan"
    assert parsed["store_id"] == "s1"


def test_state_tampered_rejected() -> None:
    from app.services.platform_oauth import build_oauth_state, parse_oauth_state

    state = build_oauth_state("meituan", store_id="s1")
    # 篡改 payload(换 store_id),保留原签名
    envelope = json.loads(base64.urlsafe_b64decode(state).decode())
    fake_payload = base64.urlsafe_b64encode(
        json.dumps({"platform": "meituan", "store_id": "victim", "issued_at": datetime.now(timezone.utc).isoformat()}).encode()
    ).decode()
    tampered = base64.urlsafe_b64encode(
        json.dumps({"payload": fake_payload, "sig": envelope["sig"]}).encode()
    ).decode()
    parsed = parse_oauth_state(tampered)
    assert parsed == {"platform": "", "store_id": ""}


def test_state_expired_rejected() -> None:
    from app.services.platform_oauth import _sign_state_payload, parse_oauth_state

    old_payload = json.dumps({
        "platform": "meituan", "store_id": "s1",
        "issued_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }).encode()
    envelope = json.dumps({
        "payload": base64.urlsafe_b64encode(old_payload).decode(),
        "sig": _sign_state_payload(old_payload),
    }).encode()
    expired = base64.urlsafe_b64encode(envelope).decode()
    assert parse_oauth_state(expired) == {"platform": "", "store_id": ""}


def test_state_garbage_rejected() -> None:
    from app.services.platform_oauth import parse_oauth_state

    assert parse_oauth_state("garbage") == {"platform": "", "store_id": ""}
    assert parse_oauth_state("") == {"platform": "", "store_id": ""}


def test_state_fails_closed_without_secret(monkeypatch) -> None:
    """无签名密钥 → parse 返回空(fail-closed),不冒充有效。"""
    from app.core.config import settings
    from app.services.platform_oauth import parse_oauth_state

    monkeypatch.setattr(settings, "jwt_secret", "", raising=False)
    monkeypatch.setattr(settings, "api_token", "", raising=False)
    # 任意 state 都应被拒
    assert parse_oauth_state("anything") == {"platform": "", "store_id": ""}
