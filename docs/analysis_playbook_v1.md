# Analysis Playbook V1

## 目标

规定 MealKey 在什么时间分析什么。  
不是所有分析每分钟都跑，也不是大模型“想到什么分析什么”。

## 统一分析链路

每次正式分析都走同一条路径：

```text
Checklist
  ↓
Signal
  ↓
Event
  ↓
Diagnosis
  ↓
Candidate Decision
  ↓
ODO
  ↓
Arbitration
  ↓
Execute / Ask / Observe / Drop
```

## 8 个经营域

所有分析模块都必须归属到这 8 个域之一：

- `platform`
- `product`
- `competition`
- `traffic`
- `profit`
- `customer`
- `reputation`
- `store_growth`

## Daily Operating Clock

### 1. 开店前 `morning_readiness`

目标：今天准备好了吗？

| 检查项 | domain | 输出 |
| --- | --- | --- |
| 平台连接 / 营业状态 | `platform` | 是否进入准备态 |
| 核心 SKU 在售 / 售罄风险 | `platform` / `product` | 异常则生成保护类 ODO |
| 活动是否生效 | `traffic` | 是否需要修正 |
| 投流账户 / 余额 / 限额 | `traffic` | 是否允许午高峰动作 |
| 异常评价 / 待回复 | `reputation` | 是否进入早间处理 |
| 天气 / 商圈临时变化 | `competition` | 是否影响今日策略 |

输出规则：

- 全部正常：静默
- 有问题但 AI 可自处理：进入 `auto_do`
- 阻塞当前营业：进入保护类 ODO

### 2. 午高峰前 `pre_lunch_nba`

目标：午餐前有没有一个最值得做的动作？

| 分析项 | domain |
| --- | --- |
| 当前订单 / 利润预测 | `profit` |
| 曝光 / CTR / CVR | `traffic` / `product` |
| Hero SKU 准备度 | `product` |
| 平台活动 / 补贴 | `traffic` |
| CPC readiness | `traffic` |
| 利润空间 / 底线 | `profit` |
| 目标偏差 | `profit` |

产出规则：

- 最多 1 个 NBA
- 如果缺利润底线 / 投流授权 / 产能上限，则走 Checklist 判定
- 不允许一个节点同时扔出多个“建议老板处理”

### 3. 午高峰中 `lunch_protect`

目标：Protect Mode，只护店，不搞长战略。

允许分析：

- 售罄
- 闭店
- 订单异常
- CPC 失控
- 平台异常
- 评价事故

禁止分析：

- 周战略
- 第二线上店
- 长周期用户运营

输出规则：

- 仅事故级 ODO 可打扰老板
- 其他优先自动降载、自动止损、继续观察

### 4. 午餐结束 `post_lunch_review`

目标：午餐结果怎样，晚餐要不要改策略？

| 分析项 | domain |
| --- | --- |
| 目标完成度 | `profit` |
| 商圈对比 | `competition` |
| 商品贡献结构 | `product` |
| 投流效果 | `traffic` |
| 早间动作初步结果 | `product` / `traffic` / `customer` |

输出规则：

- 可产生晚餐前微调 ODO
- 不做终局结论

### 5. 晚高峰前 / 中

和午餐同构：

- `pre_dinner_nba`
- `dinner_protect`

只有门店存在明确晚高峰时才启用。

### 6. 次日数据完整后 `night_settlement`

目标：完整结算昨日经营，并把结果写回记忆。

| 分析项 | domain |
| --- | --- |
| 订单 / GMV / 贡献利润 | `profit` |
| 商品 / SKU / 主图实验 | `product` |
| 活动 / 补贴 / 投流 | `traffic` |
| 用户 / 复购 / 召回 | `customer` |
| 评价 / 差评 / 回复 | `reputation` |
| 排名 / 竞品变化 | `competition` |
| 第二线上店相关信号 | `store_growth` |

输出规则：

- 允许生成 `RESULT` 类 ODO
- 允许更新 Strategy Memory
- 允许关闭 / 续航 WorkThread

### 7. 周 / 月策略节点

#### `weekly_strategy`

重点回答：

- 哪些动作重复有效
- 哪些问题反复出现
- 当前目标轨迹是否偏离
- 用户结构和商品结构有没有变化

#### `monthly_strategy`

重点回答：

- 商品结构和广告结构是否该重构
- 是否出现第二线上店机会
- 当前模式下的利润模型是否健康

## Trigger × Domain 矩阵

| Trigger | Domain | 典型内容 |
| --- | --- | --- |
| `TIME` | `traffic` | 午高峰前是否加投 |
| `TIME` | `platform` | 开店前检查在售、活动、营业状态 |
| `ANOMALY` | `product` | Hero SKU CTR 连续下降 |
| `ANOMALY` | `reputation` | 评分突然下降 / 差评集中 |
| `CONTINUATION` | `competition` | 牛肉饭 Top3 计划进入下一阶段 |
| `CONTINUATION` | `customer` | 老客召回进入第 7 天复盘 |
| `OPPORTUNITY` | `traffic` | 新补贴值得参加 |
| `OPPORTUNITY` | `store_growth` | 商圈出现第二线上店机会 |
| `GOAL_DEVIATION` | `profit` | 月利润预测低于目标 |
| `RESULT` | `product` | 主图实验 CTR +14% |
| `RESULT` | `customer` | 召回用户复购提升 |

## 节点输出约束

### 允许直接产出 ODO 的节点

- `morning_readiness`
- `pre_lunch_nba`
- `lunch_protect`
- `post_lunch_review`
- `pre_dinner_nba`
- `dinner_protect`
- `night_settlement`
- `weekly_strategy`
- `monthly_strategy`

### 不允许直接推前台的东西

- 原始 Signal
- 中间诊断草稿
- 未经过 Risk Gate 的候选动作
- 多个并列建议列表

## 典型例子

### 例 1：午高峰前

```text
时间：
10:25

节点：
pre_lunch_nba

发现：
黑椒牛肉饭 CTR 连续下降

缺失：
hero_item_floor_price

结果：
生成 product 域异常 ODO
中栏向老板追问最低可接受价格
而不是继续自动判断活动是否值得参加
```

### 例 2：次日结算

```text
时间：
次日 07:10

节点：
night_settlement

发现：
主图实验 CTR +14%

结果：
生成 RESULT × PRODUCT 的 ODO
写入 Memory
右栏显示“结果出来了”
左栏原 WorkThread 进入下一阶段
```

## 工程落点

建议新增 `AnalysisNode` / `AnalysisPlaybookRule`：

```json
{
  "node": "pre_lunch_nba",
  "enabled_when": ["store.open_for_lunch = true"],
  "domains": ["traffic", "product", "profit", "competition"],
  "output_limit": 1,
  "protect_mode": false
}
```

V1 实现顺序：

1. 把现有 time / anomaly / result 逻辑先挂到固定节点
2. 让每个节点声明可分析 domain 和输出上限
3. 所有分析先产 `Candidate Decision`
4. 统一交给 ODO + Arbitration
