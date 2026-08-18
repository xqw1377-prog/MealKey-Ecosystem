# MealKey Production Invariants V1

**冻结日期：2026-08-18（V1 九条）**  
**状态：不可违反。新增 Agent / Action / Dashboard 不得绕过。**  
**阶段主题：Execution & Truth Convergence**

当前最大风险已经从「功能还没做」变成「两条都能跑的路径，哪条才是真实生产语义」。  
下面九条是生产语义的硬约束，不是风格建议。

```text
1. Synthetic 永远不是 Truth。
2. Secret 永远不通过普通业务 API 返回。
3. NOT_IMPLEMENTED 永远不能伪装成 Executed。
4. Tool/Action Success 永远不能直接成为 Strategy Success。
5. Verification Failure 永远不能静默。
6. Observed correlation 永远不能冒充 incremental effect。
7. No direct Execute — 所有执行必须经过中央 Action Pipeline。
8. Production never falls back to Mock。
9. No Provenance = No Truth。
```

一句话阶段目标：

> **现在不是补能力，而是建立 Single Choke Point：所有执行只能从一个门进去，所有 Truth 只能从一个门晋升。**

真店前三个核心面：

| Gate | 核心问题 | 目标 |
| --- | --- | --- |
| **AUTHORITY** | 谁可以操作什么店/秘密 | 权限 fail closed |
| **EXECUTION** | 什么东西可以被称为 Executed | 单一 Action Pipeline |
| **TRUTH** | 什么数据可以进入 Business Truth | 单一 Truth Promotion |

## 1. Synthetic 永远不是 Truth

`REAL` 门店在无数据时只能是 `NO_SIGNAL`。  
禁止：`no data → synthesize order decline → ORDER_DROP`。

Mock / Fixture 可以服务测试，但必须带：

```text
source = synthetic
environment = sandbox/test
```

并且永远不能晋升生产 Business Truth，也不能覆盖已对账的授权数据。

## 2. Secret 永远不通过普通业务 API 返回

`PlatformConnection.meta_json` 与设置页列表 API 不得包含 `access_token` / `refresh_token`。  
普通设置 API 只返回：

```text
connected / expires_at / scopes / credential_status
```

真实凭据若曾以明文落库：迁移后建议 rotate / revoke，而不是只搬字段。  
本约束属于 `SEC-PLATFORM-01`，不并入 DATA-AS-01。

## 3. NOT_IMPLEMENTED 永远不能伪装成 Executed

能力真相只在 Action Registry：

```text
IMPLEMENTED | READ_ONLY | MANUAL_ONLY | NOT_IMPLEMENTED | DISABLED
```

所有调用方统一经过：

```text
PREPARE → VALIDATE → CAPABILITY CHECK → AUTHORIZE → EXECUTE
```

`execution_method = not_implemented` 必须产生 `BLOCKED_NOT_IMPLEMENTED`：

- 不得进入 EXECUTED
- 不得创建假的 Result
- 不得进入 Strategy Memory

这是中央 invariant，不是 Sandbox 特判。

## 4. Tool/Action Success 永远不能直接成为 Strategy Success

工具调用成功、人工点了「已执行」、平台写回成功，都只证明 **动作发生过**。  
策略是否成功必须经过 Result / Verification / Memory，且允许结果为 `UNKNOWN`。

## 5. Verification Failure 永远不能静默

`experiment_attribution → verification writeback` 失败时：

```text
verification failure
→ explicit FAILED_VERIFICATION
→ AgentEvent / error trace
→ Result = UNKNOWN
→ 不写入 Strategy Memory
```

禁止 broad exception 把归因/写回错误吃掉后继续「看起来没事」。

## 6. Observed correlation 永远不能冒充 incremental effect

证据强度（存储/解释）与生产排序权必须分开：

```text
Evidence storage:
Observed     0.25
Attributed   0.55
Incremental  1.00

Production Growth Ranking:
Observed     → explain_only
Attributed   → may_rank
Incremental  → strong_rank
```

ObservedResult 可以被 AI 看见、解释、生成假设。  
不能因为「上次做完订单涨了」就提升发券 / 唤醒 / Referral / 价格 / 补贴 的生产排序。

## 7. No direct Execute — 所有执行必须经过中央 Action Pipeline

Execution has one choke point。系统里只有一个地方有权把动作变成执行态：

```text
Recommendation
      ↓
ActionSpec
      ↓
PREPARE → VALIDATE → CAPABILITY CHECK → AUTHORIZE → EXECUTE → VERIFY → COMMIT
```

`POST /recommendations/{id}/execute` 只是 Action Pipeline 的薄入口，禁止：

```text
POST /recommendations/{id}/execute
→ recommendation.status = executed
```

`execution_method = not_implemented` → `BLOCKED_NOT_IMPLEMENTED`  
缺审批 → `NEED_APPROVAL`  
平台不可用 → `PLATFORM_UNAVAILABLE`

没有任何 handler 可以自己写 `executed=true`。唯一写入点是 `commit_recommendation_executed`。

## 8. Production never falls back to Mock

```text
DEV / TEST:  mock = explicitly allowed
PROD:        mock = forbidden
```

真实 Connector 可用 → REAL。  
否则 → `UNAVAILABLE` / `CONFIGURATION_ERROR`。  
禁止：`真实 Connector 不可用 → MOCK`。

生产启动若发现 `connector_mode == mock`：禁用该 Connector，并记 `CONFIGURATION_ERROR`。  
Sandbox 可以继续存在，但必须锁在 `Synthetic + Sandbox/Test`，不得与 production evidence 共用晋升路径。

## 9. No Provenance = No Truth

禁止给空 `data_source` 补默认值（不要猜 `platform` / `platform_export`）。

```text
data_source is NULL / ""
        ↓
LEGACY_UNKNOWN_SOURCE
        ↓
confidence = 0
        ↓
excluded_from_production_truth = true
```

历史无来源数据可以展示、调试、人工核查。  
不能驱动 POIE、影响生产排序、进入 Strategy Memory。  
等真正重新对账以后，再升格。

## 与阶段状态的关系

这些 invariant 属于 `PRE-PROD HYGIENE GATE` / **Execution & Truth Convergence**。  
真店启动顺序：

```text
AUTHORITY Gate PASS
      ↓
EXECUTION Gate PASS
      ↓
TRUTH Gate PASS
      ↓
DATA-AS-01 Day 0
```

在真实授权 Session 第一条数据进来之前，Mock、空 source、legacy 双轨数据不得被 StoreState 误选成 Truth。  
不扩 DATA-AS-01 真实 fetch、不扩 Sandbox、不做自动发券。
