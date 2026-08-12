# Runtime V1 Backend Contract

## 目标

把 MealKey Runtime V1 从状态机规格继续收束成后端可以直接开工的接口级设计。

本文件冻结三件事：

1. 数据库对象如何承载 Runtime V1
2. API Contract 如何给前端和调度层供数
3. 事件 Schema 如何把 `Signal -> Event -> Candidate ODO -> Arbitration -> Action` 串起来

## 核心对象总览

Runtime V1 长期稳定的业务对象应固定为这 10 个：

| 对象 | 解决的问题 | 生命周期 |
| --- | --- | --- |
| `store_state` | 这家店现在是什么状态 | 持续更新 |
| `merchant_context` | 老板的目标、偏好、约束、权限 | 长期 |
| `goal` | 老板想要什么结果 | 天/周/月 |
| `signal` | 原始数据发生什么变化 | 高频 |
| `business_event` | 哪个变化具有经营意义 | 小时/天 |
| `odo` | MealKey 对这件事的完整经营判断 | 一次决策 |
| `work_thread` | 一件事情如何持续往前走 | 多天 |
| `action` | AI 或老板具体做什么 | 分钟/天 |
| `experiment` | 怎么验证动作有没有效果 | 小时/周 |
| `strategy_memory` | 做完学到了什么 | 长期 |

关键原则：

```text
Event ≠ ODO ≠ WorkThread
```

## 一、数据库对象

Runtime V1 不建议推翻现有对象，而是沿现有表扩展。

### 现有表继续作为主干

| 表 | 作用 |
| --- | --- |
| `merchant_understanding` | MUE / Checklist / Gap / Permission |
| `goal` | 老板想达到什么 |
| `operating_thread` | 持续推进的经营故事线 |
| `operating_decision` | ODO 落库审计 |
| `experiment` | Action 的观察窗 |
| `strategy_memory` | Result -> Lesson |

### Runtime V1 新增建议表

#### 0. `store_state_snapshot`

保存某一时刻 AI 对店铺的统一认知，支持：

```text
AI 当时是基于什么店铺状态做这个决定的？
```

建议字段：

```text
id
store_id
snapshot_at
state_json
```

#### 0.5 `merchant_context_item`

保存细粒度 Context Item，而不是把老板偏好塞进聊天记录。

建议字段：

```text
id
merchant_id
store_id
key
value_json
source
confidence
valid_from
valid_until
last_verified_at
required_for_json
blocking
ask_score
```

#### 0.6 `signal`

保存高频原始 signal。大部分只用于聚合，不会直接打扰老板。

#### 0.7 `business_event`

保存有经营意义的事实事件。

这里必须和 `trigger_reason` 分开：

```text
event_type ≠ trigger_reason
```

#### 1. `daily_operating_plan`

保存 Deep Review 后生成的“AI 店长今天脑子里的计划”。

字段建议：

```text
id
store_id
plan_date
runtime_state
current_meal_period
core_goal
focus_meal_period
active_experiment
protected_metrics_json
auto_exec_budget_json
active_threads_json
check_points_json
summary
status
```

#### 2. `runtime_event`

保存 Runtime V1 事件链路中的统一事实包。

字段建议：

```text
id
store_id
state
node
trigger_reason
domain
event_level
subject_type
subject_id
title
detail
event_payload_json
evidence_json
priority_score
execution_mode
status
source_odo_id
occurred_at
resolved_at
```

用途：

- 给右栏 Proactive Feed 一个真正稳定的后端来源
- 让调度器、POIE、前端都看到同一份事件事实
- 保留 ODO / Trigger / Runtime State 的审计轨迹

#### 3. `operating_action`

保存系统真正执行过什么，支持审计：

```text
为什么 AI 自己花了这 60 块？
```

#### 4. `experiment_result`

把 Result 从 Experiment 中独立出来，支持：

```text
RESULT Trigger
↓
Continuation
```

## 二、表之间的关系

```text
merchant_understanding
        ↓
daily_operating_plan
        ↓
runtime_event
        ↓
operating_decision
        ↓
operating_thread
        ↓
experiment
        ↓
strategy_memory
```

关键关系：

- 一个 `daily_operating_plan` 会关联多个 `runtime_event`
- 一个 `runtime_event` 最终可能进入一个 `operating_decision`
- 一个 `operating_decision` 可以挂到一个 `operating_thread`
- 一个 `operating_decision` 执行后可能创建一个 `experiment`
- 一个 `experiment` 结束后会写入 `strategy_memory`

## 三、API Contract

### 1. Workspace Runtime

`GET /v1/stores/{store_id}/workspace`

用途：
- 返回三栏投影
- 返回当前 Runtime State
- 返回当前最高优先级 Guide

响应结构：

```json
{
  "store": {
    "store_id": "store_1",
    "store_name": "老王牛肉饭",
    "runtime_state": "pre_peak_decision"
  },
  "left": {
    "need_you": [],
    "active": [],
    "waiting": [],
    "completed": [],
    "opportunities": [],
    "active_goal": null,
    "threads": []
  },
  "center": {
    "active_thread_id": "thread_1",
    "guide": {},
    "principle": "系统负责发现所有事情..."
  },
  "right": {
    "proactive_feed": [],
    "filtered_count": 0
  },
  "meta": {
    "candidates_total": 7,
    "filtered_noop_count": 4,
    "mealkey_score": {},
    "operation_score": {}
  }
}
```

### 2. Daily Plan

`GET /stores/{store_id}/daily-plan`

用途：
- 取当前有效的 `DailyOperatingPlan`
- 给开发调试、运营校验、Agent 侧协作使用

响应结构：

```json
{
  "plan": {
    "date": "2026-08-12",
    "current_runtime_state": "pre_peak_decision",
    "current_meal_period": "lunch",
    "core_goal": "利润优先",
    "focus_meal_period": "lunch",
    "active_experiment": "黑椒牛肉饭新主图",
    "protected_metrics": ["贡献利润率", "到手率"],
    "auto_exec_budget": {
      "ads_daily_limit": 300
    },
    "active_threads": ["牛肉饭 Top3"],
    "check_points": ["10:30", "14:00", "17:00", "数据结算后"]
  },
  "runtime_state": "pre_peak_decision"
}
```

### 3. Intent Runtime Entry

`POST /v1/stores/{store_id}/intent`

用途：
- 老板主动说一句话，也必须进入 Runtime V1 链路

原则：

```text
Intent
→ Goal / Gap / Action Request
→ Candidate ODO
→ POIE
→ Guide / Auto / Observe
```

### 4. Runtime Feed

建议新增：

`GET /v1/stores/{store_id}/runtime-feed`

用途：
- 直接返回 Runtime V1 的事件流，不混杂老 dashboard 数据

查询维度：

- `state`
- `trigger_reason`
- `domain`
- `status`
- `limit`

### 5. Runtime Queue

建议新增：

`GET /v1/stores/{store_id}/runtime-queue`

用途：
- 给 POIE / 调试台 / 运维侧看 `Candidate ODO -> Arbitration` 队列

## 四、事件 Schema

### 1. Signal

原始输入，不直接推前台。

```json
{
  "id": "sig_1",
  "store_id": "store_1",
  "state": "peak_protect",
  "node": "lunch_protect",
  "source": "platform",
  "kind": "hero_sku_sold_out",
  "payload": {
    "sku_id": "sku_1"
  },
  "observed_at": "2026-08-12T12:03:00+08:00"
}
```

### 2. Event

Signal 收敛后的经营事实。

```json
{
  "id": "evt_1",
  "store_id": "store_1",
  "state": "peak_protect",
  "node": "lunch_protect",
  "trigger_reason": "ANOMALY",
  "domain": "PRODUCT",
  "subject": {
    "type": "sku",
    "id": "sku_1",
    "name": "黑椒牛肉饭"
  },
  "title": "黑椒牛肉饭提前售罄",
  "detail": "较历史正常售罄时间提前 75 分钟",
  "evidence": [
    "历史正常售罄时间 13:18",
    "今日售罄时间 12:03"
  ]
}
```

### 3. Candidate ODO

Event 经过诊断后的候选经营判断。

```json
{
  "id": "odo_1",
  "state": "peak_protect",
  "node": "lunch_protect",
  "trigger_reason": "ANOMALY",
  "domain": "PRODUCT",
  "why_now": "午高峰中 Hero SKU 异常提前售罄",
  "diagnosis": {
    "primary": "需要先确认真实备货情况"
  },
  "required_context_keys": ["today_stockout_reason"],
  "execution_mode": "ASK_INFORMATION"
}
```

### 4. Arbitration Queue Item

POIE 的输入输出单元。

```json
{
  "candidate_odo_id": "odo_1",
  "runtime_state": "peak_protect",
  "priority_score": 88.3,
  "decision": "ASK_INFORMATION",
  "interrupt_owner": true,
  "guide_projection_id": "guide_1"
}
```

## 五、Execution Mode

Runtime V1 正式冻结 6 个出口：

```text
AUTO
AUTO_REPORT
ASK_APPROVAL
ASK_INFORMATION
OBSERVE
DROP
```

兼容建议：

- `AUTO_REPORT` 在 DB 可映射为 `AUTO_AND_REPORT`
- 其他保持一致

## 六、V1 最小闭环

Runtime V1 第一阶段只要求打通这条链：

```text
Daily Deep Review
→ Pre-Peak Decision
→ Peak Protect
→ Post-Peak Review
```

限制范围：

- Domain 只先支持 `PRODUCT / TRAFFIC / PROFIT / COMPETITION`
- Trigger 只先支持 `TIME / ANOMALY / CONTINUATION / RESULT`
- Execution Mode 六种全部支持

## 七、推荐实现顺序

### Step 1

- 新建 `daily_operating_plan` / `runtime_event` 表
- 给 `operating_decision` 补 `runtime_state / node / source_event_id`

### Step 2

- 新建 `runtime_api` schema
- 让 `workspace` / `daily-plan` / `intent` 三个接口先对齐 contract

### Step 3

- Signal / Event / Candidate ODO / Arbitration Queue 全部落结构化 schema
- 不再依赖前端侧自由拼装

### Step 4

- 四个最小节点先跑通
- 再接 `OPPORTUNITY / GOAL_DEVIATION / CUSTOMER / REPUTATION / PLATFORM / STORE_GROWTH`

## 八、验收标准

如果后端实现完成，应该能回答：

1. 当前门店正处于哪个 Runtime State？
2. 当前状态允许哪些 Trigger？
3. 当前候选 ODO 有哪些？
4. 为什么只出现这 1 条老板需要处理的 Guide？
5. 当前右栏事件来自哪个 Runtime Event / ODO？
6. 当前动作最终会不会形成 Experiment 和 Strategy Memory？
