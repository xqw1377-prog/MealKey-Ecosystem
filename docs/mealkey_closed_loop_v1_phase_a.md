# MealKey Closed Loop V1 — Phase A

## 目标

Phase A 只做一件事：

> 让一个真实经营事项从第一次被 MealKey 发现开始，始终围绕同一个 `work_thread_id` 持续推进，直到进入 `WAITING_RESULT`。

这不是接口收集阶段，也不是 Agent 扩张阶段。

Phase A 的交付是：

- 同一事项唯一身份
- 显式 WorkThread 状态机
- 统一 ActionSpec / Action Registry
- 至少跑通 1 条 Golden Flow 到 `WAITING_RESULT`

## Golden Flow

Phase A 冻结的第一条 Golden Flow：

```text
Signal
↓
ODO
↓
WorkThread
↓
Guide
↓
ActionSpec
↓
Approval / Information
↓
Ready To Execute
↓
Executed
↓
Observing
↓
Waiting Result
```

第一批动作选型：

1. `CHANGE_PRODUCT_IMAGE`
2. `CHANGE_PRODUCT_TITLE`
3. `REPLY_REVIEW`

其中第一条“主图优化”作为主验证路径。

## 研发票

### CLV1-A01：统一三栏与对话到同一个 `work_thread_id`

#### 目标

让左栏 WorkThread 卡片、中栏 Guide、右栏 ProactiveEvent、首页对话补充、上传附件，全部能追溯并回到同一个 `work_thread_id`。

#### 要解决的问题

当前风险是：

- 左栏 / 中栏 / 右栏各自持有不同对象
- 点击后容易重新生成一段新对话
- 附件和补充信息可能绕过原事项，产生新线程

#### 研发实现

后端：

- 给以下对象补齐或校验 `work_thread_id`
  - ODO
  - Guide
  - ProactiveEvent
  - Conversation message
  - Attachment
  - Approval
- 增加 Thread Re-entry Rule：
  - 何时必须回到既有线程
  - 何时允许新建线程

前端：

- 左栏卡片点击进入已有 Thread，而不是生成新问答
- 中栏 Guide 的动作、按钮、补充回答全部写回原 Thread
- 右栏 Event 点击进入同一 Thread 上下文
- 拖卡片到 AI 对话栏时，优先附着原 `work_thread_id`

#### 验收

- 同一事项从左 / 中 / 右任一入口进入，都显示同一 Thread 状态
- 上传附件后，不会新建平行线程
- 继续问一句“那你现在做到哪了”，系统回的是原事项进度，而不是新建一段泛对话

#### 建议涉及文件

- `app/api/routes_runtime.py`
- `app/api/routes_workspace.py`
- `app/static/js/04-home.js`
- `app/static/js/06-actions.js`
- `app/static/js/07-events.js`

### CLV1-A02：实现显式 WorkThread State Machine

#### 目标

建立统一的经营事项状态机，由业务逻辑驱动状态变化，UI 只消费状态。

#### 冻结状态

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

#### 要解决的问题

当前风险是：

- 前端靠 `if/else` 和 body class 猜业务状态
- “生成执行包”容易被误判成“已执行”
- 同一事项没有单一可信阶段

#### 研发实现

后端：

- 定义 `WorkThread.status` 和合法迁移
- 定义每种迁移动作的触发条件
- 在 Approval / Execution / Observe / Result 写回时显式改状态

前端：

- 左栏按状态分组投影：
  - 需要你
  - 正在进行
  - 等待结果
  - 最近完成
- 中栏根据 Thread 状态选择渲染：
  - 问信息
  - 求确认
  - 展示执行包
  - 展示观察窗口

#### 验收

- `READY_TO_EXECUTE` 和 `EXECUTED` 严格区分
- 执行后事项从“需要你”移动到“等待结果”或“正在进行”
- UI 不再通过散乱 body class 推断业务阶段

#### 建议涉及文件

- `app/schemas/runtime_objects.py`
- `app/models/runtime_v1.py`
- `app/api/routes_workspace.py`
- `app/static/js/00-state.js`
- `app/static/js/04-home.js`

### CLV1-A03：统一 ActionSpec + Action Registry

#### 目标

把“建议动作”升级为统一 ActionSpec，并建立第一版 Action Registry。

#### 第一批 Action Type

```text
CHANGE_PRODUCT_IMAGE
CHANGE_PRODUCT_TITLE
REPLY_REVIEW
```

#### 每个 Action Type 必须定义

- `required_context`
- `input_schema`
- `risk_level`
- `approval_requirement`
- `execution_method`
- `rollback_method`
- `success_metrics`
- `default_observation_window`

#### 要解决的问题

当前风险是：

- 不同 Agent / Route 各自描述动作
- “动作”只是文本建议，不能驱动状态机
- 后续从人工执行切到平台执行时会整体返工

#### 研发实现

后端：

- 新建统一 ActionSpec schema
- 新建 Action Registry
- 所有进入 Guide 的推荐动作，都先落 ActionSpec

前端：

- 中栏只消费 ActionSpec，不再消费松散文本建议
- “复制执行”“上传资料”“确认执行”等操作围绕 ActionSpec 渲染

#### 验收

- 同一类型动作的 UI 和执行逻辑来自同一个注册表定义
- `CHANGE_PRODUCT_IMAGE`、`CHANGE_PRODUCT_TITLE`、`REPLY_REVIEW` 都能产出结构化 ActionSpec
- ActionSpec 可支持“人工执行”与“平台执行”两种 executor，而不改变对象本身

#### 建议涉及文件

- `app/schemas/agents.py`
- `app/schemas/runtime_objects.py`
- `app/services/action_executor.py`
- `app/static/js/04-home.js`
- `app/static/js/06-actions.js`

### CLV1-A04：跑通“主图优化”闭环到 `WAITING_RESULT`

#### 目标

把“主图优化”做成 Phase A 第一条完整 Golden Flow。

#### 冻结路径

```text
异常发现
→ 诊断
→ 生成 brief
→ 请求真实商品图
→ 生成/选择主图
→ 老板确认
→ 人工平台执行
→ 标记已执行
→ 进入观察
→ Waiting Result
```

#### 要解决的问题

当前风险是：

- 主图建议只是一个建议卡
- 生成素材和真正执行之间没有状态边界
- 执行后没有进入稳定的观察态

#### 研发实现

后端：

- 让 ODO 产出 `CHANGE_PRODUCT_IMAGE` ActionSpec
- 为“请求真实商品图”“确认图片份量真实性”定义信息缺口
- 为“已执行”与“观察窗口”建立显式状态写回

前端：

- 中栏展示主图优化 Guide
- 允许用户上传实物图并写回原 Thread
- 支持“已在平台执行”确认按钮
- 执行后切换到观察视图，展示成功指标与回看时间

#### 验收

- 用户从任一入口进入“主图优化”都回到同一 Thread
- 上传图片不会开启新事项
- 点击“已执行”后线程进入 `OBSERVING / WAITING_RESULT`
- 左栏状态变化正确，右栏继续解释当前等待点

#### 建议涉及文件

- `app/api/routes_store.py`
- `app/api/routes_workspace.py`
- `app/services/storefront_agent.py`
- `app/services/action_executor.py`
- `app/static/js/04-home.js`
- `app/static/js/06-actions.js`

## 建议新增两张辅助票

### CLV1-A05：Thread Re-entry Rule

定义以下输入何时必须回到已有 Thread：

- 首页继续问答
- 左中右栏再次点击
- 上传附件
- 语音转文字
- Approval / Information 回答

验收：

- 本应继续原事项的输入，`Same Thread Continuity Rate` 明显提升

### CLV1-A06：Unknown Truth Contract

所有关键经营字段统一带：

```text
value
source
confidence
last_updated
```

缺失即 `UNKNOWN`。

这张票是 Phase B 的前置清理票，避免后面 Profit Truth 返工。

## 验收总口径

Phase A 不按“完成多少接口”验收，只按 Golden Flow 验收。

必须同时满足：

1. 一个事项从首页第一次出现后，无论点击左、中、右哪个入口，始终是同一个事项
2. 用户完成动作后，这件事会真正进入下一状态，而不是重新生成一段聊天
3. 至少一条动作路径从 ODO 跑到 `WAITING_RESULT`

## 不应进入本阶段的需求

以下需求全部后排：

- 新 Agent
- 新一级产品模块
- 多店 BI
- 多品类扩张
- 自动调价
- 自动预算
- 自动参加平台活动
- 全量平台写回

## 开发顺序建议

建议按下面顺序执行：

1. `CLV1-A01`
2. `CLV1-A02`
3. `CLV1-A03`
4. `CLV1-A05`
5. `CLV1-A04`
6. `CLV1-A06`

其中：

- `A01 + A02` 先把“同一事项能活下去”做真
- `A03` 解决动作对象统一
- `A04` 提供第一条可见闭环
- `A05/A06` 用来降低后续返工
