# MealKey Closed Loop V1

## 目标

Closed Loop V1 不以“新增更多 AI 能力”作为目标。

它只证明三件事：

1. 同一件经营事项能持续活下去。
2. 这件事的结果会改变系统下一次判断。
3. 成熟以后，系统能够自己执行其中一部分动作。

最终主链冻结为：

```text
经营事实
  ↓
Signal / Event
  ↓
ODO
  ↓
WorkThread
  ↓
Now
  ↓
Guide / ActionSpec
  ↓
确认 / 执行
  ↓
Observation
  ↓
Result
  ↓
Memory
  ↓
Next Decision
```

任何新能力都只能接到这条链上，不能再形成一套平行工作流。

## 北极星问题

以后所有新增需求先过这一关：

> 它是在让一个经营事项更完整地从发现走到结果，还是又制造了一条新的产品分叉？

## 三阶段路线

### Phase A — One Closed Loop

目标：

> 证明一个经营事项在 MealKey 中拥有唯一身份，并且可以从“需要处理”持续推进到“已执行 / 等待结果”。

Phase A 的核心不是新 Agent，而是经营事项状态机。

#### 硬验收 1：唯一事项身份

例如“黑椒牛肉饭 CTR 下滑”这件事，无论用户：

- 点击左栏“牛肉饭主图优化”
- 点击右栏“发现 CTR 异常”
- 在中间继续和 AI 对话
- 上传一张牛肉饭实物图
- 回答“这张图份量真实吗”

后台始终都是同一个：

```text
work_thread_id = wt_xxx
```

不允许被重新生成成 `wt_xxx_2`、`wt_xxx_3`。

#### 硬验收 2：动作后状态继续推进

不允许：

```text
AI建议换主图
↓
用户确认
↓
重新开始一段对话
```

必须：

```text
RECOMMENDED
↓
WAITING_APPROVAL
↓
APPROVED
↓
READY_TO_EXECUTE
↓
EXECUTED
↓
OBSERVING
↓
WAITING_RESULT
```

#### Phase A 反目标

明确不做：

- 新 Agent
- 新一级产品模块
- Market 大系统
- 全量平台接入
- 自动调价
- 自动预算
- 自动参加平台活动
- 大规模 BI
- 多品类扩张
- 一店多开自动化
- 新的“学习中心”页面

### Phase B — Make Result Matter

目标：

> 历史发生过的结果必须进入下一次决策。

正式链：

```text
StoreState真实读数
      ↓
Observation
      ↓
Result
      ↓
Attribution
      ↓
Strategy Memory
      ↓
Candidate Action Ranking
```

#### 硬验收

同样的经营情境第二次发生时，系统排序必须改变，并且能解释为什么改变。

不是 memory 表里多一条记录，而是：

- 候选动作排序真的不同
- 风险判断真的不同
- MealKey 能引用相似上下文里的历史结果

#### 本阶段同时补齐的经营 Truth

- Canonical Profit Model
- Profit Diagnosis
- Campaign Decision

所有关键字段必须带：

```text
value
source
confidence
last_updated
```

缺失就显式标记为 `UNKNOWN`，禁止让模型猜真实经营数据。

### Phase C — Make Action Real

目标：

> 把 Human Executor 换成 Platform Executor。

只选一条低风险动作先打通。建议优先：

1. 普通评价回复
2. 商品标题/描述更新

暂不做：

- 自动改价
- 自动大额投流
- 自动参加平台活动
- 自动下架

## 核心对象图

Closed Loop V1 只围绕 6 个主对象开发：

```text
Signal
  │
  ▼
ODO
  │
  ▼
WorkThread
  │
  ├─────────────┐
  ▼             ▼
ActionSpec   Context Gap
  │             │
  ▼             ▼
Action       Ask User
  │
  ▼
Result
  │
  ▼
Memory
```

### 1. Signal / Event

只回答：

> 发生了什么？

例如：

```json
{
  "type": "SKU_CTR_DROP",
  "subject": "黑椒牛肉饭",
  "value": -0.148,
  "baseline": "7d_same_meal_period"
}
```

Signal 不允许直接给主人建议。

### 2. ODO

回答：

> MealKey 对这件事现在的经营判断是什么？

至少包含：

- 为什么现在
- 发现什么
- 诊断是什么
- 证据是什么
- 置信度
- 预计业务影响
- 建议动作
- 风险
- 是否需要老板
- 成功指标
- 什么时候回来检查

ODO 是判断，不是任务。

### 3. WorkThread

回答：

> 这件经营事情现在推进到哪里了？

例如：

```text
黑椒牛肉饭点击恢复

开始：
CTR -14.8%

当前：
主图方案已确认

状态：
执行中

目标：
CTR +8%

观察窗口：
48h
```

左栏本质上不是 task list，而是 `WorkThread Lifecycle Projection`。

### 4. ActionSpec

这是 Phase A 最重要的新对象之一。

不能只存一句“建议优化主图”，而应该是可执行包：

```json
{
  "type": "CHANGE_PRODUCT_IMAGE",
  "subject": {
    "type": "sku",
    "name": "黑椒牛肉饭"
  },
  "reason": "CTR连续3个午餐时段低于基线",
  "execution_package": {
    "brief": "...",
    "asset": "...",
    "instructions": "..."
  },
  "risk": "LOW",
  "requires_approval": true,
  "success_metric": {
    "metric": "ctr",
    "target_lift": 0.08
  },
  "guardrails": {
    "cvr_drop_max": 0.03
  },
  "observation_window": "48h"
}
```

以后从人工执行升级成平台自动执行时，不应该改变 `ActionSpec` 本身，只改变 executor。

### 5. Result

不能只写“实验完成”，必须形成经营结果：

- 做了什么
- 原来多少
- 现在多少
- 变化多少
- 是否达到目标
- Guardrail 有没有恶化
- 结果可信度多少
- 保留 / 放大 / 回滚 / 继续观察

例如：

```json
{
  "outcome": "SUCCESS",
  "primary": {
    "ctr_lift": 0.146
  },
  "guardrails": {
    "cvr": "PASS"
  },
  "decision": "KEEP",
  "confidence": 0.87
}
```

### 6. Memory

Phase A 先存对结构，Phase B 才要求真正参与决策。

正确结构应该是：

- 在什么上下文
- 出现什么问题
- 用了什么策略
- 产生什么结果
- 对什么范围有效
- 置信度多少

## 三栏 Projection 原则

三栏必须彻底变成 Projection，而且必须指向同一个 `work_thread_id`。

### 左栏：`WorkThreadProjection`

回答：

> 我的事情现在在哪？

只显示：

- 需要你
- 正在进行
- 等待结果
- 最近完成

### 中栏：`GuideProjection`

回答：

> 现在 MealKey 最需要我做什么？

它是 Guide，不是 dashboard。

### 右栏：`ProactiveEventProjection`

回答：

> MealKey 今天为什么在行动？

它解释当前事件、状态和等待点，但不能再形成独立工作流。

## 工程收口清单

### P0-1：全链 `work_thread_id`

以下对象全部必须可追溯到同一个 `work_thread_id`：

- ODO
- Guide
- Card
- Conversation
- Action
- Experiment
- Result
- ProactiveEvent
- Attachment
- Approval

### P0-2：建立显式 WorkThread State Machine

冻结状态：

```text
DISCOVERED
ANALYZING
NEED_INFORMATION
NEED_APPROVAL
READY_TO_EXECUTE
EXECUTING
OBSERVING
WAITING_RESULT
COMPLETED
FAILED
CANCELLED
NO_EFFECT
```

UI 根据状态渲染，业务逻辑负责改变状态。

### P0-3：前端状态机收口

前端最终只关心：

```text
HOME
THREAD
INTERVIEW
SETTINGS
```

`THREAD` 内部状态来自 `WorkThread` 本身，不再把业务状态继续存到 `<body class>`。

### P0-4：`runtime / workspace / store / settings` 边界

`runtime` 负责：

- 当前 Now
- 首页三栏 Projection
- Intent Router
- Daily operating projection

`workspace` 负责：

- WorkThread
- Guide
- Conversation
- Action
- Attachment
- Approval
- Result

`store` 负责：

- StoreState
- ProductState
- ProfitState
- PlatformState

`settings` 只负责：

- 平台连接
- 老板偏好
- 权限
- Operating Budget
- 长期约束

### P0-5：Action Registry

第一批只支持：

- `CHANGE_PRODUCT_IMAGE`
- `CHANGE_PRODUCT_TITLE`
- `REPLY_REVIEW`

每个 Action Type 必须定义：

- `required_context`
- `input_schema`
- `risk_level`
- `approval_requirement`
- `execution_method`
- `rollback_method`
- `success_metrics`
- `default_observation_window`

以后新增动作，只能往 Registry 增加新的 Action Type，不能再造一套 Agent 流程。

## Phase A 第一批只跑 3 类动作

### Action 1：主图优化

```text
异常发现
→ 诊断
→ 生成 brief
→ 请求真实商品图
→ 生成/选择主图
→ 确认
→ 人工平台执行
→ 标记已执行
→ 等结果
```

### Action 2：商品标题优化

```text
问题发现
→ 生成标题
→ 确认
→ 复制/人工执行
→ 标记执行
→ 进入观察
```

### Action 3：差评回复

```text
差评 Event
→ 归因
→ 风险判断
→ 回复稿
→ 老板确认
→ 人工回复
→ 已执行
→ 问题关闭/继续整改
```

严重客诉自动进入：

```text
NEED_HUMAN
```

## 一个必须冻结的细节

“已生成执行包”不等于“已执行”。

必须严格分开：

```text
READY_TO_EXECUTE
```

和：

```text
EXECUTED
```

否则系统会错误地认为“我给了建议 = 店铺已经被改了”，直接污染 Result 和 Memory。

## Closed Loop V1 KPI

最终先冻结 6 个指标：

1. `Time to First Useful Action`
2. `Same Thread Continuity Rate`
3. `Action Execution Rate`
4. `Closed Loop Rate`
5. `Positive Result Rate`
6. `Repeat Strategy Lift`

其中：

- `Same Thread Continuity Rate` 是 Phase A 核心指标
- `Closed Loop Rate` 是整个 V1 最关键指标
- `Repeat Strategy Lift` 用来判断 MealKey 是否真的越来越会经营

## 开发决策规则

以后任何需求都先问 3 个问题：

### 1. 它服务现有 Closed Loop 吗？

如果不是，延期。

### 2. 它解决当前闭环的哪个断点？

必须能明确对应：

```text
Sense
Decide
Act
Observe
Learn
```

### 3. 不做它，当前 Golden Flow 会失败吗？

如果不会，降低优先级。

## 当前结论

停止继续讨论大架构，直接开 Phase A。

建议第一批研发票：

1. `CLV1-A01`：让左栏卡片、中间 Guide、右栏 Event 指向同一个 `work_thread_id`，并点击后恢复同一 Thread 状态
2. `CLV1-A02`：实现 WorkThread State Machine
3. `CLV1-A03`：统一 ActionSpec + Action Registry
4. `CLV1-A04`：跑通“主图优化”从 ODO → 执行包 → 已执行 → Waiting Result

做到 `A04` 时，产品才第一次真正进入：

> 这不是一张 AI 建议卡了，这是一件正在被 MealKey 持续经营的事情。
