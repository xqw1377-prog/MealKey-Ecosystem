# MealKey Content Engine V1

## 目标

冻结 MealKey 从“漂亮 Demo”走向“真正 AI 外卖店长”的内容系统。  
本规格先停止 UI 打磨，优先定义 AI 大脑如何决定：

1. 什么时候分析什么
2. 什么发现值得进入经营系统
3. 该调用哪个外卖经营域
4. AI 自己做、找老板、还是继续观察
5. 左栏、中栏、右栏分别投影什么
6. 最后如何验证结果并写入记忆

## 核心链路

```text
Merchant Understanding Engine
        ↓
Store State
        ↓
Analysis Playbook
        ↓
Signal
        ↓
Event
        ↓
Diagnosis
        ↓
Candidate Decision
        ↓
Proactive Operating Engine
  6 Reasons × 8 Domains
        ↓
Operating Decision Object
        ↓
Permission / Risk Gate
   ├─ AI做
   ├─ 找老板
   └─ 只观察
        ↓
WorkThread / Action
        ↓
Experiment
        ↓
Result
        ↓
Memory
```

## 设计原则

### 1. 13 个 Agent 退到系统下面

Agent 是技能，不是产品表面结构。  
主系统只认统一对象、统一节奏、统一仲裁。

### 2. 所有内容必须落进 8 个经营域

| domain | 含义 |
| --- | --- |
| `platform` | 平台连接、营业、履约、售罄、IM、平台健康 |
| `product` | 菜单、SKU、图片、标题、定价、线上装修 |
| `competition` | 商圈、竞品、搜索/单品/团购排名 |
| `traffic` | 官方活动、补贴、CPC、广告、流量 |
| `profit` | GMV、实收、到手率、成本、贡献利润 |
| `customer` | 用户画像、频率、RFM、复购、召回 |
| `reputation` | 评价、回复、差评、申诉、评分 |
| `store_growth` | 一店多开、线上店定位、SKU 隔离、矩阵增长 |

### 3. 所有主动内容必须来自 6 种理由

`TIME / ANOMALY / CONTINUATION / OPPORTUNITY / GOAL_DEVIATION / RESULT`

关键不是“右栏有哪些模块”，而是：

```text
为什么现在发生
×
发生在哪个经营域
×
当前店铺状态 / 目标 / WorkThread
```

### 4. 三栏来自同一个 ODO

- 左栏：`WorkThreadProjection`
- 中栏：`GuideDirective`
- 右栏：`ProactiveEventProjection`

禁止三栏各写各的文案。

## V1 交付物

### 1. Merchant Information Checklist

定义每类经营信息：

- 来源优先级
- 第一次真正有价值的时机
- 缺失是否阻塞
- 缺失时是推断、Safe Mode 还是当场询问

见 [merchant_information_checklist_v1.md](file:///C:/Users/xqw13/MealKey%20Ecosystem/mealky-ai-backend/docs/merchant_information_checklist_v1.md)

### 2. Analysis Playbook

定义 AI 的经营作息表：

- 什么时间跑什么分析
- 每个节点允许看哪些信号
- 每个节点只允许产出什么类型的 ODO

见 [analysis_playbook_v1.md](file:///C:/Users/xqw13/MealKey%20Ecosystem/mealky-ai-backend/docs/analysis_playbook_v1.md)

### 3. ODO Schema + Arbitration Rules

定义统一经营判断对象，以及 POIE 的仲裁出口。

见 [odo_schema_and_arbitration_v1.md](file:///C:/Users/xqw13/MealKey%20Ecosystem/mealky-ai-backend/docs/odo_schema_and_arbitration_v1.md)

### 4. Runtime Operating State Machine

定义 MealKey 一天 24 小时到底处于什么状态、每个状态允许什么 Trigger、什么时候允许打扰老板。

见 [runtime_operating_state_machine_v1.md](file:///C:/Users/xqw13/MealKey%20Ecosystem/mealky-ai-backend/docs/runtime_operating_state_machine_v1.md)

### 5. Runtime Backend Contract

定义 Runtime V1 的数据库对象、API Contract、事件 Schema。

见 [runtime_v1_backend_contract.md](file:///C:/Users/xqw13/MealKey%20Ecosystem/mealky-ai-backend/docs/runtime_v1_backend_contract.md)

### 6. DeerFlow Integration POC

定义 DeerFlow 只作为 Agent Harness 接入时，MealKey 和 DeerFlow 的边界、桥接接口与第一条 Golden Path 验证范围。

见 [deerflow_integration_poc_v1.md](file:///C:/Users/xqw13/MealKey%20Ecosystem/mealky-ai-backend/docs/deerflow_integration_poc_v1.md)

## V1 不做什么

1. 不继续手写右栏 Demo 文案
2. 不继续新增首页视觉状态
3. 不把 8 个经营域暴露成用户导航
4. 不要求老板在启动时填完一整套资料
5. 不允许 Agent 绕过 ODO 直接推内容到前台

## 推荐工程落点

### Phase 1

- 把 8 个 `domain` 升级为系统级枚举
- 把 `reason × domain` 前推到事件生成，而不是前端投影时猜
- 给 `OperatingDecision` / `ProactiveEvent` 增加 ODO 所需字段

### Phase 2

- 建 `Merchant Information Checklist` 的结构化存储
- 建 `Analysis Playbook` 调度层
- 让 POIE 从“卡片仲裁”升级为“ODO 仲裁”

### Phase 3

- 建内容模拟器：输入店铺状态，自动产出左/中/右三栏内容
- 用模拟器验收内容系统，而不是先盯 UI

### Service Split

- `context-service`：商家/门店上下文、信息缺口、Ask Engine
- `analysis-service`：Analysis Playbook、Daily Operating State、Clock Node 调度
- `decision-service`：ODO、Impact、Profit Gate、Risk Gate
- `poie-service`：6 Trigger、Arbitration、Next Best Action
- `work-service`：Goal、WorkThread、Action、Experiment、Result、Memory

## 验收标准

给定任一店铺状态快照，系统应能稳定回答：

1. 现在为什么值得产生这条内容？
2. 这条内容属于哪个经营域？
3. 这是 AI 自己做、找老板、还是继续观察？
4. 左栏、中栏、右栏是否来自同一个 ODO？
5. 结果出来后是否能回写 Memory？
