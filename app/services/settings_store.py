from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.settings import AppSetting

# 可在设置页改写的系统键
EDITABLE_KEYS: dict[str, dict[str, Any]] = {
    "amap_web_service_key": {
        "label": "高德 Web 服务 Key",
        "is_secret": True,
        "description": "用于周边竞品 POI 扫描",
        "group": "maps",
    },
    "amap_js_api_key": {
        "label": "高德 JS API Key",
        "is_secret": True,
        "description": "用于前端竞争地图",
        "group": "maps",
    },
    "amap_js_security_code": {
        "label": "高德 JS 安全密钥",
        "is_secret": True,
        "description": "仅开发环境会下发给前端",
        "group": "maps",
    },
    "platform_connector_url": {
        "label": "外卖平台对接地址",
        "is_secret": False,
        "description": "你的平台适配服务 URL，接收统一 JSON 契约",
        "group": "platform",
    },
    "platform_connector_token": {
        "label": "平台对接 Token",
        "is_secret": True,
        "description": "调用平台适配服务时的鉴权 Token",
        "group": "platform",
    },
    "competition_partner_api_url": {
        "label": "竞品数据 Partner URL",
        "is_secret": False,
        "description": "持牌/授权竞品数据源",
        "group": "competition",
    },
    "competition_partner_api_token": {
        "label": "竞品 Partner Token",
        "is_secret": True,
        "description": "竞品数据源鉴权",
        "group": "competition",
    },
    "asr_service_url": {
        "label": "ASR 服务地址",
        "is_secret": False,
        "description": "独立语音转写服务 URL，例如 https://asr.example.com",
        "group": "speech",
    },
    "asr_service_token": {
        "label": "ASR 服务 Token",
        "is_secret": True,
        "description": "调用独立语音服务时的鉴权 Token",
        "group": "speech",
    },
    "asr_api_key": {
        "label": "ASR 回退 API Key",
        "is_secret": True,
        "description": "独立语音服务不可用时的回退转写密钥",
        "group": "speech",
    },
    "asr_base_url": {
        "label": "ASR 回退 Base URL",
        "is_secret": False,
        "description": "OpenAI 兼容 ASR 回退地址",
        "group": "speech",
    },
    "asr_model": {
        "label": "ASR 回退模型",
        "is_secret": False,
        "description": "OpenAI 兼容 ASR 回退模型名",
        "group": "speech",
    },
    "auto_pilot_level": {
        "label": "AI 自动经营等级",
        "is_secret": False,
        "description": "0=全部问我；1=零风险动作自动（改标题/描述）；2=低风险可回滚动作自动；3=中风险也可自动",
        "group": "autopilot",
    },
}


def _mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}***{value[-2:]}"


def get_setting(key: str, db: Session | None = None) -> Optional[str]:
    owns = db is None
    session = db or SessionLocal()
    try:
        row = session.execute(select(AppSetting).where(AppSetting.key == key).limit(1)).scalar_one_or_none()
        if row and row.value is not None and str(row.value).strip() != "":
            return str(row.value)
        return None
    finally:
        if owns:
            session.close()


def upsert_setting(
    db: Session,
    key: str,
    value: str | None,
    *,
    is_secret: bool = False,
    description: str | None = None,
) -> AppSetting:
    row = db.execute(select(AppSetting).where(AppSetting.key == key).limit(1)).scalar_one_or_none()
    if row is None:
        row = AppSetting(key=key, value=value, is_secret=is_secret, description=description)
        db.add(row)
    else:
        # 空字符串表示清空；前端传 **** 或占位则保留原值
        if value is None:
            pass
        elif value.strip() == "":
            row.value = ""
        elif "***" in value or set(value.strip()) <= {"*"}:
            # 前端回传掩码时保留原值
            pass
        else:
            row.value = value
        if description:
            row.description = description
        row.is_secret = is_secret
        db.add(row)
    db.flush()
    return row


def list_system_settings(db: Session, env_fallback: dict[str, str | None]) -> list[dict[str, Any]]:
    rows = {
        row.key: row
        for row in db.execute(select(AppSetting).where(AppSetting.key.in_(tuple(EDITABLE_KEYS)))).scalars().all()
    }
    result = []
    for key, meta in EDITABLE_KEYS.items():
        db_value = rows[key].value if key in rows else None
        # LLM 键同时兼容 ENV 大写名（DEEPSEEK_API_KEY）
        env_value = env_fallback.get(key) or env_fallback.get(key.upper())
        effective = db_value if db_value not in (None, "") else env_value
        configured = bool(effective)
        result.append(
            {
                "key": key,
                "label": meta["label"],
                "group": meta["group"],
                "description": meta["description"],
                "is_secret": meta["is_secret"],
                "configured": configured,
                "value": _mask(effective) if meta["is_secret"] else (effective or ""),
                "source": "database" if db_value not in (None, "") else ("env" if env_value else "empty"),
            }
        )
    return result
