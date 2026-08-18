# SEED-STORE-01

**冻结日期：2026-08-18**  
**产品状态：Seed-store pilot ready，not production ready。**

> MealKey 已具备第一家真实种子店的受控只读试点条件，但尚未具备正式生产门店连接条件。

工程不再是主阻塞项。现在第一次允许**真实商家 Evidence 进入受控流程**。  
不是继续开发，也不是接通用 Connector。

```text
SEED-STORE-01

Platform        = MEITUAN
Stores          = 1
Mode            = READ_ONLY
Duration        = 7 DAYS
PII             = MINIMUM
Platform Write  = DISABLED
Mock            = FORBIDDEN
Official Report = EVIDENCE_ONLY
Real Fetch      = UNAVAILABLE until authorized wiring
```

`AuthorizedSessionConnector.fetch() = UNAVAILABLE` 在授权接线完成前完全正确。  
店已登记，也不允许「顺便把 Session 接起来看看」。Session 接线是 Day 0 之后的独立动作，且必须只针对**这一家已明确授权的 store**，不得重开通用 Connector 开发。

## Day 0 只证明四件事

Day 0 **不是**证明 MealKey 能自动采集。

```text
1. 这家店是谁
2. 谁授权 MealKey 做什么
3. 官方报表里的四个经营指标到底是什么口径
4. MealKey 能不能建立未来 Collector 的对账基准
```

四个经营指标：

```text
order_count
gross_gmv
merchant_revenue
refund_amount
```

字段没有、口径说不清 → `UNKNOWN`。不要补。  
`merchant_revenue` 第一天对不上「预计收入 / 实收 / 结算金额」是正常发现，不是 POC 失败。

## 正确操作顺序

```text
明确授权商家
      ↓
seed-store/open
      ↓
确认 READ_ONLY / NO MOCK / NO WRITEBACK
      ↓
上传官方报表
      ↓
MetricDefinitionVersion
      ↓
Day 0 reconciliation baseline
```

入口：

```text
POST /v1/stores/{id}/seed-store/open
GET  /v1/stores/{id}/seed-store
POST /v1/stores/{id}/data-acquisition/official-report
```

官方报表只进 Evidence，不进生产 StoreState。

## Day 0 必须留下的审计证据

```text
store_id
authorization
platform = meituan
report_date
raw_report_ref / hash

order_count
gross_gmv
merchant_revenue
refund_amount

MetricDefinitionVersion
reconciliation_status
```

## Day 0 结论（先不要宣称 DATA-AS-01 PASS）

```text
DAY0_READY
DAY0_PASS
DAY0_PASS_WITH_LIMITS
DAY0_BLOCKED
```

| 结论 | 含义 |
| --- | --- |
| `DAY0_READY` | 种子店已登记，尚未留下官方报表基线 |
| `DAY0_PASS` | 店、授权、四指标与口径版本都可审计 |
| `DAY0_PASS_WITH_LIMITS` | 基线已立，部分指标 `UNKNOWN`（常见是 `merchant_revenue`） |
| `DAY0_BLOCKED` | 缺店、缺授权、错平台、或报表无法作为对账基准 |

Day 0 验证「我们知道真实是什么」。  
Day 1–7 才验证「我们能不能持续知道真实发生了什么」。

```text
Day 1–7
真实只读 Evidence
      ↓
Reconciliation
      ↓
Production Truth
      ↓
StoreState
      ↓
POIE
      ↓
ODO
      ↓
Candidate Action
```

店没有到位：`fetch = UNAVAILABLE`。  
店一到位：**立即进入 SEED-STORE-01 Day 0，不再继续补架构。**
