from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.cors import parse_cors_origins

# 确保 llm_engine 通过 os.getenv 也能读到主仓迁移来的 Key
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def adapt_database_url(url: str, environ: Mapping[str, str] | None = None) -> str:
    """Vercel 函数文件系统只读，SQLite 必须落到 /tmp。"""
    env = environ if environ is not None else os.environ
    if str(env.get("VERCEL") or "") != "1":
        return url
    text = (url or "").strip()
    if text.startswith("sqlite") and ":memory:" not in text and "/tmp/" not in text:
        return "sqlite:////tmp/mealky.db"
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    database_url: str = "sqlite:///./mealky.db"
    run_schema_sync_on_startup: bool = False
    run_alembic_on_startup: bool = False
    storestate_days: int = 7
    api_token: str = ""
    # 多租户 JWT（生产务必单独配置 JWT_SECRET）
    jwt_secret: str = ""
    jwt_expire_minutes: int = 60 * 24 * 7
    jwt_enforce_store_scope: bool = True

    # CORS — 逗号分隔；也兼容 JSON 数组。开发默认 * ；生产必须显式白名单。
    cors_origins: str = "*"
    sentry_dsn: str = ""
    log_json: str = ""  # 空=生产开 JSON 日志；0/1 可强制

    # 种子客户对公转账（不走微信自动扣费）
    seed_bank_payee: str = ""
    seed_bank_account: str = ""
    seed_bank_name: str = ""

    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    competition_collection_hour: int = 7
    competition_collection_minute: int = 30
    platform_intel_hour: int = 7
    platform_intel_minute: int = 45
    daily_job_hour: int = 8
    daily_job_minute: int = 0

    amap_web_service_key: str = ""
    amap_js_api_key: str = ""
    amap_js_security_code: str = ""
    competition_partner_api_url: str = ""
    competition_partner_api_token: str = ""
    platform_connector_url: str = ""
    platform_connector_token: str = ""

    # LLM（主仓智能引擎配置；密钥放 .env，勿提交）
    deepseek_api_key: str = ""
    qwen_api_key: str = ""
    dashscope_api_key: str = ""
    moonshot_api_key: str = ""
    ark_api_key: str = ""
    asr_service_url: str = ""
    asr_service_token: str = ""
    asr_api_key: str = ""
    asr_base_url: str = ""
    asr_model: str = ""
    llm_use_purpose_policy: str = "1"

    @model_validator(mode="after")
    def _serverless_sqlite(self) -> Settings:
        adapted = adapt_database_url(self.database_url)
        if adapted != self.database_url:
            self.database_url = adapted
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _cors_origins_as_str(cls, value: object) -> str:
        if value is None:
            return "*"
        if isinstance(value, (list, tuple, set)):
            joined = ",".join(str(item).strip() for item in value if str(item).strip())
            return joined or "*"
        text = str(value).strip()
        return text or "*"

    @property
    def is_dev(self) -> bool:
        return str(self.app_env or "").lower() in {"dev", "development", "local", "test"}

    @property
    def cors_origin_list(self) -> list[str]:
        return parse_cors_origins(self.cors_origins)

    @property
    def json_logs_enabled(self) -> bool:
        raw = str(self.log_json or "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return not self.is_dev

    @property
    def llm_configured(self) -> bool:
        return bool(
            self.deepseek_api_key
            or self.qwen_api_key
            or self.dashscope_api_key
            or self.moonshot_api_key
            or self.ark_api_key
        )


settings = Settings()
