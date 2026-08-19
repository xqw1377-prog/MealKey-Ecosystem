## MealKey 餐启 · 外卖智能经营系统（V1）

目标：**简单部署、简单对接、简单上手**。AI 会在设置页协助你完成部署与平台对接。

### 5 分钟上手

**方式 A · Windows**

```powershell
.\scripts\start.ps1
```

**方式 B · Docker**

```bash
docker compose up -d
```

**方式 C · 手动**

```bash
pip install -r requirements.txt
copy .env.example .env   # Windows；macOS/Linux 用 cp
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开：

- 看板：http://127.0.0.1:8000/
- 设置：侧栏「设置」或底部「AI协助上手」
- API 文档（仅开发）：http://127.0.0.1:8000/docs

本地默认 **SQLite**，不需要 Redis / Celery。定时任务是可选增强。生产关闭 `/docs`，CORS 必须配置 `CORS_ORIGINS` 域名白名单，节律只跑 Celery beat。

### 大模型智能引擎（独立部署副本）

本系统 **单独部署**，内置完整引擎副本：`app/services/llm_engine/`  
**运行时不依赖** 主仓 Next.js / agent-proxy / Prisma。

能力：

- Purpose 路由：`general.consulting` / `menu.analysis` / `brand.*` / `space.*`
- 静默 Failover：同能力链内切换 DeepSeek / 千问 / Kimi
- AI 店长对话优先走大模型，失败回退规则引擎
- 密钥来源：部署机 `.env`（推荐）或设置页 LLM 分组（DB 覆盖）

独立部署：

```bash
# 1) 准备含 LLM Key 的 .env（可从主仓 apps/web/.env 复制 LLM 段）
# 2) 启动
docker compose up -d --build
# 3) 探活
curl http://127.0.0.1:8000/public/health
```

状态：

- `GET /public/health` → `llm.configured` / `standalone: true`
- `GET /settings/llm/status`
- 看板「设置」→「内置大模型智能引擎」

### AI 协助部署与对接

在看板里可以直接问：

- 「怎么部署启动？」
- 「怎么对接美团/饿了么？」
- 「基础数据还缺什么？」

或打开 **设置中心**：

1. 看清单补齐门店 / 菜单 / 平台
2. 点「一键演示对接美团」立刻同步示例数据并刷新诊断
3. 正式环境在「系统与平台密钥」填写 `platform_connector_url`

### 设置模块（基础数据）

| 区块 | 做什么 |
|---|---|
| 门店基础资料 | 店名、城市、商圈、品类、客群、经纬度、配送半径 |
| 菜单基础数据 | 手工维护菜单，或由平台同步写入 |
| 系统与平台密钥 | 高德 Key、平台对接 URL/Token、竞品 Partner |
| 平台连接 | mock 演示 / HTTP 正式 / 手机连接码 |

相关 API：

- `GET /settings/overview?store_id=...`
- `PUT /settings/stores/{store_id}`
- `PUT /settings/stores/{store_id}/menu`
- `PUT /settings/system`
- `POST /settings/stores/{store_id}/platforms/connect`
- `GET /settings/assist/deploy`
- `GET /settings/assist/platform`
- `POST /settings/assist/ask`

### 外卖平台对接契约（HTTP）

你的适配服务接收：

```json
{
  "platform": "meituan",
  "store_id": "门店ID",
  "external_store_id": "平台侧门店ID"
}
```

返回：

```json
{
  "external_store_id": "mt_123",
  "store_name": "门店名",
  "menu_items": [{"name": "招牌盖饭", "price": 28, "category": "主食"}],
  "daily_metrics": [
    {"day": "2026-08-01", "impressions": 4000, "visits": 900, "orders": 120, "gmv": 4600}
  ]
}
```

配置项：`PLATFORM_CONNECTOR_URL` / `PLATFORM_CONNECTOR_TOKEN`（也可在设置页保存）。

> 美团/饿了么官方经营 API 需商家授权；竞品菜单与评价不得绕过登录抓取。竞品可用高德发现、授权快照或持牌 Partner。

### TEST-ADAPTER-01（仅 DEV/TEST，不是 DATA-AS-01）

`DailyReportTestConnector` 是产品锁定的日报夹具：第三方日报 → 适配 → 不完整 `PlatformSnapshot` / Facts → `StoreState(test)` → POIE → ODO。

- **不是** 生产 Connector，**不可晋升**。`truth_eligible=false`，`provenance=TEST_ONLY`，写回禁用。
- **不** 接入 `AuthorizedSessionConnector`，也不是美团/饿了么官方连接器。
- Canonical `impressions` / `visits` / `orders` / `gmv` 保持 UNKNOWN，禁止用进店率 × 曝光反推绝对值。
- 默认关闭。`APP_ENV=prod` fail-closed。详见 [`docs/test_adapter_01_daily_report.md`](docs/test_adapter_01_daily_report.md)。

```text
DAILY_REPORT_TEST_ENABLED=0
DAILY_REPORT_TEST_BASE_URL=
```

### 核心能力

- **MealKey AI 店长（Chief Agent）**：老板只面对一个店长 agent，它用原生 function calling（ReAct 模式）按需调度 12 个专业 agent，把结果汇总成「先结论→理由→动作→预期影响」的回答。`POST /workspace/stores/{store_id}/ask`。LLM 未配置时自动降级到规则意图分类 + agent 调用，保证可用性。
- **十二专业 Agent**：商圈竞争 / 菜单 / 商品 / **线上装修** / 经营诊断 / 增长策略 + 六矩阵专家（平台活动 / 投流 / 用户关系 / AI 客服 / 评分评价 / 线上门店增长）
- **MealKey Score 统一健康分**：跨 agent 5 维加权（商品30%/菜单20%/竞争20%/趋势20%/评价10%），首页核心数字。`GET .../manager_brief` 返回 `mealkey_score.total` + 5 维明细。
- **晨报升级**：首页从「1 问题+1 机会」升级为「3 问题 + 3 今日任务 + 量化预计影响」，像 AI 经理而非 dashboard。`ManagerHomeBrief.problems` / `tasks`。
- 线上装修诊断：头图·招牌·分类·套餐·评分区 → 销售影响预估 → 可落库改造动作
- AI 协助装修 / AI 优化主图：`POST .../storefront/ai/decorate`、`POST .../storefront/ai/optimize-image`（无 Key 时规则模板兜底）
- **Agent 自然语言总结（LLM 增强）**：diagnosis / review / menu / growth 四个核心 Agent 的总结可由 LLM 重写为更口语化的中文。默认关闭，设 `MEALKY_AGENT_LLM=1` 启用；失败自动回退到规则引擎结论。结果落在 `agent.meta.ai_narrative` / `ai_mode`，前端可优先展示、回退到 `conclusion`。
- **实验归因闭环**：已过观察窗的实验会被自动评估（计算 lift → 落库 result → 沉淀 strategy_memory），让 growth Agent 的 `plan_progress_pct` 和 `learning_summary` 真实反映已完成实验。
- **AgentContext 缓存**：店长按需调用单个专业 agent 时，复用 5 分钟 TTL 缓存的 context，不必每次重建（动作执行后自动失效）。
- OHRE：observation → hypothesis → recommendation → experiment
- 工作台：动作采纳执行、实验评估、AI 店长对话
- 商圈采集：高德 / Partner / 手机连接码（可选）

### 店长调度架构（13 Agent 团队）

```
                         商家老板
                             |
                    MealKey AI 店长 (chief_agent)
                  (ReAct + function calling 调度)
                             |
        12 个专业 Agent (按需调用，不全部跑)
        数据感知: 竞争 / 评价
        经营理解: 诊断 / 用户关系
        商品能力: 菜单 / 商品 / 线上装修
        增长执行: 平台活动 / 投流 / AI客服
        规模化:   线上门店增长 / 增长策略
```

关键文件：
- `app/services/chief_agent.py` — 店长 ReAct 调度器 + 规则降级
- `app/services/agent_context_cache.py` — context TTL 缓存
- `app/services/mealkey_score.py` — 5 维加权统一健康分
- `app/services/llm_engine/client.py` + `gateway.py` — 原生 function calling 支持

### 矩阵 Agent 可调阈值

六个矩阵专家（promo/ads/crm/service/review/store_matrix）的所有判定阈值集中在 `app/services/matrix_agents/thresholds.py`，方便调参。修改后建议跑 `tests/test_matrix_agents.py` 回归。未来按品类覆盖的钩子已预留（`category_overrides`）。

### 可选：Celery 定时

```bash
python -m celery -A app.jobs.celery_app.celery_app worker --loglevel=INFO
python -m celery -A app.jobs.celery_app.celery_app beat --loglevel=INFO
```

定时任务（beat）：

| 任务 | 说明 |
|---|---|
| `competition.collect_all_stores` | 每日采集商圈竞品快照 |
| `ops.run_daily_job_all_stores` | 每日生成 observation/hypothesis/recommendation |
| `ops.attribute_experiments_all_stores` | 每日（daily_job 后 30 分钟）归因已过观察窗的实验 |

未启动 Redis/Celery 时，用设置页演示对接，或调用：

- `/stores/{id}/competition/collect`、`/stores/{id}/daily_job`
- `POST /dev/attribute-experiments/{store_id}` 手动归因单店
- `POST /dev/attribute-experiments` 手动归因全店
- `POST /workspace/experiments/{id}/evaluate` 手动评估单条实验（force 重算）
