# DeerFlow Integration POC V1

## 目标

验证 DeerFlow 2.0 是否适合作为 MealKey 的 Agent Harness，而不是替代 MealKey 的经营大脑。

POC 只回答一个问题：

> 在不改动 MealKey 业务真相层的前提下，DeerFlow 能不能把一条真实经营路径跑通？

本阶段只验证：

```text
BusinessEvent
→ Lead Agent
→ Domain Skills
→ Candidate ODO
→ 回到 MealKey 做 POIE / Permission / Projection
```

不验证：

- 全量平台接入
- 真正的多租户调度
- 全量 Sub-agent 自动化
- 浏览器操作闭环

## 分层边界

### MealKey 负责

- `StoreState / MerchantContext / Goal / WorkThread`
- `Signal / BusinessEvent`
- `ODO / POIE / Permission / OperatingBudget`
- `Action / Experiment / Result / Strategy Memory`
- 左 / 中 / 右三栏 Projection

### DeerFlow 负责

- `Lead Agent`
- `Skills`
- `Sub-agents`
- `Sandbox / Files`
- `MCP / Tools`
- `Scheduler`
- `Authorization / Guardrails`
- `Tracing`
- `Long-term Memory`

## 最小桥接接口

### 1. MealKey -> DeerFlow

统一桥接输入：

- `store_state`
- `business_event`
- `merchant_context`
- `goal_text`
- `trigger_reason`
- `runtime_state`
- `analysis_node`
- `preferred_skills`
- `system_mode`

仓库 contract：

- [`app/schemas/deerflow_bridge.py`](file:///C:/Users/xqw13/MealKey%20Ecosystem/mealky-ai-backend/app/schemas/deerflow_bridge.py)

### 2. DeerFlow -> MealKey

统一桥接输出：

- `selected_skills`
- `skill_executions`
- `candidate_odos`
- `trace`

### 3. POC 预览接口

为后端联调提供一个直接入口：

`POST /v1/stores/{store_id}/runtime-bridge/preview`

输入：

- `store_state`
- `business_event`
- `merchant_context`
- `goal_text`
- `trigger_reason`
- `runtime_state`
- `analysis_node`

输出：

- `deerflow`
- `queue`
- `feed`

MealKey 后续继续执行：

```text
Candidate ODO
→ POIE Arbitration
→ Permission / Ask Engine
→ Action / Experiment / Result
```

## Skill 映射

V1 只接四个 Domain Skills：

| DeerFlow Skill | MealKey Domain | 作用 |
| --- | --- | --- |
| `product` | 商品经营 | 诊断 CTR / CVR / 菜单结构 / 主图问题 |
| `traffic` | 流量经营 | 判断何时可以放量，何时必须禁止投流 |
| `profit` | 利润经营 | 作为 Gatekeeper，拦截破坏利润底线的动作 |
| `competition` | 竞争经营 | 识别谁在抢生意、发生了什么变化 |

当前最小执行器：

- [`app/services/deerflow_bridge.py`](file:///C:/Users/xqw13/MealKey%20Ecosystem/mealky-ai-backend/app/services/deerflow_bridge.py)

## Golden Path 01

### 场景

`黑椒牛肉饭销量下降`

### 期望链路

```text
StoreState + BusinessEvent(HERO_SKU_CTR_DROP)
→ lead_agent 接单
→ 选择 Skills: product + competition + profit
→ Product 诊断 CTR 下降
→ Competition 验证竞品是否换图/改套餐
→ Profit 确认当前无需降价
→ 生成 Candidate ODO
→ 回到 MealKey 做 POIE
→ 如需要老板确认真实份量，生成 Ask
→ 上传图片后继续
→ Action / Experiment / Result
```

### 本次代码 POC 覆盖到哪

已覆盖：

- `BusinessEvent -> Skill selection`
- `Skill execution -> Domain findings / candidate actions`
- `Domain result -> Candidate ODO`

未覆盖：

- 真正调用 DeerFlow runtime
- 文件上传后继续 run
- 真正的 tool authorization middleware
- 真正的 tracing sink 对接

## 验收标准

POC 成功，不以“Agent 会说话”为标准，而以以下标准判断：

1. 给定一个真实 `BusinessEvent`，系统能够自动选择合理 Skills
2. 至少能产出一条结构化 `Candidate ODO`
3. `Competition` 只提供证据，不直接产经营动作
4. `Profit` 能作为依赖域和门禁存在
5. 输出仍然回到 MealKey 的 `ODO -> POIE` 主链，不出现“双大脑”

## 下一步

1. 用真实 DeerFlow run 替换当前本地 bridge 执行器
2. 接文件 / 图片输入，把 `Sandbox / Files` 跑进 Golden Path
3. 把 `ActionTrace` 接到 DeerFlow tracing correlation
4. 再扩第二条 Golden Path：`今天午餐多 30 单`
