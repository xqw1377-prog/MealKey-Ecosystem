# MealKey Data Acquisition Strategy V1

**状态：FROZEN（2026-08-17）**  
合同来源：`DATA-AS-01 CONTRACT FROZEN — V1`。后续问题优先用实现、监控和 POC 记录解决；除非安全 / 合规 / Business Truth 语义错误，否则不再改 Contract。

本文件是系统正式战略，不是实现手册。工程细节见：

- [`docs/data_as_01_merchant_authorized_collector_poc.md`](data_as_01_merchant_authorized_collector_poc.md)
- [`app/schemas/data_acquisition.py`](../app/schemas/data_acquisition.py)
- [`app/services/authorized_session_connector.py`](../app/services/authorized_session_connector.py)

## 1. 目标

MealKey 要成为 **Connected AI 外卖店长**：没有老板每天上传 Excel，也能连续获得自己店的经营事实，并据此发现真实问题。

当前最大短板不是推理，而是 **Business Truth 的自动获取**。资源冲突时：

```text
Business Truth Connectivity  >  Agent Runtime Optimization
```

## 2. 数据获取梯子

优先级高 → 低，**不可因“更好抓”而自动上调**：

```text
OFFICIAL_API
→ SERVICE_PROVIDER_API
→ AUTHORIZED_SESSION          ← 产品名：商家授权数据连接器
→ FILE_IMPORT
→ SCREENSHOT
→ MERCHANT_CONFIRMATION
```

`AUTHORIZED_SESSION` 不是爬虫，也不是绕过平台权限的抓取。它只在官方 / 服务商 API 暂时不可获得时，由商家主动授权 MealKey 读取**自己门店**的经营事实。Ownership 挂在现有 `PlatformConnectorContract` 下，不另起 crawler framework。

## 3. 六条纪律

1. Connector 只获得 Evidence，不决定 Truth。
2. `acquisition_mode` 是 provenance 的正式组成部分。
3. Business Truth 与 Market Intelligence 永久分离。
4. 不保存平台账号密码；凭据只以 `session_handle_ref` 指向安全存储。
5. PII 默认拒绝；字段用 allowlist，禁止整页 JSON 直灌后再删。
6. `AUTHORIZED_SESSION` 永不自动升为第一优先级。

## 4. 从 Evidence 到 Truth

```text
Platform Connector
↓
Raw Evidence
↓
FactEnvelope
↓
Normalize
↓
Reconciliation
↓
Business Fact
↓
StoreState
```

任意来源（OAuth API / 授权会话 / CSV）最终产出同一种 `FactEnvelope`。  
**第一次跑出来的金额，即使“看起来差不多”，也不得直接写成高置信 Business Truth。**

口径必须分开：

```text
GMV ≠ 客付
客付 ≠ 商家实收
商家实收 ≠ 贡献利润
```

拿不到的字段保持 `UNKNOWN`。禁止用模型把 UNKNOWN 补成数字。

## 5. FactEnvelope 与 provenance

每条进入系统的经营证据必须带：

| 字段 | 作用 |
| --- | --- |
| `platform` / `store_id` | 门店映射 |
| `fact_type` / `fact_key` / `occurred_at` | 事实身份与时间 |
| `value` / `unit` | 可对账的值 |
| `acquisition_mode` | 梯子上的哪一层 |
| `source_connector` / `source_version` | 哪一个连接器版本 |
| `collected_at` / `authorization_id` | 采集与授权追溯 |
| `confidence` / `reconciliation_status` | 还不是 Truth 的标记 |
| `raw_evidence_ref` / `raw_evidence_hash` | 原始证据指针，不含 PII 正文 |

Decision Core 必须能回答：这个数字是官方财务 API、服务商 API、授权会话、Excel、截图，还是老板口头确认。

## 6. 授权边界

允许持久化的只有授权元数据：

```text
authorization_id
store_id
platform
session_handle_ref
scope
created_at
expires_at
revoked_at
last_used_at
```

禁止：平台账号、密码、明文 Cookie / token 进业务表或日志。  
商家自己完成网页登录；MealKey 只持有最小、可撤销、单店隔离、有 Audit Log 的会话句柄。

## 7. PII allowlist

订单事实默认只允许：

```text
order_id_hash
ordered_at
sku_id
sku_name
quantity
gross_amount
merchant_discount
platform_discount
merchant_revenue
refund_amount
fulfillment_status
fulfillment_duration
```

默认拒绝：真实姓名、完整手机号、完整地址。  
需要个人信息时单独走授权与合规，不得因为“后台能看见”就全抓回来。

## 8. Connector health

未接线、页面改版、认证失效、字段缺失时，必须显式降级，**禁止尽最大努力猜数据**：

```text
HEALTHY
DEGRADED
AUTH_REQUIRED
RATE_LIMITED
SCHEMA_CHANGED
UNAVAILABLE
```

规则：

- 未接真实平台 / 无授权 → `UNAVAILABLE`，`envelopes=[]`
- Session 失效 → `AUTH_REQUIRED`，不得静默空跑当成功
- 页面或字段结构变化 → `SCHEMA_CHANGED`，**停采**，错字段不得进入 Business Truth
- 不具备的 capability → `UNAVAILABLE`，绝不伪造

## 9. Reconciliation 与置信度晋升

Day 0 先做基线，不进高置信 StoreState。至少核对：

```text
门店映射 / 日期边界 / 订单状态定义 / 退款口径
金额口径 / 重复订单 / 跨午夜订单 / 已取消订单
```

日度对账指标：`orders` / `gmv` / `merchant_revenue` / `refund` / `sku_sales`。

| reconciliation_status | 可否进入 StoreState | 置信度 |
| --- | --- | --- |
| `UNCHECKED` | 否（高置信） | 保持 Evidence |
| `MATCHED` | 可以 | 按 `acquisition_mode` 给档，授权会话默认中档 |
| `EXPLAINABLE_DIFF` | 可以（中/低） | 差异必须写 `reason` |
| `MISMATCH` | 否 | 不晋升 |
| `BLOCKED` | 否 | health 不健康或 schema 变化 |

授权会话即使对账通过，也不因为“金额接近”自动升到官方 API 同级置信。缺 `merchant_revenue` 时该字段保持 UNKNOWN，系统承认自己还不能做完整利润判断。

## 10. 最小经营事实（1×1 第一版）

目标不是复制商家后台，而是：**最少多少事实，就足以让 POIE 开始主动工作。**

真店第一版 **只允许** 四个事实：

```text
order_count
gross_gmv
merchant_revenue
refund_amount
```

不可靠保持 `UNKNOWN`。`merchant_revenue` 对不上官方口径 → `PASS_WITH_LIMITS`，禁止扩大抓取。

Day 0 每个核心金额事实必须带 `MetricDefinitionVersion`（`time_basis` / 含排除状态 / 退款与费用口径）。三个月后平台改口径时，系统必须知道含义变了，而不能只看到“数字仍对上 98%”。

## 11. 7 天验收与结果分类

成功标准不是抓到 JSON，而是：

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

**可以不执行 Action。** 本阶段证明的是：没有每天上传 Excel，MealKey 也能发现真实经营问题并提出下一步。

内部评审只允许四种结果（不改 Contract，只分类 POC 结果）：

| 结果 | 意义 |
| --- | --- |
| `PASS` | 可继续第二家店 |
| `PASS_WITH_LIMITS` | 可用，部分字段保持 UNKNOWN |
| `REWORK` | 数据有价值，连接可靠性不够 |
| `STOP` | 安全 / 合规 / 稳定性 / 维护成本不成立 |

允许 `PASS_WITH_LIMITS`：例如订单、GMV、退款可靠，商家实收暂时拿不到。

每日必须留下 `CollectorRun`（见 schema），第 7 天产出 `Connector Reliability Report`，而不是口头“这周挺稳定”。

## 12. 明确不做

```text
Connector Marketplace
Universal Browser Agent
Multi-platform Scheduler V2
自动验证码体系
Data Lake
新爬虫框架
自建外卖平台 / 消费者红包站 / 三级分销
把授权会话与竞品采集混用
```

下一阶段唯一问题：

> `AuthorizedSessionConnector` 能不能在一家真实授权店连续稳定工作 7 天，并最终让 POIE 发现真实经营事件、提出 Candidate Action？

这个答案出来以后，再决定第二家店、第二个平台，以及是否产品化。
