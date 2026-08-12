from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# 确保 llm_engine 通过 os.getenv 也能读到主仓迁移来的 Key
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    database_url: str = "sqlite:///./mealky.db"
    storestate_days: int = 7
    api_token: str = ""

    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    competition_collection_hour: int = 7
    competition_collection_minute: int = 30
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

    @property
    def is_dev(self) -> bool:
        return str(self.app_env or "").lower() in {"dev", "development", "local", "test"}

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
