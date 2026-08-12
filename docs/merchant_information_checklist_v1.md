# Merchant Information Checklist V1

## 目标

定义 MealKey 在什么时机必须知道什么信息。  
重点不是“资料什么时候填完”，而是“这个信息第一次真正有价值是在什么时候”。

## 统一字段模型

每个信息字段都必须带这些元数据：

| 字段 | 说明 |
| --- | --- |
| `key` | 稳定字段 ID |
| `label` | 内部可读名称 |
| `domain` | 归属经营域 |
| `source_priority` | 来源优先级 |
| `first_required_at` | 第一次真正需要它的节点 |
| `used_by` | 会影响哪些分析 / ODO / Action |
| `blocking_mode` | `none` / `safe_mode` / `block_action` / `block_startup` |
| `ask_policy` | `never` / `infer_then_confirm` / `ask_when_blocking` / `ask_contextual` |
| `stale_after` | 多久过期 |
| `fallback` | 缺失时系统怎么退化 |

## 来源优先级

```text
platform / system
> historical inference
> experiment result
> merchant explicit answer
```

冲突时，以老板最新明确回答为最高优先。

## 阶段定义

| 阶段 | 含义 |
| --- | --- |
| `startup` | 启动前最低可运营状态 |
| `contextual` | 某个经营动作真正需要时再问 |
| `daily` | 当日临时上下文 |
| `strategic` | 周 / 月级经营决策 |

## 主清单

| key | domain | first_required_at | source_priority | blocking_mode | ask_policy | fallback |
| --- | --- | --- | --- | --- | --- | --- |
| `platform_connection` | `platform` | `startup` | 平台授权 | `block_startup` | `ask_when_blocking` | 停在连接引导 |
| `business_goal` | `profit` | `startup` | 老板回答 | `safe_mode` | `ask_when_blocking` | 临时按 `balanced` |
| `priority_style` | `profit` | `startup` | 老板回答 | `safe_mode` | `ask_when_blocking` | 按平衡策略低置信运行 |
| `low_risk_auto_permission` | `reputation` | `startup` | 老板授权 | `none` | `ask_when_blocking` | 默认仅建议不自动执行 |
| `profit_floor_rate` | `profit` | 活动 / 投流 / 改价前 | 老板 / 历史推断 | `safe_mode` | `ask_when_blocking` | 禁止利润敏感动作自动执行 |
| `hero_item_floor_price` | `profit` | 商品活动 / 平台补贴前 | 老板 / 成本推断 | `block_action` | `ask_when_blocking` | 阻塞该 SKU 的改价/活动 |
| `item_cost_map` | `profit` | 利润核算 / 活动 ROI 前 | ERP / 老板 / 推断 | `safe_mode` | `ask_contextual` | 用粗利润近似，不做自动激进动作 |
| `lunch_capacity_per_hour` | `platform` | 午高峰放量前 | 老板 / 历史推断 | `block_action` | `ask_when_blocking` | 不自动放大投流 |
| `ads_daily_budget_limit` | `traffic` | 自动调投流前 | 老板授权 | `block_action` | `ask_when_blocking` | 超限动作一律需确认 |
| `review_reply_permission` | `reputation` | 评价自动回复前 | 老板授权 | `block_action` | `ask_contextual` | 好评可建议，差评不自动 |
| `compensation_policy` | `reputation` | 客诉补偿前 | 老板授权 | `block_action` | `ask_contextual` | 仅生成建议，不自动赔付 |
| `competitor_focus` | `competition` | 重点竞品分析前 | 老板 / AI 推断 | `none` | `infer_then_confirm` | 按商圈高威胁竞品默认排序 |
| `real_food_photo` | `product` | 主图真实性校验前 | 老板上传 | `block_action` | `ask_contextual` | 不自动上线真实性不明的新图 |
| `weekend_strategy_bias` | `traffic` | 周末策略切换前 | 老板 / 历史推断 | `none` | `ask_contextual` | 按工作日策略保守运行 |
| `multi_store_intent` | `store_growth` | 第二线上店机会出现时 | 老板 / 行为推断 | `none` | `ask_contextual` | 不提前问，不触发扩张方案 |

## 日常临时信息

这些不是 onboarding 字段，只有在当下决策真的依赖时才问：

| key | 触发场景 | blocking_mode | 处理方式 |
| --- | --- | --- | --- |
| `today_stockout_reason` | 核心 SKU 异常售罄 | `block_action` | 先看平台状态，判断不了再问 |
| `today_staffing_shortage` | 午高峰履约/接单异常 | `block_action` | 仅在准备放量或保护模式时询问 |
| `today_equipment_issue` | 出餐异常 / 临时闭店 | `block_action` | 事故级场景再问 |
| `today_special_hours` | 特殊营业安排 | `none` | 平台无数据时才确认 |
| `today_cost_spike` | 原料临时涨价 | `block_action` | 仅当影响活动/改价判断时问 |

## 询问规则

### 1. Ask Only What AI Cannot Know

先级永远是：

1. 先读平台
2. 再读历史/实验
3. 再做推断
4. 最后才问老板

### 2. Ask Only When It Becomes Valuable

不允许为了“资料完整”集中问。  
只允许在它第一次影响经营判断时问一句。

### 3. One Question, One Decision

一次只问一句，而且必须能直接解锁当前节点。

## 典型例子

### 例 1：活动前问底价

```text
场景：
平台午餐补贴值得参加

缺失：
hero_item_floor_price

结果：
中栏只问“黑椒牛肉饭最低到手多少钱你可以接受？”
而不是要求老板去设置中心补全成本表
```

### 例 2：投流前问额度

```text
场景：
午高峰前 ROI 稳定，AI 想放大预算

缺失：
ads_daily_budget_limit

结果：
询问“以后每天 ¥300 以内的预算调整，我可以自己处理吗？”
```

### 例 3：主图前问真实性

```text
场景：
商品 CTR 异常，AI 已生成候选主图

缺失：
real_food_photo / 真实性确认

结果：
询问“这张图和实际份量一致吗？”
```

## 实现建议

### 存储对象

建议新增统一 `ContextFact`：

```json
{
  "key": "ads_daily_budget_limit",
  "value": 300,
  "source": "merchant",
  "confidence": 1.0,
  "first_required_at": "pre_lunch_nba",
  "blocking_mode": "block_action",
  "updated_at": "2026-08-12T10:25:00+08:00"
}
```

### V1 工程动作

1. 把 MUE 当前 gap 题库映射到这张表
2. 给每个字段加 `blocking_mode`
3. 让 Playbook / ODO 在运行时声明 `required_context_keys`
4. 缺失字段统一经 Checklist 判定：推断、Safe Mode、还是发起 GuideDirective
