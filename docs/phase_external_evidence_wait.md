# Phase: SEED-STORE PILOT READY · NOT PRODUCTION READY

**产品状态：`Seed-store pilot ready，not production ready。`（2026-08-18 冻结）**  
**工程主题：`Execution & Truth Convergence`（已冻结）**  
**试点合同：[seed_store_01.md](seed_store_01.md)**

> MealKey 已具备第一家真实种子店的受控只读试点条件，但尚未具备正式生产门店连接条件。

升级理由：2026-08-18 全面审计确认服务能正常启动、171 条路由注册、核心业务端点（manager_brief / dashboard / chief agent ask）工作正常；但安全与迁移层存在真实生产风险。即使明天美团测试店到位，**也不要立刻接真实 OAuth / session**。先过 PRE-PROD-GATE-01。

内部扩建停止。`BLOCKED_EXTERNAL` **不是待开发**，而是：

> 缺外部前置条件，因此 **禁止开发**。

授权店出现前，`AuthorizedSessionConnector.fetch() = UNAVAILABLE` 就是正确实现。  
MT-LIFT 许可明确前，Research Zone **不得碰原始数据**。

不要再寻找“还能补什么功能”。下一阶段只回答两个真实世界问题：

1. **MealKey 能不能连续拿到可信 Business Truth？**
2. **MealKey 能不能比简单前后对比更可靠地判断一个动作真正产生了多少增量？**

这两件一旦有真实证据，下一轮产品决策才值得继续。

## 当前状态树

**Execution & Truth Convergence 已冻结（2026-08-18）。** 不再新增 Production Invariants，九条已足够。后面任何新能力只问：

> 它是不是绕开了 Execution Choke Point？  
> 它是不是绕开了 Truth Promotion？

任意一个答案是「是」，就不允许进生产。

```text
SEED-STORE-01                   FROZEN
Product                         Seed-store pilot ready, not production ready
AUTHORITY                       PASS
EXECUTION                       PASS
TRUTH                           PASS
SEED-STORE-GATE                 READY_FOR_DAY0
DATA-AS-01                      BLOCKED_EXTERNAL
AuthorizedSessionConnector      UNAVAILABLE until authorized wiring
Sandbox                         FROZEN
Growth Writeback                DISABLED
MT-LIFT Data                    LICENSE_BLOCKED
```

种子客户门店测试的工程条件已经具备：登记授权店 → 只读 7 天 → 禁止写回 → 禁止 Mock → 提交官方报表做 Day 0 对账基线。  
**真实 Session 采集仍等美团明确授权店**，在此之前 fetch 必须保持 UNAVAILABLE。

种子店测试入口：`POST /v1/stores/{id}/seed-store/open`（记录授权人）→ `GET /v1/stores/{id}/seed-store`（就绪检查）→ `POST /v1/stores/{id}/data-acquisition/official-report`（Day 0 基线，不进 StoreState）。

下一次打开采集主线的事件，只应该是：**美团明确授权测试店到位 → 真实 Session fetch。**  
店到了也不跳过 Gate，也不把 Mock 或未对账报表晋升为生产事实。

```text
EXTERNAL_EVIDENCE_WAIT + PRE-PROD SECURITY BLOCKED
        │
        ├── SEED-STORE-GATE   READY_FOR_DAY0
        ├── DATA-AS-01        BLOCKED_EXTERNAL
        ├── PLATFORM-SB-01    FROZEN
        ├── Growth Writeback  DISABLED
        ├── MT-LIFT Data      LICENSE_BLOCKED
        │
        └── PRE-PROD-GATE-01  🟢 PASS（8/8，见下文）
              ├─ 1 Global secrets admin gate         PASS  /settings/system PUT admin-only
              ├─ 2 Store access handler-enforced     PASS  Query store_id 路由 enforce_store_access
              ├─ 3 Empty operator scope DENY         PASS  can_access_store fail-closed
              ├─ 4 Production JWT_SECRET mandatory   PASS  生产缺 JWT_SECRET → SystemExit
              ├─ 5 OAuth tokens credential_ref only  PASS  credential_ref + 回归测试
              ├─ 6 Test DB isolated                 PASS  conftest 临时 SQLite + atexit 清理
              ├─ 7 Synthetic ≠ Truth                PASS  seed_demo synthetic 标注 + authorized_session fixture + Truth 边界回归
              └─ 8 Attribution/verification no-swallow PASS  closed_loop + 护栏不再 pass
                    │
                    └──（旁路）PROD-DB-HARDENING-01  ⏸ 不阻塞真店，阻塞正式生产部署
                          ├─ Alembic baseline 显式 DDL
                          ├─ 多 worker migration 锁
                          ├─ PG pool_pre_ping
                          └─ FK ondelete + SQLite PRAGMA
```

没有真实 OAuth 凭据、没有正式授权店、没有生产 Growth Action 时，继续保持冻结完全合理。

**一旦要进入真实店，启动顺序必须是：**

```text
AUTHORITY
所有 store / secret 权限 fail closed
        ↓ PASS

EXECUTION
所有状态改变经过中央 Action Pipeline
        ↓ PASS

TRUTH
所有生产事实经过 Truth Promotion
Mock / Synthetic / Unknown Source 不可见
        ↓ PASS

DATA-AS-01
Day 0 reconciliation
        ↓
Day 1–7 production evidence
```

而不是：拿到店 → 先接起来 → 后面再修这些问题。

任何真实平台凭据、真实授权店数据进入系统之前，必须先清掉旧路径里的生产卫生问题。  
不扩 DATA-AS-01 真实 fetch、不扩 Sandbox、不做自动发券。

## 三面 Gate（真店前收口）

不再继续加零碎 ticket。所有旧洞归入三个唯一入口：

| Gate | 核心问题 | 本轮已收口 |
| --- | --- | --- |
| **AUTHORITY** | 谁可以操作什么店/秘密 | 既有 P0-1..P0-4；所有 store / secret 权限 fail closed |
| **EXECUTION** | 什么东西可以被称为 Executed | `commit_recommendation_executed` 是唯一产生 `executed` 的入口；HTTP 200 / Tool success / 写回受理 ≠ EXECUTED；未 Verify 不得 Commit |
| **TRUTH** | 什么数据可以进入 Business Truth | Truth Promotion 失败只留 Evidence；`NULL / "" / synthetic / mock / invalid reconciliation` 在 StoreState / POIE / ranking / Memory **查询不可见**；真实 Connector 失败不得回退 Mock |

## PRE-PROD-GATE-01

**定义日期：2026-08-18**  
**范围：8 条，不扩范围。** 每条映射到 [mealkey_production_invariants_v1.md](mealkey_production_invariants_v1.md) 的原则 + 代码层状态 + 必须的改动 + 验收方法。

> 优先级 P0-1..P0-4 为安全修复（阻塞真店）；P0-5..P0-7 为 Truth/测试隔离（阻塞真店）；P0-8 为归因可观测（阻塞真店）。  
> `git init` 重要但不是 production gate，可与 P0 并行。

### P0-1　Global secrets → admin only

- **原则**：Invariant #2（Secret 不通过普通 API 返回）的权限侧。
- **状态**：🟢 PASS（已修复）。[`app/api/routes_settings.py`](../app/api/routes_settings.py) `PUT /settings/system` 现校验 `principal.is_admin`；operator → 403；死代码守卫已移除。审计前：只校验 key 在 `EDITABLE_KEYS` 白名单（含 `oauth_meituan_client_secret` / `platform_connector_token` 等），无 admin 约束。
- **必须改动**：handler 加 `require_admin(principal)`；移除死代码守卫。
- **验收**：operator JWT 调 `PUT /settings/system` → 403；admin 调 → 200。

### P0-2　Store access → handler/dependency enforced

- **原则**：多租户隔离基础。不能只依赖 URL 正则中间件。
- **状态**：🟢 PASS（已修复）。新增 `enforce_store_access` / `require_store_access` 依赖，Query 传 `store_id` 的 handler 显式校验 `principal.can_access_store(store_id)`，不再只依赖 `api_auth_guard` 的 path 正则。审计前：门店作用域检查只在中间件按 path 正则 `_STORE_PATH_RE` 做，Query 路由不命中 → 绕过校验（overview / platform-assist / platform-intel / start_platform_oauth）。
- **必须改动**：抽 `require_store_access(store_id)` 依赖，在所有 store-scoped handler 强制 `principal.can_access_store(store_id)`，不只依赖中间件。
- **验收**：operator A 的 JWT 调 `GET /settings/overview?store_id=B` → 403。

### P0-3　Empty operator scope → DENY

- **原则**：Operator 权限必须 fail closed，不得 fail open。
- **状态**：🟢 PASS（已修复）。[`app/core/security.py`](../app/core/security.py) `can_access_store` 对 operator `store_ids=[]` 改为 `return False`（fail-closed）。审计前：空集返回 `True`（语义反转，无授权门店 = 全店权限）。
- **必须改动**：operator 分支空集改 `return False`；admin/legacy 保留"空=全量"语义。补单测覆盖"空 store_ids operator 不得访问任意 store"。
- **验收**：`store_ids=[]` 的 operator JWT 访问任意 `/stores/{any}/...` → 403。

### P0-4　Production JWT_SECRET → mandatory independent secret

- **原则**：Invariant #2 凭证卫生。
- **状态**：🟢 PASS（已修复）。[`app/main.py`](../app/main.py) 生产守卫强制独立 `JWT_SECRET`，缺失 → `SystemExit(1)`；[`app/core/security.py`](../app/core/security.py) 移除 `api_token` 派生回退。审计前：允许 `api_token`/`jwt_secret` 二选一，`jwt_secret()` 缺失时由 `api_token` 确定性派生，api_token 泄露即可伪造 admin JWT。
- **必须改动**：生产守卫强制 `JWT_SECRET` 独立配置；移除 `api_token` 派生回退或仅限 `is_dev`。
- **验收**：`APP_ENV=prod` + 仅 `API_TOKEN` 无 `JWT_SECRET` → `SystemExit(1)`。

### P0-5　OAuth tokens → credential_ref only, never normal API response

- **原则**：Invariant #2。
- **状态**：🟢 PASS（2026-08-18 已核实）。[`credential_store.py`](../app/services/credential_store.py) 全链路只存 credential_ref；`public_platform_link` / `public_oauth_fields` 只返回状态布尔值；`app/schemas/` 下 `access_token/refresh_token/client_secret` 零匹配。唯一边缘情况：[`routes_auth.py:140-157`](../app/api/routes_auth.py) `/bootstrap-tenant` 首次返回租户 `client_secret` 明文（租户凭证 first-time reveal，非平台 OAuth token，不在 invariant 覆盖范围）。
- **必须改动**：无代码改动。补回归测试锁死（platform-links / oauth callback 响应不含原始 token 字段）。
- **验收**：回归测试 PASS。

### P0-6　Test DB → isolated from persistent dev/prod DB

- **原则**：Invariant #1（Synthetic ≠ Truth）的基础设施侧。
- **状态**：🟢 PASS（已修复）。[`tests/conftest.py`](../tests/conftest.py) 在 app 模块 import 前把 `DATABASE_URL` 指向独立临时文件 `mealkey_test_{pid}.db`，`atexit` 清理，永不触碰 `./mealky.db`。审计前：不覆盖 `DATABASE_URL`，`engine` 模块级单例绑死 `./mealky.db`，测试已污染 dev 库。
- **必须改动**：`conftest.py` 设 `TEST_DATABASE_URL=sqlite:///:memory:`（或临时文件）；`SessionLocal`/`engine` 延迟到 `get_db` 调用时读 settings，或 fixture monkeypatch `settings.database_url` 后重建 engine。
- **验收**：删除 `./mealky.db` 后跑全量测试，`./mealky.db` 不被重建；测试间无状态泄漏。

### P0-7　Synthetic/mock → impossible to become production Truth

- **原则**：Invariant #1（Synthetic 永远不是 Truth）。Demo 不伪装真实来源；生产归因测试自行构造满足 Truth Contract 的 fixture。
- **状态**：🟢 PASS（已修复 + Truth 边界回归锁死）。
  - [`app/api/routes_dev.py`](../app/api/routes_dev.py) `seed_demo` 幂等（先查后插）；funnel 行（Shop + Item）显式标 `data_source="synthetic"` —— NULL=历史未知来源，synthetic=明确假数据，两者都不进 `production_funnel_clause`，但 synthetic 审计语义更清楚：demo 永不伪装成 `platform_export`。
  - [`tests/truth_fixtures.py`](../tests/truth_fixtures.py) `seed_reconciled_authorized_session_funnel`：归因/诊断测试用它构造 `data_source="authorized_session"`（经授权会话、已对账）的 observed funnel，数值口径与 `seed_demo` 一致，仅 provenance 不同。
  - [`tests/test_truth_boundary.py`](../tests/test_truth_boundary.py) 4 场景把「No Provenance = No Truth」锁死为回归：None/synthetic 排除（funnel_missing）；authorized_session observed 可见；valid production provenance 归因执行落终态。
  - 10 处依赖 demo funnel 的旧测试（3 attribution + daily_job core_items + 诊断/增长/事件/facts 5 处 + product agent 1 处）改用 authorized_session fixture，不再吃 demo 的 synthetic 数据。
- **验收**：`POST /dev/seed` 连续两次幂等；`production_funnel_clause` 拒绝 None/synthetic，接受 authorized_session；Truth 边界 4 场景全绿。

### P0-8　Attribution / verification failure → never silently swallowed

- **原则**：Invariant #5（Verification Failure 永远不能静默）。
- **状态**：🟢 PASS。3 处漏网已收敛：
  - [`app/services/closed_loop.py`](../app/services/closed_loop.py) `_close_observation` 的 `evaluate_experiment` 外层 except 现在补调 `_mark_failed_verification`，未预期异常 → `result="unknown"` + `FAILED_VERIFICATION` marker + `FAILED_VERIFICATION` AgentEventLog error，loop summary 显式写「自动归因失败」，不再伪装成正常「待确认」。
  - [`app/services/experiment_attribution.py`](../app/services/experiment_attribution.py) 利润护栏检查 `except` 不再 `pass`：`logger.warning` + 追加告警，经统一降级逻辑把 positive → neutral。
  - 同文件 CPC 护栏检查 `except` 不再 `pass`：`logger.warning` + 追加告警。
- **改动**：`closed_loop.py` except 内补调 `_mark_failed_verification`；`experiment_attribution.py` 两处 `pass` 改 `logger.warning` + 追加 `guardrail_warnings`。
- **验收**：[`tests/test_preprod_gate_attribution.py`](../tests/test_preprod_gate_attribution.py) 3 条全绿：
  1. 注入 `evaluate_experiment` 未预期异常 → `result="unknown"` + `FAILED_VERIFICATION` marker + AgentEventLog error。
  2. 利润护栏故障 → positive 降级 neutral + warning。
  3. CPC 护栏故障 → warning（不静默）。
- **全量回归**（2026-08-18 Option B 闭合后）：595 passed / 4 skipped / 0 failed（仅剩 1 处 `test_memory_rerank` collection error，旁路登记为 KNOWN_TEST_DEBT）：
  - ~~1 处 `test_agent_infra` ImportError~~ → ✅ 已收：测试改到真实公开 contract `run_recommendation_pipeline`（PREPARE→VALIDATE→CAPABILITY CHECK→AUTHORIZE→EXECUTE→VERIFY→COMMIT），删除旧 `ActionPipeline`/`PipelineStage`/`PipelineStatus` 符号漂移。
  - ~~4 处 `test_oci_whitelist` 缺外部语料~~ → ✅ 已收：外部 OCI 语料（`data/cases/`，curated ≥33 文件，不在 repo）缺失时 4 条语料依赖测试 explicit SKIP（reason：external OCI corpus unavailable），不伪造语料、不假装通过。
  - ~~1 处 `test_product_agent` failed~~ → ✅ 已收：补 `seed_reconciled_authorized_session_funnel`（与已修 9 处同根：`seed_demo` synthetic 被过滤 → 补 `authorized_session` observed funnel），`diagnosis_stage` 恢复 `ctr`。Option B（Synthetic 永不是 Truth）真正闭合：所有依赖 observed funnel 的测试均走 authorized_session fixture。
  - 之前的 9 处 + 本次 1 处 funnel/provenance 失败已由 P0-7 全部清零。
  - **KNOWN_TEST_DEBT — non-blocking for SEED-STORE Day 0**：`test_memory_rerank` 1 collection error（`StrategyMemorySnapshot` 未定义，缺 import），与 Execution & Truth Convergence / Option B / 种子店 Gate 均无关；不为本轮扩，留档待下一轮独立处理。

### PASS 条件

```text
P0-1..P0-8 全部 PASS
        ↓
PRE-PROD-GATE-01 PASS
        ↓
美团 × 1 授权测试店（READ_ONLY / 7 days / MINIMUM PII / 禁止写回）
        ↓
DATA-AS-01 Day 0
```

### 旁路：PROD-DB-HARDENING-01（不阻塞本地只读开发，阻塞正式生产部署）

不进 PRE-PROD-GATE-01，单独跟踪：

- Alembic baseline 重写为显式 DDL（当前 [`migrations/versions/20260813_0001_baseline.py:23`](../migrations/versions/20260813_0001_baseline.py) 用 `Base.metadata.create_all`）
- 移除 `RUN_ALEMBIC_ON_STARTUP` app 内迁移分支（多 worker 无锁），统一走独立 migrate container
- engine 加 `pool_pre_ping` / `pool_recycle`（[`app/db/session.py:9-12`](../app/db/session.py)）
- SQLite `PRAGMA foreign_keys=ON` + 关键 FK 显式 `ondelete`
- `apply_schema_backfill` 补索引 / PG 分支补 DEFAULT
- 统一 `RUN_MIGRATIONS_ON_START` vs `RUN_ALEMBIC_ON_STARTUP` env var

## 路线图

```text
P0  DATA-AS-01
    Contract / Docs / Code Contract   DONE
    Real Connector                    BLOCKED_EXTERNAL
            ↓
    Waiting for authorized Meituan store
            ↓
    Day 0 Reconcile + MetricDefinitionVersion
            ↓
    Day 1–7 Evidence
            ↓
    StoreState → POIE → ODO → Candidate Action（不执行写回）

旁路
    DSH          SHADOW ONLY，不抢工程资源
    TE-01        Architecture Research 可继续（不碰原始数据）
    MT-LIFT Data BLOCKED BY LICENSE
    PLATFORM-SB-01  FROZEN（integration test infrastructure）
    Growth Primitive  Registry only，not_implemented
```

## 恢复触发（仅此两条）

| 外部条件 | 恢复动作 |
| --- | --- |
| **授权店到位**（美团 × 1 家，只读、7 天、最小 PII、禁止写回） | 先确认 PRE-PROD HYGIENE P0 已通过，再启动 `DATA-AS-01 Day 0 → Day 7`。只验证四个事实、口径、连续性、对账，以及 `POIE → ODO → Candidate Action` |
| **MT-LIFT 许可到位** | 单独开启 Data Use Review。先确认 commercial R&D、训练产物商用、衍生成果等范围，再决定是否下载/训练。**不与生产门禁绑定** |

授权店启动条件必须同时满足：

```text
platform = MEITUAN
store = 明确指定的一家真实门店
authorization = 店主/经营主体明确授权
mode = READ_ONLY
duration = 7 days
pii_scope = MINIMUM
writeback = DISABLED
PRE-PROD HYGIENE = PASS
```

禁止：预适配、模拟登录、猜测页面结构。

选店建议：正常营业、相对稳定、日均约 30–100 单、能拿到官方报表、非最核心旗舰店。

## 真店第一版只允许四个事实

```text
order_count
gross_gmv
merchant_revenue
refund_amount
```

不可靠 → `UNKNOWN`。`merchant_revenue` 口径无法解释一致 → `PASS_WITH_LIMITS`，禁止为完整率扩大抓取。

Day 0：核心金额带 `MetricDefinitionVersion`。  
Truth = `value + source + confidence + metric_definition_version`。

同一个事实可以有多个 Evidence，但只有一个 Truth Resolution。  
mock / oauth / session / import 先进入 Business Facts，再经 Truth Resolution 写入 `ShopFunnelDaily` / `StoreState`。  
现阶段不重构整个数据层；最低要求：同日 × 同店 × 同 metric 的 source lineage 可辨认，并且 mock 不可能覆盖真实授权数据。

## V1 证据权重 ≠ 生产排序权

证据强度表达（可校准，非永久常数）：

```text
Observed 0.25  <  Attributed 0.55  <  Incremental 1.0
```

生产 Growth Ranking 权限：

```text
Observed     → explain_only
Attributed   → may_rank
Incremental  → strong_rank
```

ObservedResult 可以被 AI 看见、解释、生成假设，但不能因为「上次做完订单涨了」就提升 Growth Action 的生产排序。

## Production Invariants V1

见 `docs/mealkey_production_invariants_v1.md`。九条不可违反：

> Synthetic 永远不是 Truth。  
> Secret 永远不通过普通业务 API 返回。  
> NOT_IMPLEMENTED 永远不能伪装成 Executed。  
> Tool/Action Success 永远不能直接成为 Strategy Success。  
> Verification Failure 永远不能静默。  
> Observed correlation 永远不能冒充 incremental effect。  
> No direct Execute — 所有执行必须经过中央 Action Pipeline。  
> Production never falls back to Mock。  
> No Provenance = No Truth。

下一阶段工程主题：**Execution & Truth Convergence**。

```text
一个执行入口。
一个 Truth 晋升入口。
一个权限判断入口。
```

## 明确停止

- 不再扩 Sandbox / Growth 执行 / DATA-AS-01 连接器实现
- 不下载、训练、商用 MT-LIFT
- 不继续内部功能扩建
- 真实凭据或授权店进入前，不跳过 PRE-PROD HYGIENE
