# SEC-PLATFORM-01 Credential Hygiene

**级别：P0 Security**  
**范围极小：堵住当前明文 token 风险。不是统一 Secrets Platform。**

## 现在的问题

```text
PlatformConnection.meta_json
{
  oauth: {
    access_token: "...",
    refresh_token: "...",
    raw: { ... }
  }
}

GET /settings/stores/{id}/platforms
→ 原样返回 meta（含 token）
```

与 DATA-AS-01 / Authorized Session 无关。不要塞进授权店项目。

## 目标形态

```text
PlatformConnection.meta_json.oauth
{
  credential_ref: "oauth_secret:{store_id}:{platform}",
  credential_status: "ACTIVE",
  token_type: "bearer",
  scope: "...",
  rotate_recommended: false
}

AppSetting(is_secret=true)
  key   = credential_ref
  value = { access_token, refresh_token, ... }
```

普通设置 API 永远只返回：

```text
connected: true
expires_at: ...
scopes: [...]
credential_status: ACTIVE
```

绝不回 token。`credential_ref` 也不下发给普通业务 API。

## 迁移

读/写路径遇到 `meta_json` 里的明文 token：

1. 搬到 secret setting
2. 从 `meta_json` 删除 token / raw
3. 标记 `rotate_recommended=true`

若已是真实凭据：**迁移后建议 rotate / revoke，而不是只搬字段。**

## 明确不做

- 不做 KMS / Vault / 统一密钥平台
- 不改平台 connector 的拉数协议（服务端内部仍可把 token 交给 `platform_connector_url`）
- 不把本票并入 DATA-AS-01
