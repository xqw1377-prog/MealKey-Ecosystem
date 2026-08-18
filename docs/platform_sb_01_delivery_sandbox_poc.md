# PLATFORM-SB-01 Delivery Sandbox POC

**类型：P1b**  
**状态：FROZEN（2026-08-17）** — 使命完成：改标题 → Read Back → treatment−control → L0。  
**PLATFORM-SB-01 = integration test infrastructure，不是第二个外卖产品。**  
禁止再加：价格 / 优惠券 / 广告 / 会员 / 评价 / 复杂订单模拟。除非某条真实 Closed Loop 测试明确需要。  
**不抢 P0：** DATA-AS-01 1×1 授权店仍是生产数据主线。本 Sandbox 只服务 **闭环集成测试**，产出不得冒充真实 Business Truth。

不并入 `weitianpaxi/sky_take_out` / Enatega 代码。吸收的是「自控外卖世界」：菜单、订单、评价、写回、读回。苍穹外卖若使用，只降格为可选外部 Test Platform，经同一 `MockPlatformConnector` 契约接入。

依赖：[`docs/research_te_01_mt_lift_incremental_profit.md`](research_te_01_mt_lift_incremental_profit.md)  
合同：[`app/schemas/platform_sandbox.py`](../app/schemas/platform_sandbox.py) · [`app/services/platform_sandbox.py`](../app/services/platform_sandbox.py)

---

## 只回答一个问题

> MealKey 能否在**完全可控**的平台里跑通  
> `ActionSpec → Permission → Execute → Platform State Change → Read Back → 模拟后续订单 → Observed Result + Incremental Result（相对 control）`  
> 并且 **不把 Sandbox 数据写成生产高置信 Truth**？

## 范围（锁死）

```text
1 Sandbox World
×
Twin stores: treatment + control
×
Read + Write（仅 allowlist）
×
Synthetic demand
```

第一版只测现有写回白名单，不扩增长动作：

```text
change_title / CHANGE_PRODUCT_TITLE
change_main_image / CHANGE_PRODUCT_IMAGE
reply_ordinary_reviews / REPLY_REVIEW
```

外加测试注入（不是商家动作）：

```text
inject_orders
inject_review
simulate_tick
```

## 明确不做

| 禁止项 |
| --- |
| 并入开源外卖主系统 |
| 对接真实美团 / 闪购写回 |
| 自动发券 / 改价 / 差评回复 |
| 把 Sandbox 结果写入生产 Strategy Memory 当 L1+ incremental |
| 用 Sandbox uplift 过 Profit / Permission Gate |
| 先做 CRM / COUPON Primitive（P2） |
| 完整外卖商城、骑手、支付 |

---

## 为什么必须是 Twin，不能只做前后对比

TE-01 已冻结：Sandbox 若只能 “action 前后”，测的仍是 observed lift。

```text
World
├─ control store    不执行 Action
└─ treatment store  执行 Action
        ↓
同一 demand shock / simulate_tick
        ↓
incremental_orders = treatment − control
```

`IncrementalResult.evidence_grade` 在本 POC **固定 `L0_RESEARCH`**（合成世界）。  
可验证链路与口径，**不可**影响生产排序或授权。

---

## 最小接口

```text
SandboxWorld
  spawn_twin(world_id) → {treatment_store_id, control_store_id}

SandboxConnector   # 测试平台，不是生产 Connector
  apply(store_id, ActionSpec) → WriteReceipt
  read_back(store_id, op) → PlatformState
  inject(store_id, scenario)
  simulate_tick(world_id, hours)

contrast(world_id) → IncrementalResult   # 永远 L0
```

场景注入（制造可被 POIE 看见的变化）：

```text
order_drop / order_rise
sku_stockout
negative_review
price_changed          # 仅注入观察，第一版不开放改价写回
```

## 黄金路径（验收）

```text
注入 treatment+control 午餐订单下降
        ↓
MealKey 生成 Candidate Action（改标题，已有 Registry）
        ↓
Permission（测试店自动通过或显式 fixture）
        ↓
只对 treatment 执行写回
        ↓
Read Back 标题已变；control 未变
        ↓
simulate_tick：两边同一需求过程，treatment 因标题状态可有不同订单
        ↓
Observed lift（treatment 前后）与 Incremental（treatment−control）同时算出
        ↓
Incremental 标 L0，may_authorize_action = false
```

**可以不接真实 POIE 引擎。** 第一版用 fixture 事件 + 现有 ActionSpec 即可。成功标准是闭环可测，不是「AI 说对了」。

---

## Gate

| 指标 | Gate |
| --- | ---: |
| 未把 Sandbox 标成生产 Truth | **0 次违规** |
| control 被误执行 Action | **0** |
| Read Back 与写入不一致仍算成功 | **0** |
| Incremental 证据等级 | 必须 `L0_RESEARCH` |
| `may_authorize_action` | **false** |
| Twin 对比可重复（同 seed） | **是** |
| 真实平台副作用 | **0** |

结果分类（同 DATA-AS-01，不改其合同）：

| 结果 | 意义 |
| --- | --- |
| `PASS` | 黄金路径稳定，可接第二条路径（换主图） |
| `PASS_WITH_LIMITS` | 写回/读回可用，增量模拟过粗 |
| `REWORK` | 仍只能做前后对比 |
| `STOP` | Sandbox 与生产状态分不开 |

---

## 与现网的边界

| 层 | Sandbox | 生产 |
| --- | --- | --- |
| Connector | `acquisition_mode` 不适用；`source=sandbox` | DATA-AS-01 梯子 |
| Write | 内存 / 可选外部 Test Platform | `platform_write` allowlist + 真连接器 |
| Fact | 合成 Evidence | Reconciliation 后才升 Truth |
| Memory | 测试夹具，可丢弃 | 仅真实店 Verified Result |

现有 `platform_connectors.post_platform_write(mode="mock")` 是单店演示写回，**不是** Twin Sandbox。本 POC 另建测试世界，不替换 mock 生产演示。

---

## 执行顺序

1. 本 POC 合同 + 内存 Twin 骨架 ← **当前**
2. 黄金路径自动化测试（改标题）
3. 可选：把苍穹外卖降格为外部 Test Platform（同一契约）
4. 再开 P2 Growth Action Primitive

DATA-AS-01 一旦有授权测试店，工程时间立刻回到 1×1 Collector。
