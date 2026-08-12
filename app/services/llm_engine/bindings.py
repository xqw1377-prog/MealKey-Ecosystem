from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

PurposeProvider = Literal["kimi", "deepseek", "qianwen", "doubao"]

LlmPurpose = str


@dataclass(frozen=True)
class PurposeModelCandidate:
    id: str
    provider: PurposeProvider
    model: str
    base_url: str
    api_key_env: str
    quality_tier: str = "balanced"


def _env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    # 独立部署时也允许设置页（DB）覆盖，不依赖主仓
    try:
        from app.services.settings_store import get_setting

        return (get_setting(name.lower()) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def resolve_capability_purpose(purpose: LlmPurpose) -> str:
    mapping = {
        "brand_design": "brand.structured_output",
        "space_design": "space.structured_output",
        "polish": "general.polish",
        "consulting": "general.consulting",
        "mwork": "general.consulting",
        "compiler": "general.consulting",
        "expert_l1": "general.consulting",
        "menu.simulation_explain": "menu.simulation_explain",
        "menu.order_simulation_explain": "menu.order_simulation_explain",
    }
    return mapping.get(purpose, purpose)


def _unique(items: list[PurposeModelCandidate]) -> list[PurposeModelCandidate]:
    seen: set[str] = set()
    out: list[PurposeModelCandidate] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)
    return out


def list_consulting_chain() -> list[PurposeModelCandidate]:
    chain: list[PurposeModelCandidate] = []
    if _env("DEEPSEEK_API_KEY"):
        chain.append(
            PurposeModelCandidate(
                id="general:deepseek-chat",
                provider="deepseek",
                model=_env("CONSULTING_PRIMARY_MODEL")
                or _env("DEEPSEEK_FLAGSHIP_MODEL")
                or "deepseek-v4-pro",
                base_url=_env("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
                api_key_env="DEEPSEEK_API_KEY",
                quality_tier="balanced",
            )
        )
    if _env("QWEN_API_KEY") or _env("DASHSCOPE_API_KEY"):
        chain.append(
            PurposeModelCandidate(
                id="general:qwen-plus",
                provider="qianwen",
                model=_env("CONSULTING_QWEN_FALLBACK_MODEL")
                or _env("QWEN_UTILITY_MODEL")
                or "qwen3.6-flash",
                base_url=_env("QWEN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_env="QWEN_API_KEY" if _env("QWEN_API_KEY") else "DASHSCOPE_API_KEY",
                quality_tier="fast",
            )
        )
    if _env("MOONSHOT_API_KEY") or _env("KIMI_API_KEY"):
        chain.append(
            PurposeModelCandidate(
                id="general:kimi",
                provider="kimi",
                model=_env("KIMI_LONG_CONTEXT_MODEL") or "kimi-k3",
                base_url=_env("MOONSHOT_BASE_URL") or "https://api.moonshot.cn/v1",
                api_key_env="MOONSHOT_API_KEY" if _env("MOONSHOT_API_KEY") else "KIMI_API_KEY",
                quality_tier="balanced",
            )
        )
    return _unique(chain)


def list_menu_analysis_chain() -> list[PurposeModelCandidate]:
    return [
        PurposeModelCandidate(
            id=c.id.replace("general:", "menu.analysis:", 1),
            provider=c.provider,
            model=c.model,
            base_url=c.base_url,
            api_key_env=c.api_key_env,
            quality_tier=c.quality_tier,
        )
        for c in list_consulting_chain()
    ]


def list_brand_text_chain() -> list[PurposeModelCandidate]:
    chain: list[PurposeModelCandidate] = []
    if _env("MOONSHOT_API_KEY") or _env("KIMI_API_KEY"):
        model = _env("MDESIGN_BRAND_MODEL") or "kimi-k3"
        chain.append(
            PurposeModelCandidate(
                id=f"brand.text:kimi:{model}",
                provider="kimi",
                model=model,
                base_url=_env("MOONSHOT_BASE_URL") or "https://api.moonshot.cn/v1",
                api_key_env="MOONSHOT_API_KEY" if _env("MOONSHOT_API_KEY") else "KIMI_API_KEY",
                quality_tier="flagship",
            )
        )
    if _env("QWEN_API_KEY") or _env("DASHSCOPE_API_KEY"):
        chain.append(
            PurposeModelCandidate(
                id="brand.text:qwen-plus",
                provider="qianwen",
                model=_env("BRAND_QWEN_FALLBACK_MODEL")
                or _env("QWEN_STRUCTURED_MODEL")
                or "qwen3.7-plus",
                base_url=_env("QWEN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_env="QWEN_API_KEY" if _env("QWEN_API_KEY") else "DASHSCOPE_API_KEY",
                quality_tier="balanced",
            )
        )
    if _env("DEEPSEEK_API_KEY"):
        chain.append(
            PurposeModelCandidate(
                id="brand.text:deepseek-chat",
                provider="deepseek",
                model=_env("DEEPSEEK_FAST_MODEL") or "deepseek-v4-flash",
                base_url=_env("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
                api_key_env="DEEPSEEK_API_KEY",
                quality_tier="balanced",
            )
        )
    return _unique(chain)


def list_space_text_chain() -> list[PurposeModelCandidate]:
    chain: list[PurposeModelCandidate] = []
    if _env("QWEN_API_KEY") or _env("DASHSCOPE_API_KEY"):
        chain.append(
            PurposeModelCandidate(
                id="space.text:qwen-max",
                provider="qianwen",
                model=_env("SPACE_QWEN_FALLBACK_MODEL")
                or _env("QWEN_STRUCTURED_MODEL")
                or "qwen3.7-plus",
                base_url=_env("QWEN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_env="QWEN_API_KEY" if _env("QWEN_API_KEY") else "DASHSCOPE_API_KEY",
                quality_tier="flagship",
            )
        )
    if _env("DEEPSEEK_API_KEY"):
        chain.append(
            PurposeModelCandidate(
                id="space.text:deepseek-chat",
                provider="deepseek",
                model=_env("DEEPSEEK_FLAGSHIP_MODEL") or "deepseek-v4-pro",
                base_url=_env("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
                api_key_env="DEEPSEEK_API_KEY",
                quality_tier="balanced",
            )
        )
    if _env("MOONSHOT_API_KEY") or _env("KIMI_API_KEY"):
        chain.append(
            PurposeModelCandidate(
                id="space.text:kimi",
                provider="kimi",
                model=_env("KIMI_LONG_CONTEXT_MODEL") or "kimi-k3",
                base_url=_env("MOONSHOT_BASE_URL") or "https://api.moonshot.cn/v1",
                api_key_env="MOONSHOT_API_KEY" if _env("MOONSHOT_API_KEY") else "KIMI_API_KEY",
                quality_tier="balanced",
            )
        )
    return _unique(chain)


def resolve_purpose_model_chain(purpose: LlmPurpose) -> list[PurposeModelCandidate]:
    cap = resolve_capability_purpose(purpose)
    if cap.startswith("brand."):
        return list_brand_text_chain()
    if cap.startswith("space."):
        return list_space_text_chain()
    if cap.startswith("menu."):
        return list_menu_analysis_chain()
    return list_consulting_chain()


def resolve_candidate_api_key(candidate: PurposeModelCandidate) -> str | None:
    if candidate.api_key_env and _env(candidate.api_key_env):
        return _env(candidate.api_key_env)
    if candidate.provider == "kimi":
        return _env("MOONSHOT_API_KEY") or _env("KIMI_API_KEY") or None
    if candidate.provider == "deepseek":
        return _env("DEEPSEEK_API_KEY") or None
    if candidate.provider == "qianwen":
        return _env("QWEN_API_KEY") or _env("DASHSCOPE_API_KEY") or None
    if candidate.provider == "doubao":
        return _env("ARK_API_KEY") or None
    return None


def is_purpose_chain_configured(purpose: LlmPurpose = "general.consulting") -> bool:
    return any(resolve_candidate_api_key(c) for c in resolve_purpose_model_chain(purpose))
