# MealKey 大模型智能引擎（独立部署副本）

本目录是主仓 `Mealkey Ai/apps/web/src/server/llm-engine` 的 **Python 独立副本**。

## 设计原则

1. **可单独部署**：本系统不依赖主仓 Next.js、Prisma、agent-proxy。
2. **直连厂商**：通过 OpenAI 兼容协议调用 DeepSeek / 千问 / Kimi / 豆包。
3. **Purpose 路由 + 静默 Failover**：同一能力链内切换供应商；整链失败再回退规则引擎。
4. **密钥本地持有**：部署机 `.env` 或设置页写入；镜像内不烘焙密钥。

## 模块

| 文件 | 职责 |
|---|---|
| `bindings.py` | Purpose → 模型链、API Key 解析 |
| `client.py` | OpenAI 兼容 `chat/completions` |
| `gateway.py` | `call_llm` / Failover / 状态 |
| `store_manager.py` | AI 店长经营问答 |

## 运行时配置

优先读进程环境变量（由 `.env` / Docker `env_file` 注入）：

- `DEEPSEEK_API_KEY` / `DEEPSEEK_*_MODEL`
- `QWEN_API_KEY` 或 `DASHSCOPE_API_KEY`
- `MOONSHOT_API_KEY`
- `ARK_API_KEY`（豆包，可选）

探测：`GET /settings/llm/status`、`GET /public/health`

## 与主仓关系

- 配置与模型偏好从主仓复制，便于同一套 Key 开箱即用。
- 运行时 **不再调用** 主仓 HTTP。主仓升级引擎时，按需再同步本目录逻辑即可。
