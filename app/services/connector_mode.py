"""Production never falls back to Mock.

DEV/TEST: mock 必须显式声明。
PROD: mock 禁止；缺失真实 connector = UNAVAILABLE，绝不能切到 mock。
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

MOCK_MODES = frozenset({"mock", "fixture", "sandbox"})
TEST_ONLY_MODES = frozenset({"daily_report_test"})
ALLOWED_MODES = frozenset({"mock", "http", "mobile", "oauth", "human_paste", "daily_report_test"})

CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
PLATFORM_UNAVAILABLE = "PLATFORM_UNAVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
SCHEMA_CHANGED = "SCHEMA_CHANGED"
DEGRADED = "DEGRADED"
REAL_FETCH_MODES = frozenset({"http", "mobile", "oauth"})


class ConnectorModeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def allows_mock() -> bool:
    return bool(settings.is_dev)


def assert_mode_allowed(mode: str | None, *, explicit: bool = False) -> str:
    requested = str(mode or "").strip().lower()
    if not requested:
        if allows_mock() and explicit:
            raise ConnectorModeError(PLATFORM_UNAVAILABLE, "未指定 connector mode，不能默认成 mock。")
        raise ConnectorModeError(PLATFORM_UNAVAILABLE, "真实 Connector 不可用，不能回退到 Mock。")
    if requested not in ALLOWED_MODES:
        raise ConnectorModeError(CONFIGURATION_ERROR, f"不支持的 connector mode: {requested}")
    if requested in MOCK_MODES and not allows_mock():
        raise ConnectorModeError(CONFIGURATION_ERROR, "生产环境禁止 Mock，且绝不能 fallback 到 Mock。")
    if requested in TEST_ONLY_MODES and not allows_mock():
        raise ConnectorModeError(
            CONFIGURATION_ERROR,
            "生产环境禁止未认证日报测试源（TEST-ADAPTER-01），且绝不能 fallback。",
        )
    return requested


def classify_connector_failure(exc: BaseException) -> ConnectorModeError:
    """真实 Connector 失败只能降级为 UNAVAILABLE / AUTH_REQUIRED / SCHEMA_CHANGED，绝不转 Mock。"""
    if isinstance(exc, ConnectorModeError):
        return exc
    text = str(exc)
    lowered = text.lower()
    if any(token in lowered for token in ("401", "403", "unauthorized", "auth_required", "token")):
        return ConnectorModeError(AUTH_REQUIRED, text)
    if any(token in lowered for token in ("schema", "422", "unprocessable")):
        return ConnectorModeError(SCHEMA_CHANGED, text)
    return ConnectorModeError(PLATFORM_UNAVAILABLE, text)


def resolve_fetch_mode(*, requested: str | None = None, connection_mode: str | None = None) -> str:
    """解析采集/同步 mode。缺失或非法时失败，绝不回退 mock。"""
    if requested:
        return assert_mode_allowed(requested, explicit=True)
    if connection_mode:
        return assert_mode_allowed(connection_mode, explicit=True)
    raise ConnectorModeError(PLATFORM_UNAVAILABLE, "没有可用的真实 Connector mode。")


def disable_production_mock_connectors(db: Session) -> list[str]:
    """生产启动：发现 mock connector 则禁用，不静默改走 mock。"""
    if allows_mock():
        return []
    from app.models.settings import PlatformConnection

    rows = db.execute(select(PlatformConnection)).scalars().all()
    disabled: list[str] = []
    for row in rows:
        mode = str(row.connector_mode or "").strip().lower()
        if mode not in MOCK_MODES and mode not in TEST_ONLY_MODES:
            continue
        row.status = "disabled"
        reason = "production forbids unauthenticated daily-report test source" if mode in TEST_ONLY_MODES else "production forbids mock"
        row.last_error = f"{CONFIGURATION_ERROR}: {reason}"
        db.add(row)
        disabled.append(row.id)
    if disabled:
        db.commit()
    return disabled


def iter_disabled_ids(ids: Iterable[str]) -> list[str]:
    return [str(item) for item in ids]
