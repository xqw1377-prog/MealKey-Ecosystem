# RESEARCH-TE-01 — MT-LIFT & Incremental Profit Review

**类型：P1a Research Spike**  
**状态：REVIEW COMPLETE + SEMANTICS LANDED（2026-08-17）**  
Incremental Result 可落库，证据等级门禁已接线；**未**下载 MT-LIFT，**未**改生产归因主路径。  
**不抢 P0：** DATA-AS-01 的工程资源优先。本文件只定语义，不训练模型，不改生产归因代码。

来源：

- 数据集：[MTDJDSP/MT-LIFT](https://github.com/MTDJDSP/MT-LIFT)
- 对应论文：Huang et al., *Entire Chain Uplift Modeling…* (ECUP), [arXiv:2402.03379](https://arxiv.org/abs/2402.03379)
- 方向旁证（非本数据集）：Zhang et al., *FunnelCausalNet*, [arXiv:2608.11675](https://arxiv.org/abs/2608.11675)
- 许可默认规则：[GitHub Docs — Licensing a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)

语义合同（Research Zone，未接线生产）：[`app/schemas/incremental_result.py`](../app/schemas/incremental_result.py)

---

## 一句话结论

MT-LIFT 值得学的是 **「相对不作为，这个动作多产生了多少结果」**，不是「这家店今天该发 5 元券」。

MealKey V2 **吸收 `Incremental Result` 语义**；**不吸收** MT-LIFT 权重、匿名特征、优惠券决策模型。  
Uplift **只许做 Candidate Action 的排序证据，不许做经营授权。**

```text
P0   DATA-AS-01     真实 Business Truth 连续性
P1a  RESEARCH-TE-01 本文件：Incremental / Treatment Effect 语义
P1b  PLATFORM-SB-01 可控平台跑 Action → Read Back → Result
P2   Growth Action Primitive
```

先弄清「怎样算真正有增量」，再造 Sandbox，再扩大 `COUPON / REACTIVATE`。否则低质量前后对比会写进 Strategy Memory。

---

## 五个审阅问题

### 1. LICENSE — Research Zone only

| 事实 | 依据 |
| --- | --- |
| 仓库根目录基本只有 README，无 LICENSE 文件 | [MT-LIFT](https://github.com/MTDJDSP/MT-LIFT) |
| GitHub API `license: null` | 2026-08-17 核验 |
| 公开可看 / 可 fork ≠ 可复制、修改、再分发、商用 | [GitHub Docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) |
| 论文称数据集 released for future research | [arXiv:2402.03379](https://arxiv.org/abs/2402.03379) — **研究意图，不是商用许可** |

**冻结：**

> 在获得明确 License / 数据使用条款之前，MT-LIFT **只进入 Research Zone**。  
> **不得**进入 MealKey 商用训练集、生产特征库、可再分发数据资产。  
> **不得**把该数据训出的模型权重部署进生产。  
> 下载本身也须先向作者 / 美团确认条款；在此之前默认 **不下载、不入库**。

### 2. CAUSAL STRUCTURE — RCT 能教什么

公开描述（README + ECUP）：

- 美团 App 外卖优惠券营销、约 **5,541,842** 条、**99** 个匿名特征 `f0–f98`
- **RCT**：treatment 随机分配，降低混杂
- `treatment ∈ {0,1,2,3,4}`（多臂；0 视为 control）
- 标签：`click`、`conversion`（impression → click → conversion 全链）
- 用途明确包含 **uplift modeling**

ECUP 用 Neyman–Rubin 潜在结果定义 ITE：

```text
τ(x) = E[Y | t=k, x] − E[Y | t=0, x]
```

并指出 **chain-bias**：只看 CVR uplift、忽略 click 段，可能把决策做反。

**MealKey 应学到的结构（不是模型）：**

| 概念 | 含义 |
| --- | --- |
| Treatment / Control | 做了动作 vs 什么都不做（或更弱动作） |
| ATE | 群体平均增量 |
| CATE | 在某类店 / 某类客群下的增量 |
| Chain | 曝光 → 点击 → 转化 各段 uplift 可以反向 |
| Incremental ≠ Observed | 自然流量本来也会涨 |

当前仓库归因是前后对比：

```text
lift_pct = (observed − baseline) / baseline
```

见 `app/services/experiment_attribution.py` 与 `Experiment.baseline_value / observed_value / lift_pct`。  
这回答的是「做完之后变了多少」，**不是**「相对不作为多了多少」。

### 3. FIELD SEMANTICS — 为什么不能当优惠券模型

公开 schema 只有：`f0–f98`、`treatment`、`click`、`conversion`。

**没有公开：**

- 99 个特征的业务语义
- 券面额 / 门槛 / 商家补贴 / 平台补贴
- 客付、商家实收、贡献利润
- 门店、SKU、商圈可解释标签

因此：

```text
能教：怎样估计 treatment effect
不能教：这家牛肉饭店今天该发哪一档券
不能直接优化：Incremental Contribution Profit
```

FunnelCausalNet（[arXiv:2608.11675](https://arxiv.org/abs/2608.11675)）把 conversion uplift、条件客单、补贴感知 ROI 连在一起，**只作为方向旁证**：MealKey 最终目标应是 **Incremental Contribution Profit**，不能停在 Conversion Lift。该文用的不是 MT-LIFT，不能把其结论当成本数据集的字段能力。

### 4. MEALKEY MAPPING

```text
现在（V1，保留）
before → action → after → observed lift → Strategy Memory.lesson

V2 增加（不替换 V1）
treatment vs control
→ Incremental Result
→ Memory.incremental_lesson
→ 仅作为 Ranking Signal
→ 仍过 Profit Gate / Permission
→ 真实门店实验
→ Verified Result
```

| 现有对象 | V2 增量 | 不做 |
| --- | --- | --- |
| `Experiment.lift_pct` | 旁路增加 `IncrementalResult` | 立刻改掉 V1 前后对比 |
| `attribution_quality` | 增加 `evidence_grade` | 用 MT-LIFT 分数覆盖质量 |
| `StrategyMemoryItem.lesson` | 增加 incremental 字段 | 用匿名 CATE 当 lesson |
| Candidate Action 排序 | 以后可吃 **已验证** incremental | 用研究模型 AUTO 发券 |
| Profit / Permission Gate | **不吃** uplift 分数 | — |

Strategy Memory 句式升级：

```text
以前：发券后订单涨了 12%。
以后：对这类店 / 这类客群，该券相对不发，约 +4% 增量订单，贡献利润 -2%。
```

没有 control、没有成本、没有利润口径时，**只许写 observed，不许冒充 incremental。**

### 5. PRODUCTION GATE

```text
Research Model（含任何 MT-LIFT 训练物）
        ↓
Treatment Effect Estimate
        ↓
Candidate Action Ranking Signal     ← 最高到达这里，且须 L1+
        ↓
MealKey Profit Gate                 ← 不读 uplift 授权
        ↓
Risk / Permission
        ↓
Real Store Experiment
        ↓
Verified Result → Strategy Memory
```

**禁止：**

```text
model predicts uplift = 8%  →  AUTO 发券
```

| 证据等级 | 来源 | 可做什么 |
| --- | --- | --- |
| `L0_RESEARCH` | MT-LIFT / 论文复现 | 只写研究笔记；**零**生产影响 |
| `L1_STORE_CONTRAST` | 本店可解释的 treatment/control（含 holdout / 同期未动作对照） | 写入 Incremental Result；Memory 标 `incremental` |
| `L2_CROSS_STORE` | 多店复核且口径一致 | 可轻微影响 Candidate Action **排序** |
| `L3_PROFIT_VERIFIED` | 增量订单 + 真实成本 + 贡献利润对账通过 | 仍须过 Profit / Permission；**仍禁止**只凭模型 AUTO |

Uplift 是排序证据，不是经营授权。

---

## V2 吸收 / 暂不做

### 进入 MealKey V2 语义（先定义，后实现）

1. **`Incremental Result`**：与 observed lift 并存。
2. Experiment 可声明 `treatment` / `control` / `observation_window` / `treatment_cost`。
3. 主结果优先：**增量贡献利润**；没有利润口径时该字段 `UNKNOWN`，不得用转化率冒充。
4. Strategy Memory 区分 `observed_lesson` 与 `incremental_lesson`。
5. 证据等级门禁：未达 `L1` 的估计不得进排序。

### 暂时不做

- 完整 causal ML 平台（S/T/X-learner、CATE 服务、预算分配器）
- 下载 / 训练 / 部署 MT-LIFT
- 把 uplift 分数接入 Profit Gate / Permission / 自动写回
- 先扩 `COUPON / REACTIVATE / MEMBER_REWARD` 却仍只用前后对比写 Memory
- PLATFORM-SB-01 之前的「增长中心」

---

## 对后续项目的约束

**DATA-AS-01（P0）**  
Incremental Profit 依赖真实 `merchant_revenue` / 成本。没有连续 Business Truth，本 Spike 的语义无法落地。

**PLATFORM-SB-01（P1b）**  
Sandbox 必须能造 **treatment 店 vs control 店（或 holdout）**，不能只造 “action 前后”。否则测的仍是 observed lift。

**Growth Action Primitive（P2）**  
每个增长动作必须带：`treatment_cost`、`primary_outcome`、`profit_guard`、`attribution_method`。缺 control 设计的动作，Memory 只能记 observed。

---

## 评审记录

| 项 | 决定 |
| --- | --- |
| LICENSE | Research Zone；无明确条款前不下载、不训练、不商用、不再分发 |
| CAUSAL STRUCTURE | 吸收 treatment/control 与 Incremental ≠ Observed |
| FIELD SEMANTICS | 不能当优惠券决策模型；无 Profit Truth 字段 |
| MEALKEY MAPPING | V1 前后对比保留；V2 旁路 Incremental Result |
| PRODUCTION GATE | Uplift ≠ 授权；L0 零生产；L2 才可影响排序 |

## 三层结果（不得混写）

```text
ObservedResult      订单 +12%          ranking 权重 0.25
AttributedResult    与该 Action 相关 ≈ +7%   0.55
IncrementalResult   相对 control ≈ +4%       1.00（须 L2+ 才可影响排序）
```

Strategy Memory 可以同时知道三者；**ranking 权重必须不同**。没有 control 不得把 observed 写成 incremental。

## MT-LIFT 许可通过条件

Architecture Research **可以继续**（论文、语义、证据等级）。**Data Use 暂停**，直到书面确认：

| 条款 | 必须明确 |
| --- | --- |
| 允许下载 | 是/否 |
| 允许内部研究 | 是/否 |
| 允许模型训练 | 是/否 |
| 允许商业产品研发 | **关键** |
| 允许训练后模型商用 | **关键** |
| 允许衍生统计结果 | 是/否 |
| 允许再分发原始数据 | 不必须（没有也没关系） |
| 需要 attribution | 条件 |
| 使用期限 | 条件 |
| 数据删除要求 | 条件 |

未通过前：不下载、不训练、不微调、不进商用语料、不生产 serving、不再分发。

**本 Spike 架构审阅完成。** Sandbox 已冻结。DATA-AS-01 等美团授权店。见 [`docs/phase_external_evidence_wait.md`](phase_external_evidence_wait.md)。
