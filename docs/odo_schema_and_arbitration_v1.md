# ODO Schema And Arbitration V1

## 目标

定义 MealKey 进入经营系统的统一对象：`ODO — Operating Decision Object`。  
任何值得进入左栏、中栏、右栏的经营判断，都必须先变成一个 ODO。

## 核心原则

1. Agent 不得直接推内容到前台
2. Event 不等于 ODO
3. ODO 必须同时回答“为什么现在”“发现了什么”“准备怎么做”“需不需要老板”
4. 三栏都是同一个 ODO 的不同投影

## ODO Schema

```json
{
  "id": "odo_20260812_001",
  "reason": "ANOMALY",
  "domain": "PRODUCT",
  "object": {
    "type": "sku",
    "id": "sku_8291",
    "name": "黑椒牛肉饭"
  },
  "source_node": "pre_lunch_nba",
  "why_now": "连续3个午餐时段 CTR 低于 7 日基线",
  "finding": {
    "metric": "ctr",
    "change": "-14.8%",
    "benchmark": "7d_same_meal_period"
  },
  "diagnosis": {
    "primary": "首屏商品吸引力下降",
    "confidence": 0.86
  },
  "evidence": [
    "曝光基本稳定",
    "价格没有明显变化",
    "2家核心竞品近期更换主图"
  ],
  "business_impact": {
    "orders": "-18~25/day",
    "profit": "-1800~2600/week"
  },
  "recommended_action": {
    "type": "image_ab_test",
    "window": "48h"
  },
  "required_context_keys": [
    "real_food_photo"
  ],
  "human_required": true,
  "human_reason": "需要确认新版主图中的实际商品份量",
  "success_metric": {
    "metric": "ctr",
    "target": "+8%"
  },
  "next_check_at": "2026-08-14T14:00:00+08:00"
}
```

## 字段定义

| 字段 | 说明 |
| --- | --- |
| `reason` | 6 种主动理由之一 |
| `domain` | 8 个经营域之一 |
| `object` | 本次经营判断针对的对象 |
| `source_node` | 来自哪个 Analysis Playbook 节点 |
| `why_now` | 为什么是现在 |
| `finding` | 当前指标变化或经营发现 |
| `diagnosis` | AI 对问题的主判断与置信度 |
| `evidence` | 支撑判断的证据 |
| `business_impact` | 对订单 / 利润 / 排名 / 评分 / 复购的影响 |
| `recommended_action` | 单一推荐动作 |
| `required_context_keys` | 依赖哪些 Checklist 字段 |
| `human_required` | 是否真的需要老板 |
| `human_reason` | 为什么必须是老板 |
| `success_metric` | 怎么算做成 |
| `next_check_at` | 下一次回看时间 |

## 投影规则

### 1. 左栏：WorkThreadProjection

如果 ODO 需要跨时段持续推进，就必须挂到一个 WorkThread 上。

示例：

```text
Thread:
牛肉饭点击恢复

状态:
等待主图确认

下一节点:
48h 主图实验
```

左栏展示：

```text
需要你
- 牛肉饭主图确认
```

### 2. 中栏：GuideDirective

中栏永远不是 ODO 报告，而是“为了把当前这件经营工作继续往前推，AI 现在最需要老板回答哪一句”。

示例：

```text
我已经把问题定位到主图。

新图已经准备好了，但我需要确认图片里的牛肉份量与实际出餐一致。

这张图和实际份量一致吗？

[一致] [看起来多了] [我发张实物图给你]
```

### 3. 右栏：ProactiveEventProjection

右栏记录经营轨迹，只保留最重要的三四行：

```text
09:42 · 异常 · 商品

黑椒牛肉饭正在丢点击
连续3个午餐 CTR 低于基线 14.8%

已完成原因排查，正在等待实物份量确认

需要你
```

## 仲裁规则

POIE 不直接看 UI，只看 ODO 的经营价值。

### 判断维度

```text
影响大吗？
现在紧急吗？
置信度够吗？
和当前 Goal 有关吗？
AI 自己能做吗？
动作可逆吗？
会花多少钱？
必须老板知道吗？
老板今天已经被打扰几次了？
```

### V1 评分

```text
Priority =
  BusinessImpact
  × Urgency
  × Confidence
  × GoalRelevance
  × HumanNeed
  ÷ InterruptionCost
```

## 五种仲裁出口

| 出口 | 含义 | 例子 |
| --- | --- | --- |
| `auto_do` | AI 自己做 | 普通好评自动回复 |
| `report_after_doing` | 做完后告诉老板 | 午餐预算在授权范围内已调整 |
| `need_owner_now` | 现在需要老板 | 请确认主图真实性 / 实际份量 |
| `observe_only` | 继续观察 | 竞品降价但暂不跟进 |
| `drop` | 丢弃 | 数据噪声，无经营意义 |

## 风险门

仲裁之后，还要过 `Permission / Risk Gate`。

### 允许直接执行

- 已授权的低风险动作
- 可逆且低成本的自动动作
- 不穿透利润底线的微调动作

### 必须老板确认

- 改价
- 深折
- 超预算投流
- 真实性未确认的主图上线
- 补偿 / 赔付
- 第二线上店启动

### 进入 Safe Mode

当这些关键信息缺失时，ODO 仍可生成，但不能自动执行：

- `profit_floor_rate`
- `hero_item_floor_price`
- `ads_daily_budget_limit`
- `lunch_capacity_per_hour`

## 典型例子

### 1. ANOMALY × PRODUCT

```text
黑椒牛肉饭 CTR 下降
AI 已排除价格与曝光异常
需要老板确认主图真实性
→ need_owner_now
```

### 2. TIME × TRAFFIC

```text
午高峰前 ROI 正常，预算只用到计划 42%
在授权范围内
→ auto_do / report_after_doing
```

### 3. RESULT × CUSTOMER

```text
高价值老客召回完成
23 人中 7 人回流
新增贡献利润 ¥436
→ report_after_doing
```

### 4. OPPORTUNITY × STORE_GROWTH

```text
商圈价格带出现空档
第二线上店 ROI 预测成立
缺失 multi_store_intent
→ 先 GuideDirective 询问老板意愿
```

## 建议数据结构

V1 建议在现有 `OperatingDecision` 上游新增 ODO 显式对象，至少补这几个系统级枚举：

```text
ProactiveReason
OperatingDomain
OperatingObjectType
ArbitrationOutcome
```

并保证：

```text
Analysis Playbook -> ODO -> Arbitration -> Projection
```

而不是：

```text
Agent 文案 -> 前端拼接 -> 看起来像经营系统
```
