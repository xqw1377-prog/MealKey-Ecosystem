# DATA-AS-01 Merchant Authorized Data Collector POC

## 状态

> **DATA-AS-01 CONTRACT FROZEN — V1（2026-08-17）**
>
> 后续问题优先通过实现、监控和 POC 记录解决；除非出现安全 / 合规 / Business Truth 语义错误，否则不再改 Contract。

战略文档已升级：

- [`docs/mealkey_commercial_os_v1.md`](mealkey_commercial_os_v1.md) — 梯子与原则
- [`docs/data_acquisition_strategy_v1.md`](data_acquisition_strategy_v1.md) — 正式 Data Acquisition Strategy

当前执行：

```text
Contract：FROZEN
Docs：DONE
Ingest / Reconciliation / Discover：LANDED
Real Connector：BLOCKED_EXTERNAL（等美团授权店）
fetch：保持 UNAVAILABLE — 禁止预适配 / 模拟登录 / 猜页面
工程：停止新增功能
```

真店启动条件与四事实范围见 [`docs/phase_external_evidence_wait.md`](phase_external_evidence_wait.md)。

不集成 `waimai-crawler` 代码。吸收其 Platform Adapter / 多门店定时同步思想，挂在现有 `PlatformConnectorContract` 下。

## 正式冻结（与本 POC 绑定）

### 数据获取梯子

```text
OFFICIAL_API
→ SERVICE_PROVIDER_API
→ AUTHORIZED_SESSION          ← 商家授权数据连接器（受控 fallback）
→ FILE_IMPORT
→ SCREENSHOT
→ MERCHANT_CONFIRMATION
```

`AUTHORIZED_SESSION` **不是爬虫能力**，更不是绕平台权限的抓取方案。  
仅当官方 / 服务商 API 暂时不可获得时，由商家主动授权 MealKey 获取**自己门店经营事实**。

### 工程优先级（资源冲突时）

```text
Business Truth Connectivity  >  Agent Runtime Optimization
```

dsh / DeepSeek Harness 可继续 Shadow；冲突时真实 Data Connector 优先。

### 六条架构纪律

1. **Connector 只获 Evidence，不决定 Truth**  
   `Connector → Raw Evidence → FactEnvelope → Normalize → Reconciliation → Business Fact → StoreState`
2. **`acquisition_mode` 是 provenance 正式字段**（见下方 schema）
3. **Business Truth 与 Market Intelligence 永久分离**  
   `AUTHORIZED_SESSION` = 自己店；Competition Connector = 外部观察；禁止共用“crawler”模型混事实
4. **不保存平台账号密码**（POC architecture gate）  
   只允许 `authorization_id / store_id / platform / session_handle_ref / scope / created_at / expires_at / revoked_at / last_used_at`；凭据走安全存储，禁止明文进业务表或日志
5. **PII 默认拒绝；schema 用 allowlist**，禁止“整页 JSON 抓回再删”
6. **`AUTHORIZED_SESSION` 永不自动升为第一优先级**  
   即使比官方 API 更易用，仍保持：官方 API > 服务商 API > 授权 Session

---

## POC 只回答一个问题

> MealKey 能否在**不保存账号密码、不采集非必要 PII**的前提下，连续 **7 天**从**一家明确授权测试店**获得足够驱动 POIE 的经营事实？

### 范围（锁死）

```text
1 Platform × 1 Authorized Store × Read Only × 7 Days
```

### 明确不做

| 禁止项 |
| --- |
| 多平台 / 多商户规模化 |
| 自动写回 / 改菜单 / 评价回复 |
| 竞品采集 |
| 验证码破解 |
| 自动化绕过登录安全机制 |
| `MeituanCrawler` 类族或独立 crawler framework |

产品名固定：**商家授权数据连接器**。

---

## 最小接口（仓库 contract）

### Schema

[`app/schemas/data_acquisition.py`](../app/schemas/data_acquisition.py)

含：

- `AcquisitionMode` + `ACQUISITION_LADDER`
- `ConnectorCapability` / `CapabilityDeclaration`
- `ConnectorHealthStatus`：`HEALTHY | DEGRADED | AUTH_REQUIRED | RATE_LIMITED | SCHEMA_CHANGED | UNAVAILABLE`
- `AuthorizationRecord`（无明文凭据）
- `ORDER_FACT_ALLOWLIST`
- `FactEnvelope`
- `ReconciliationRow`
- `FetchRequest` / `FetchResult`

### Connector Protocol

[`app/services/authorized_session_connector.py`](../app/services/authorized_session_connector.py)

```text
PlatformConnector
  capabilities(...)
  health_check(...)
  fetch(...)

AuthorizedSessionConnector(PlatformConnector)   # acquisition_mode = AUTHORIZED_SESSION
```

能力示例：`ORDERS | PRODUCT_SALES | REFUNDS | FULFILLMENT | FINANCE`  
平台真实不具备 → `UNAVAILABLE`，**绝不伪造**。

当前骨架在未接线前：`health=UNAVAILABLE`，`envelopes=[]`。

### 核心输出

**不是**直接写 StoreState，而是 **`FactEnvelope`**：

```text
platform / store_id
fact_type / fact_key / occurred_at
value / unit
acquisition_mode / source_connector / source_version
collected_at / authorization_id
confidence / reconciliation_status
raw_evidence_ref / raw_evidence_hash
payload   # allowlist only
```

OAuth API、Authorized Session、CSV **三种来源最终产出同一种业务事实信封**，再经现有 Business Facts 层进入 StoreState。

### Order Fact allowlist（默认）

```text
order_id_hash, ordered_at, sku_id, sku_name, quantity,
gross_amount, merchant_discount, platform_discount, merchant_revenue,
refund_amount, fulfillment_status, fulfillment_duration
```

默认拒绝：真实姓名、完整手机号、完整地址。

---

## Reconciliation（进 POC，不以后补）

每日对比 Collector vs 商家后台正式报表：

| 指标 |
| --- |
| Orders |
| GMV |
| Merchant Revenue |
| Refund |
| SKU Sales |

每行至少记录：

```text
collector_value / official_value / absolute_diff / relative_diff / reason
```

`SCHEMA_CHANGED`：数据必须停，禁止错字段继续进入 Business Truth。  
Session 失效：显式 `AUTH_REQUIRED`，不得静默空跑当成功。

---

## Gate（验收门槛）

| 指标 | Gate |
| --- | ---: |
| 未授权采集 | **0** |
| 明文账号/密码存储 | **0** |
| 非必要 PII | **0** |
| Store mapping | **100%** |
| Provenance coverage（含 acquisition_mode） | **100%** |
| Duplicate critical facts | ≈ **0** |
| 连续 7 天同步 | 必须完成 |
| 与官方报表订单数一致性 | **≥99%** |
| 核心金额 reconciliation | **≥99% 或差异可解释** |
| Session 失效 | 必须进入 `AUTH_REQUIRED` |
| UNKNOWN 被模型补全 | **0** |

---

## 真正的成功标准（第 7 天）

不以「抓到 7 天 JSON」为成功。必须跑通：

```text
AUTHORIZED_SESSION
→ Raw Evidence
→ FactEnvelope
→ Reconciliation
→ Business Fact
→ StoreState
→ POIE Trigger
→ ODO
→ Candidate Action
```

**可以不执行 Action。** 目的是证明：没有老板每天上传 Excel，MealKey 也能发现真实经营问题，并提出基于连续数据的下一步。

示例：连续订单事实进入 StoreState 后，MealKey **自动发现午餐订单连续异常**并进入 POIE / ODO / Candidate Action。

---

## 结果分类（不改 Contract）

第 7 天内部评审只允许：

| 结果 | 意义 |
| --- | --- |
| `PASS` | 可继续第二家店 |
| `PASS_WITH_LIMITS` | 可用，部分字段保持 UNKNOWN |
| `REWORK` | 数据有价值，连接可靠性不够 |
| `STOP` | 安全 / 合规 / 稳定性 / 维护成本不成立 |

允许 `PASS_WITH_LIMITS`：例如订单、GMV、退款可靠，`merchant_revenue = UNKNOWN`。不要为完整而冒险抓更多页面。

每日自动形成一条 `CollectorRun`，第 7 天汇总为 `Connector Reliability Report`。

Day 0 先做 reconciliation 基线（门店映射、日期边界、订单状态、退款/金额口径、重复/跨午夜/已取消订单），**不进高置信 StoreState**。

---

## 执行顺序

1. 本 POC 合同定型 — **FROZEN**
2. 更新 `docs/mealkey_commercial_os_v1.md` + 新增 `docs/data_acquisition_strategy_v1.md` — **DONE**
3. **SEED-STORE-01 Day 0**：明确授权商家 + 官方报表基线。不接通用 Connector。`fetch` 保持 UNAVAILABLE，直到针对**这一家已授权店**单独接线。
4. Day 1–7 真实只读 Evidence → Reconciliation → Production Truth → StoreState → POIE → ODO → Candidate Action（不执行写回）

## 下一步（1×1 实现）

- 选定测试平台与明确授权测试店
- 安全凭据存储 + `session_handle_ref` 接线
- Day 0 官方报表基线对账
- 日度 `CollectorRun` + `ReconciliationRow`
- 将 **已对账** Fact 映射进现有 `business_facts` / StoreState
- 构造可触发 POIE 的 Golden Path（午餐订单异常 → Candidate Action，不执行写回）
