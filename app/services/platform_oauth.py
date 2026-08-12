"""平台 OAuth 授权骨架 — 美团/饿了么开放平台对接预留。

当前是骨架——定义了完整的 OAuth 授权码流程接口，但实际平台 API
需要申请开发者资质后填充 client_id/client_secret/redirect_uri。

流程：
1. 老板点"连接美团" → POST /platforms/oauth/start → 返回授权 URL
2. 老板在美团授权页确认 → 美团回调 redirect_uri → POST /platforms/oauth/callback
3. 系统用 code 换 access_token + refresh_token → 存 PlatformConnection
4. 后续拉数据用 access_token
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode


@dataclass
class OAuthConfig:
    """平台 OAuth 配置。"""
    platform: str  # meituan / eleme
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    auth_url: str = ""  # 授权页 URL
    token_url: str = ""  # 换 token 的 URL
    scope: str = ""  # 授权范围


# 预设配置模板（需要填充真实值）
_OAUTH_CONFIGS: dict[str, OAuthConfig] = {
    "meituan": OAuthConfig(
        platform="meituan",
        auth_url="https://open-erp.meituan.com/oauth/authorize",  # 示例
        token_url="https://open-erp.meituan.com/oauth/token",
        scope="order_manage menu_manage review_manage ads_manage",
    ),
    "eleme": OAuthConfig(
        platform="eleme",
        auth_url="https://open.ele.me/oauth/authorize",  # 示例
        token_url="https://open.ele.me/oauth/token",
        scope="order menu review",
    ),
}


def get_oauth_url(platform: str, state: str = "") -> Optional[str]:
    """生成 OAuth 授权 URL。

    老板点击后跳转到平台授权页。
    需要先在设置里填 client_id + redirect_uri。
    """
    config = _OAUTH_CONFIGS.get(platform)
    if config is None or not config.client_id or not config.redirect_uri:
        return None
    params = urlencode({
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": config.scope,
        "state": state or platform,
    })
    return f"{config.auth_url}?{params}"


def exchange_code_for_token(platform: str, code: str) -> Optional[dict]:
    """用授权码换 access_token。

    需要平台开发者资质后实现。
    """
    config = _OAUTH_CONFIGS.get(platform)
    if config is None or not config.client_id or not config.client_secret:
        return None
    # TODO: 实际实现——POST config.token_url 换 token
    # import urllib.request
    # payload = urlencode({
    #     "grant_type": "authorization_code",
    #     "code": code,
    #     "client_id": config.client_id,
    #     "client_secret": config.client_secret,
    #     "redirect_uri": config.redirect_uri,
    # })
    # ... POST token_url → 解析 access_token / refresh_token / expires_in
    return None


def refresh_token(platform: str, refresh_token: str) -> Optional[dict]:
    """用 refresh_token 刷新 access_token。"""
    config = _OAUTH_CONFIGS.get(platform)
    if config is None or not config.client_id:
        return None
    # TODO: 实际实现
    return None


def is_oauth_configured(platform: str) -> bool:
    """检查某平台的 OAuth 是否配置完毕。"""
    config = _OAUTH_CONFIGS.get(platform)
    return config is not None and bool(config.client_id and config.client_secret and config.redirect_uri)


def configure_oauth(
    platform: str,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> None:
    """配置平台 OAuth（管理后台调用）。

    配置后持久化到设置表。
    """
    from app.services.settings_store import set_setting

    set_setting(f"oauth_{platform}_client_id", client_id)
    set_setting(f"oauth_{platform}_client_secret", client_secret)
    set_setting(f"oauth_{platform}_redirect_uri", redirect_uri)
    # 更新内存配置
    if platform in _OAUTH_CONFIGS:
        _OAUTH_CONFIGS[platform].client_id = client_id
        _OAUTH_CONFIGS[platform].client_secret = client_secret
        _OAUTH_CONFIGS[platform].redirect_uri = redirect_uri
