# Runtime Operating State Machine V1

## 目标

把 MealKey Content Engine 继续落成一张可以直接交付研发实现的运行时序图。

它回答的是：

1. AI 店长一天 24 小时分别处于什么状态
2. 每个状态允许分析什么，不允许分析什么
3. 什么时候允许触发 6 种主动理由
4. 什么时候允许找老板，什么时候必须静默
5. WorkThread、Experiment、Result、Memory 在一天中怎么流转

## 总原则

### 1. 运行时状态优先于单个 Agent

任何 Domain Skill 都不能脱离运行时状态直接给出前台内容。

先判断：

```text
我现在处于哪个 Runtime State
↓
此状态允许看哪些 Domain / Trigger
↓
产出 Candidate ODO
↓
交给 POIE 仲裁
↓
才决定 Ask / Auto / Observe / Drop
```

### 2. 不同时段不是同一种 AI

- 高峰前：找一个最值得做的动作
- 高峰中：只护店，不引入新变量
- 餐后：解释发生了什么
- 次日数据完整后：做最完整的一次经营判断

### 3. 没有经营意义的状态不打扰老板

如果当前状态没有值得推进的 ODO，就应该静默。

## 24 小时状态机

### State 1: `night_learn`

时间：
- 凌晨数据逐渐结算后

重点：
- 回收实验
- 回写 Result
- 更新 Goal 进度
- 更新 WorkThread 状态
- 更新 Merchant Understanding / Strategy Memory

允许 Trigger：
- `RESULT`
- `CONTINUATION`

禁止：
- 找老板要新信息
- 推战略建议到前台

输出：
- Result ODO
- Memory Update
- Thread Close / Continue

### State 2: `daily_deep_review`

时间：
- 次日核心数据完整后

重点：
- 全链路分析昨日经营
- 形成候选 ODO
- 生成今日 `Daily Operating State`

分析链：

```text
订单
GMV
实收 / 到手率 / 贡献利润
曝光 → 进店 → 下单
商品结构
活动 + CPC
用户
评价
排名 / 竞争
昨日 Action / Experiment
```

允许 Trigger：
- `RESULT`
- `ANOMALY`
- `GOAL_DEVIATION`
- `CONTINUATION`
- `OPPORTUNITY`

输出：
- Candidate ODO
- Daily Operating Plan
- Strategy Memory Update

### State 3: `pre_open_check`

时间：
- 开店前 / 新经营日初始化

重点：
- 判断今天有没有值得主动处理的事情

检查：
- 营业状态
- Hero SKU 在售
- 活动状态
- 投流账户 / 余额 / 限额
- 平台健康
- 评分明显变化
- 昨日未结束事项
- 今日目标
- 商圈夜间变化

允许 Trigger：
- `TIME`
- `ANOMALY`
- `CONTINUATION`

输出规则：
- 没事则静默
- 能自动处理则直接处理
- 阻塞营业才允许强提醒

### State 4: `pre_peak_decision`

时间：
- 午 / 晚高峰前 30-60 分钟

目标：

```text
现在有没有一个动作最值得做
```

分析顺序：

```text
今日目标
↓
当前预测
↓
流量
↓
商品准备度
↓
活动状态
↓
投流效率
↓
产能
↓
利润空间
↓
商圈竞争
```

允许 Trigger：
- `TIME`
- `ANOMALY`
- `OPPORTUNITY`
- `GOAL_DEVIATION`

约束：
- 每个餐段前最多 1 个 NBA
- 不允许一个节点同时抛多个老板问题
- `CTR/CVR` 弱时，禁止先投流

### State 5: `peak_protect`

时间：
- 高峰进行中

原则：

```text
稳定优先，不轻易引入新变量
```

监控：
- 异常闭店
- 核心 SKU 售罄
- 订单骤降
- 平台异常
- CPC 失控
- 履约异常
- IM 异常
- 退款 / 取消异常

允许 Trigger：
- `TIME`
- `ANOMALY`

禁止：
- 长战略
- 新实验
- 低置信修改商品主图 / 核心价格 / 菜单结构

输出：
- 事故级 ODO
- Auto stop-loss
- Observe

### State 6: `post_peak_review`

时间：
- 餐段结束后

目标：

```text
这一餐到底发生了什么
```

比较基线：
- 同星期历史
- 近 4 周同餐段
- 今日目标
- 商圈
- Top 竞品
- MealKey 动作前后

允许 Trigger：
- `RESULT`
- `ANOMALY`
- `GOAL_DEVIATION`

输出：
- 餐段解释类 ODO
- 晚餐前微调候选

### State 7: `inter_peak_strategy`

时间：
- 午后到晚餐前

目标：
- 判断午餐经验是否值得迁移到晚餐
- 做必要但克制的策略调整

关键检查：

```text
meal_period_transferability
```

如果午餐实验有效，但晚餐人群不同：
- 不能自动复制
- 必须先过 transfer check

允许 Trigger：
- `CONTINUATION`
- `RESULT`
- `OPPORTUNITY`

### State 8: `day_close`

时间：
- 营业结束到次日数据完整前

目标：
- 轻复盘，不做深结论

检查：
- 是否有遗留异常
- 是否有明早前必须知道的信息
- 是否有即将过期活动
- 是否有待观察实验

允许 Trigger：
- `CONTINUATION`
- `TIME`

禁止：
- 输出重战略结论
- 做深度归因

## 6 Trigger 在状态机里的出现时机

| Trigger | 主要出现状态 |
| --- | --- |
| `TIME` | `pre_open_check` / `pre_peak_decision` / `peak_protect` / `day_close` |
| `ANOMALY` | `daily_deep_review` / `pre_open_check` / `pre_peak_decision` / `peak_protect` / `post_peak_review` |
| `CONTINUATION` | `night_learn` / `pre_open_check` / `inter_peak_strategy` / `day_close` |
| `OPPORTUNITY` | `daily_deep_review` / `pre_peak_decision` / `inter_peak_strategy` |
| `GOAL_DEVIATION` | `daily_deep_review` / `pre_peak_decision` / `post_peak_review` |
| `RESULT` | `night_learn` / `daily_deep_review` / `post_peak_review` / `inter_peak_strategy` |

## Ask Engine 在状态机里的规则

不是每个状态都允许问老板。

### 允许主动问老板

- `pre_peak_decision`
- `inter_peak_strategy`
- 极少数 `pre_open_check`

前提：

```text
AskScore =
DecisionImpact
× Uncertainty
× Urgency
× HumanUniqueness
÷ InterruptionCost
```

并且该问题能直接解锁当前最值得推进的 ODO。

### 原则上不该问老板

- `peak_protect`
- `night_learn`
- `daily_deep_review`

这些状态更偏系统内部运转。

## WorkThread / Experiment / Memory 流转

```text
Deep Review
↓
Candidate ODO
↓
POIE
↓
WorkThread 建立 / 续航 / 关闭
↓
Action / Experiment
↓
Peak / Meal Review 继续观察
↓
Night Learn 回收结果
↓
Memory 更新
↓
第二天继续
```

## Runtime Contract

建议运行时至少显式维护这几个对象：

### 1. `DailyOperatingState`

用于描述门店此刻所处运行状态：

```json
{
  "current_state": "pre_peak_decision",
  "current_meal_period": "lunch",
  "active_goal": "午餐利润提升",
  "protect_mode": false,
  "owner_interrupts_used": 1,
  "pending_trigger_reasons": ["ANOMALY", "OPPORTUNITY"]
}
```

### 2. `OperatingClockNode`

用于定义每个时段能做什么：

```json
{
  "node": "pre_peak_decision",
  "purpose": "只找一个最值得做的动作",
  "allowed_triggers": ["TIME", "ANOMALY", "OPPORTUNITY", "GOAL_DEVIATION"],
  "allow_owner_interrupt": true,
  "protect_mode": false
}
```

### 3. `RuntimeTransition`

用于把一天串成状态机：

```json
{
  "from_state": "pre_peak_decision",
  "to_state": "peak_protect",
  "condition": "meal_period_started"
}
```

## Service 分工建议

| Service | 负责 |
| --- | --- |
| `context-service` | Merchant Context、Gap、Ask Engine |
| `analysis-service` | Daily Operating State、Analysis Playbook、Clock Node 调度 |
| `decision-service` | ODO、Impact、Profit Gate、Risk Gate |
| `poie-service` | Trigger、Arbitration、Next Best Action |
| `work-service` | Goal、WorkThread、Action、Experiment、Result、Memory |

## 实现顺序

### Phase 1

- 先把现有 `ops.operating_clock` 挂到显式 `OperatingClockNode`
- 统一 phase 命名和 Runtime State 命名

### Phase 2

- 所有 Clock Node 只产 `Candidate ODO`
- 统一交给 `decision-service` + `poie-service`

### Phase 3

- 中栏 / 左栏 / 右栏只消费 Projection
- UI 不再感知外卖经营细节

## 验收标准

给定任意门店的一天时间线，系统应能回答：

1. 当前处于哪个 Runtime State？
2. 此状态允许哪些 Trigger？
3. 此状态允许不允许打扰老板？
4. 当前最高优先级的 ODO 是什么？
5. 它会投影成哪个 WorkThread / Guide / ProactiveFeed？
6. 实验结果会在什么状态被回收并写回 Memory？
