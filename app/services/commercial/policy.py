"""MealKey Commercial OS + Competitive Strategy V1 — 冻结政策。

定价数字不变。2026-08-13 战略收口：
平台是执行场，MealKey 是商家的经营控制层。
护城河是 Business Truth + Outcome Data + Strategy Memory，不是「我们会执行」。
V1 不加利润增量分成，也不把白标 ERP/POS 当主路径。
"""

from __future__ import annotations

from dataclasses import dataclass


VERSION = "commercial-os-v1.2"
COMPETITIVE_STRATEGY_VERSION = "competitive-strategy-v1"
STRATEGY_FREEZE = "2026-08-13"
FX_USD_CNY_BUDGET = 7.3  # 内部预算汇率，不是预测汇率
AI_MARKUP = 1.30
SUBSCRIPTION_FLOOR_CNY = 200.0  # 等效月价红线，低于此须人工审批
LIST_MONTHLY_CNY = 300.0
QUARTERLY_MONTHS_PAID = 2.75  # 付 2.75 用 3，约 8.3% off
QUARTERLY_MONTHS_USED = 3
ANNUAL_MONTHS_PAID = 10
ANNUAL_MONTHS_USED = 12
WALLET_TOPUP_TIERS_CNY = (200.0, 500.0, 1000.0)
WALLET_LOW_CNY = 30.0  # 客户只看人民币，低于此提醒充值
AI_STORE_BUDGET_ACTUAL_CNY = 150.0  # 成本控制线，不是收费额度
AI_THROTTLE_RATIO = 0.80
ACQUISITION_AUDIT_CAP_CNY = 5.0
BASE_CASE_TOKENS_PER_STORE = 4_500_000
TOKEN_INPUT_SHARE = 0.85
TOKEN_CACHED_INPUT_SHARE = 0.50  # 占 input
MODEL_MIX = {"luna": 0.60, "terra": 0.30, "sol": 0.10}

# OpenAI 官方示意价：USD / million tokens  (input, cached_input, output)
MODEL_USD_PER_M = {
    "luna": (1.00, 0.10, 6.00),
    "terra": (2.50, 0.25, 15.00),
    "sol": (5.00, 0.50, 30.00),
}

# (min_stores, monthly_cny, annual_cny_per_store)
VOLUME_TIERS: tuple[tuple[int, float, float], ...] = (
    (300, 250.0, 2500.0),
    (100, 260.0, 2600.0),
    (50, 270.0, 2700.0),
    (20, 280.0, 2800.0),
    (5, 290.0, 2900.0),
    (1, 300.0, 3000.0),
)

PARTNER_Y1_BASE = 0.50
# (min_new_qualified_stores, extra_on_top_of_base)
PARTNER_Y1_BONUS: tuple[tuple[int, float], ...] = (
    (300, 0.20),
    (100, 0.15),
    (50, 0.10),
    (20, 0.05),
    (1, 0.00),
)
PARTNER_Y2 = 0.30
PARTNER_Y3 = 0.20
PARTNER_TAIL = 0.10
QUALIFY_DAYS = 30
BONUS_CONFIRM_DAYS = 90  # 90-Day Qualified Store：档位奖励只认活过 90 天的店

POSITIONING_LINE = "一个站在商家这一边、跨平台经营并持续从结果里学习的 AI 外卖店长。"
POSITIONING_SHORT = "AI 外卖店长"
SYSTEM_POSITIONING = "Merchant Operating Control Plane"
COMPETITIVE_ONE_LINER = "平台是执行场，MealKey 是商家的经营控制层。"
BOSS_QUESTION = "站在这家商户整体利润和长期经营目标上，现在整盘生意最该做什么？"
MOAT_LINE = "MealKey 的护城河不是 AI，也不是某一个平台接口，而是商家拥有的跨平台经营事实、持续积累的经营动作结果，以及由这些结果训练出来的经营策略记忆。"
MOAT_STACK = ("business_truth", "outcome_data", "strategy_memory")
STRATEGIC_SEAT = "merchant_operating_control_plane"  # 不是 MealKey vs 美团
COMPANY_GOAL_PAID_STORES = 20
COMPANY_GOAL_VERIFIED_LOOPS = 100
COMPANY_GOAL_MEMORY_CHANGED = 10
COMPANY_GOAL_NATURAL_RENEWALS = 1
# 100 条闭环是 PMF Evidence Seed，不是护城河
LOOP_LADDER = (
    {"from": 0, "to": 100, "name": "pmf_evidence_seed", "means": "证明系统不是假的"},
    {"from": 100, "to": 1000, "name": "playbook_calibration", "means": "开始校准 Playbook"},
    {"from": 1000, "to": 10000, "name": "strategy_memory_value", "means": "开始形成 Strategy Memory 价值"},
    {"from": 10000, "to": None, "name": "outcome_network", "means": "开始形成数据网络效应；更大规模后才谈难复制的 Outcome Dataset"},
)
BATTLEFIELDS = (
    {"key": "in_platform_execution", "label": "场内数据与执行", "stance": "够用，不争全面第一"},
    {"key": "cross_platform_pnl", "label": "跨平台整盘生意", "stance": "必须领先"},
    {"key": "closed_loop_memory", "label": "经营闭环与记忆", "stance": "核心领先区"},
    {"key": "distribution", "label": "商业牵引 / 分发", "stance": "当前必须补齐"},
    {"key": "cost_of_intelligence", "label": "单位智能成本", "stance": "规模化生死线"},
)
# 不追求场内全面第一，但必须达到 Closed Loop 所需的最低执行深度
MIN_CLOSED_LOOP_ACTIONS = ("change_title", "change_main_image", "reply_ordinary_reviews")
CLOSED_LOOP_CHAIN = ("Decision", "ActionSpec", "Platform Action", "Read Back", "Result")
NOT_COMPETING_IN_PLATFORM = (
    "CPC底层实时竞价基础设施",
    "IM基础设施",
    "平台内活动系统",
    "配送调度",
)
COST_OF_INTELLIGENCE_STACK = (
    "确定性计算优先",
    "POIE先过滤",
    "Context Projection",
    "Model Router",
    "Memory Retrieve而不是Dump",
    "Token真实计费",
)
MUST_SHIP = (
    {"item": "真实成本/订单/广告/评价/活动导入", "adds": "Business Truth"},
    {"item": "真实 Action 执行 / 人工确认 / Read Back", "adds": "Outcome Data"},
    {"item": "Experiment / Attribution / Memory BOOST", "adds": "Strategy Memory"},
    {"item": "Partner / Result Card / Audit / 连锁扩店", "adds": "Distribution"},
)
DEFER_SHIP = (
    "第14个 Agent",
    "更漂亮的 BI Dashboard",
    "覆盖所有平台的所有写接口",
    "复杂 CRM 大而全",
    "移动端重新造一整套 App",
)
FREEZE_SENTENCES = (
    "不跟平台争谁更懂平台，争谁更懂老板整盘生意。",
    "跨平台是进入市场的楔子，不是长期护城河。",
    "Business Truth 是决策基础，Outcome Data 是核心资产，Strategy Memory 是复利。",
    "Agent、Runtime、长程任务、单平台自动化都不是长期壁垒。",
    "第一阶段不追求功能最多，而追求最多真实 Closed Loop。",
    "架构领先只有经过付费门店、真实动作和真实结果之后，才会转化成公司壁垒。",
)
CONTROL_PLANE_BELOW = (
    "美团",
    "淘宝闪购",
    "京东",
    "抖音",
    "POS",
    "ERP",
    "成本数据",
    "老板输入",
    "竞品数据",
)
PROFIT_SHARE_V1 = False
WHITE_LABEL_PRIMARY = False

SLA_PROMISES = (
    "每天有人看",
    "重要问题有人判断",
    "该做什么有人推动",
    "做完以后有人回来检查",
    "成功失败都会成为下一次经验",
)

BILLING_STAGES = (
    {"stage": "V1", "name": "Subscription", "sells": "持续经营责任", "includes": ["base_subscription", "ai_compute"]},
    {"stage": "V2", "name": "Subscription + Execution", "sells": "权限成熟后的执行托管", "includes": ["base_subscription", "ai_compute", "managed_execution"]},
    {"stage": "V3", "name": "Optional Outcome Share", "sells": "Attribution 被证明以后的增值", "includes": ["optional_result_share"]},
)

GROWTH_PRIORITY = (
    {"route": "¥300 AI店长 + Partner分销", "priority": "P0", "note": "第一验证路线，掌握用户关系"},
    {"route": "人工辅助的 Closed Loop 服务", "priority": "P0", "note": "冷启动必须，藏在产品后面"},
    {"route": "跨平台统一经营", "priority": "P0", "note": "进入楔子，不是最终资产"},
    {"route": "执行托管", "priority": "P1", "note": "权限成熟后扩大价值"},
    {"route": "Embedded / API", "priority": "P1/P2", "note": "跑出真实数据后再谈，不当白标引擎"},
    {"route": "Result / 利润增量分成", "priority": "P2", "note": "Attribution 成熟以前不做计费基础"},
    {"route": "Strategy / Data 产品", "priority": "P3", "note": "足够门店和 Outcome Data 以后"},
)

TWENTY_STORE_COHORTS = (
    {"key": "direct", "stores": 5, "tests": "自己卖需要多少成本"},
    {"key": "referral", "stores": 5, "tests": "Result 有没有自然传播力"},
    {"key": "partner", "stores": 5, "tests": "高分润能不能驱动销售"},
    {"key": "chain_expansion", "stores": 5, "tests": "1 店 → N 店是否发生"},
)

DATA_LADDER = (
    "official_api",
    "service_provider_api",
    "export_csv_excel",
    "report_screenshot",
    "merchant_confirmation",
)

CUSTOMER_BILL_CATEGORIES = (
    "日常经营分析",
    "异常诊断",
    "AI对话",
    "图片/内容处理",
    "其他",
)


@dataclass(frozen=True)
class VolumePrice:
    min_stores: int
    monthly_cny: float
    annual_cny: float

    @property
    def annual_equiv_monthly(self) -> float:
        return round(self.annual_cny / ANNUAL_MONTHS_USED, 2)


def volume_price(active_stores: int) -> VolumePrice:
    count = max(int(active_stores or 0), 0)
    for min_stores, monthly, annual in VOLUME_TIERS:
        if count >= min_stores:
            return VolumePrice(min_stores, monthly, annual)
    return VolumePrice(1, LIST_MONTHLY_CNY, LIST_MONTHLY_CNY * ANNUAL_MONTHS_PAID)


def y1_partner_rate(new_qualified_stores: int) -> float:
    count = max(int(new_qualified_stores or 0), 0)
    extra = 0.0
    for threshold, bonus in PARTNER_Y1_BONUS:
        if count >= threshold:
            extra = bonus
            break
    return round(PARTNER_Y1_BASE + extra, 2)


def lifecycle_partner_rate(months_since_first_paid: int, y1_rate: float) -> float:
    months = max(int(months_since_first_paid or 0), 0)
    if months < 12:
        return round(float(y1_rate), 2)
    if months < 24:
        return PARTNER_Y2
    if months < 36:
        return PARTNER_Y3
    return PARTNER_TAIL


def policy_snapshot() -> dict:
    return {
        "version": VERSION,
        "competitive_strategy_version": COMPETITIVE_STRATEGY_VERSION,
        "strategy_freeze": STRATEGY_FREEZE,
        "positioning": POSITIONING_LINE,
        "positioning_short": POSITIONING_SHORT,
        "system_positioning": SYSTEM_POSITIONING,
        "competitive_one_liner": COMPETITIVE_ONE_LINER,
        "boss_question": BOSS_QUESTION,
        "moat": MOAT_LINE,
        "moat_stack": list(MOAT_STACK),
        "strategic_seat": STRATEGIC_SEAT,
        "company_goal": {
            "paid_stores": COMPANY_GOAL_PAID_STORES,
            "verified_closed_loops": COMPANY_GOAL_VERIFIED_LOOPS,
            "memory_changed_decisions": COMPANY_GOAL_MEMORY_CHANGED,
            "natural_renewals": COMPANY_GOAL_NATURAL_RENEWALS,
            "ai_cost_per_store": "observed",
            "label": "20 Paid Stores / 100 Verified Closed Loops / 10 Memory-Changed Decisions / 1 Natural Renewal / real AI Cost per Store",
            "note": "100 条闭环是 PMF Evidence Seed，不是护城河。",
        },
        "loop_ladder": list(LOOP_LADDER),
        "battlefields": list(BATTLEFIELDS),
        "min_closed_loop_actions": list(MIN_CLOSED_LOOP_ACTIONS),
        "closed_loop_chain": list(CLOSED_LOOP_CHAIN),
        "not_competing_in_platform": list(NOT_COMPETING_IN_PLATFORM),
        "cost_of_intelligence_stack": list(COST_OF_INTELLIGENCE_STACK),
        "must_ship": list(MUST_SHIP),
        "defer_ship": list(DEFER_SHIP),
        "freeze_sentences": list(FREEZE_SENTENCES),
        "control_plane_below": list(CONTROL_PLANE_BELOW),
        "sla": list(SLA_PROMISES),
        "billing_stages": list(BILLING_STAGES),
        "growth_priority": list(GROWTH_PRIORITY),
        "twenty_store_cohorts": list(TWENTY_STORE_COHORTS),
        "data_ladder": list(DATA_LADDER),
        "list_monthly_cny": LIST_MONTHLY_CNY,
        "floor_equiv_monthly_cny": SUBSCRIPTION_FLOOR_CNY,
        "quarterly_months_paid": QUARTERLY_MONTHS_PAID,
        "quarterly_months_used": QUARTERLY_MONTHS_USED,
        "annual_months_paid": ANNUAL_MONTHS_PAID,
        "annual_months_used": ANNUAL_MONTHS_USED,
        "wallet_topup_tiers_cny": list(WALLET_TOPUP_TIERS_CNY),
        "wallet_low_cny": WALLET_LOW_CNY,
        "ai_markup": AI_MARKUP,
        "ai_store_budget_actual_cny": AI_STORE_BUDGET_ACTUAL_CNY,
        "acquisition_audit_cap_cny": ACQUISITION_AUDIT_CAP_CNY,
        "partner_y1_base": PARTNER_Y1_BASE,
        "partner_y1_max": PARTNER_Y1_BASE + PARTNER_Y1_BONUS[0][1],
        "partner_y2": PARTNER_Y2,
        "partner_y3": PARTNER_Y3,
        "partner_tail": PARTNER_TAIL,
        "qualify_days": QUALIFY_DAYS,
        "bonus_confirm_days": BONUS_CONFIRM_DAYS,
        "commission_base": "base_subscription_collected",
        "commission_excludes": [
            "ai_compute",
            "third_party_api",
            "image_speech_search_passthrough",
            "custom_development",
            "refunds",
        ],
        "multi_level_commission": False,
        "profit_share_v1": PROFIT_SHARE_V1,
        "white_label_primary": WHITE_LABEL_PRIMARY,
        "not_a_moat": [
            "platform_will_only_suggest",
            "agent_runtime",
            "catpaw_or_deerflow_parity",
            "single_platform_oauth",
            "white_label_erp_pos",
            "verified_closed_loops_100",
            "in_platform_execution_first",
        ],
    }
