"""MealKey Runtime V1 — 24h 状态机对象。

在现有 DailyOperatingPlan / OperatingBudget 基础上，
补齐运行时状态机、Clock Node 和 Transition contract。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.content_engine import AnalysisNodeKey, OperatingReason

# 8 个 Runtime 状态
RuntimeState = Literal[
    "night_learn",         # 当日经营结束、数据逐渐结算
    "daily_deep_review",   # 昨日核心数据完整，全面复盘
    "pre_open_check",      # 开店前准备度检查
    "pre_peak_decision",   # 午/晚高峰前 30-60 分钟
    "peak_protect",        # 进入高峰，实时守店
    "post_peak_review",    # 餐段结束后复盘
    "inter_peak_strategy", # 两个餐段之间
    "day_close",           # 营业结束
]

MealPeriod = Literal["breakfast", "lunch", "afternoon", "dinner", "late_night", "all_day", "none"]


class OperatingClockNode(BaseModel):
    """运行时节点定义：回答这个状态允许系统做什么。"""

    state: RuntimeState
    node: AnalysisNodeKey
    meal_period: MealPeriod = "none"
    purpose: str = ""
    allowed_triggers: list[OperatingReason] = Field(default_factory=list)
    allow_owner_interrupt: bool = False
    protect_mode: bool = False
    expected_outputs: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)


class RuntimeTransition(BaseModel):
    """状态机转换定义。"""

    from_state: RuntimeState
    to_state: RuntimeState
    condition: str
    note: str = ""


class DailyOperatingState(BaseModel):
    """门店此刻的运行态快照。"""

    current_state: RuntimeState
    current_node: AnalysisNodeKey
    current_meal_period: MealPeriod = "none"
    active_goal: str = ""
    protect_mode: bool = False
    owner_interrupts_used: int = 0
    pending_trigger_reasons: list[OperatingReason] = Field(default_factory=list)
    active_threads: list[str] = Field(default_factory=list)
    summary: str = ""


class RuntimeStateMachine(BaseModel):
    """一整天的运行时制度。"""

    nodes: list[OperatingClockNode] = Field(default_factory=list)
    transitions: list[RuntimeTransition] = Field(default_factory=list)


class DailyOperatingPlan(BaseModel):
    """AI 店长今天脑子里的"工作计划"（材料 §12）。

    Deep Review 完成后生成，不需要完整展示给老板。
    """

    date: str = ""  # YYYY-MM-DD
    core_goal: str = ""  # 今日核心目标（来自 Goal + preferences）
    focus_meal_period: str = ""  # 今日重点餐段（lunch/dinner/all）
    active_experiment: str = ""  # 当前主实验
    protected_metrics: list[str] = Field(default_factory=list)  # 需要保护的指标
    auto_exec_budget: dict[str, Any] = Field(default_factory=dict)  # 允许 AI 自主执行的预算
    active_threads: list[str] = Field(default_factory=list)  # 需要继续的 WorkThread
    check_points: list[str] = Field(default_factory=list)  # 今日关键检查节点（时间列表）
    current_runtime_state: Optional[RuntimeState] = None
    current_meal_period: MealPeriod = "none"


class OperatingBudget(BaseModel):
    """AI 自主经营的授权边界（材料 §13）。

    老板可以自然语言修改："广告500以内以后你自己看着办" → 系统直接改变此对象。
    """

    ads_daily_limit_cny: Optional[float] = None  # 每日广告上限（None=未授权）
    activity_profit_floor_pct: Optional[float] = None  # 活动不能让贡献利润率低于此值
    price_auto_adjust_range: float = 1.0  # 商品价格 ±¥ 自动测试范围
    review_auto_reply: bool = True  # 普通评价全部自动
    user_compensation_limit_cny: float = 0.0  # 用户补偿上限（0=不自动）
    menu_sort_auto: bool = True  # 菜单排序可自动
    menu_delete_needs_confirm: bool = True  # 删除 SKU 需确认

    def can_auto_execute(self, action_type: str, *, spend: float = 0) -> bool:
        """判断某个动作是否在 AI 自主执行权限内。"""
        if action_type in ("batch_reply_negative_reviews", "publish_service_reply_scripts") and self.review_auto_reply:
            return True
        if action_type in ("boost_hero_item_ads", "shift_ads_to_high_cvr_item"):
            return self.ads_daily_limit_cny is not None and spend <= self.ads_daily_limit_cny
        if action_type in ("change_title",):
            return True  # 标题低风险
        if action_type in ("menu_cleanup",) and self.menu_delete_needs_confirm:
            return False
        if action_type == "menu_sort" and self.menu_sort_auto:
            return True
        return False  # 默认不自动


class ContextTransferCheck(BaseModel):
    """跨餐段策略转移检查（材料 §7）。

    午餐实验有效，不能默认晚餐也有效。
    """

    source_meal_period: str = ""  # 午餐
    target_meal_period: str = ""  # 晚餐
    transferable: bool = False
    reason: str = ""
    # 检查维度
    same_audience: Optional[bool] = None
    same_price_band: Optional[bool] = None
    same_hero_sku: Optional[bool] = None
    same_competition: Optional[bool] = None


def check_context_transfer(
    source: str,  # lunch / dinner
    target: str,
    *,
    store_state: Any = None,
) -> ContextTransferCheck:
    """检查一个餐段的策略能不能复制到另一个餐段。

    默认不复制——午餐人群 ≠ 晚餐人群，必须独立验证。
    """
    # V1 保守策略：不同餐段默认不转移
    if source == target:
        return ContextTransferCheck(
            source_meal_period=source,
            target_meal_period=target,
            transferable=True,
            reason="同一餐段，无需转移检查。",
        )

    return ContextTransferCheck(
        source_meal_period=source,
        target_meal_period=target,
        transferable=False,
        reason=f"{source}人群 ≠ {target}人群，午餐实验有效不能默认晚餐有效。需要独立验证。",
        same_audience=False,
    )


def default_runtime_state_machine() -> RuntimeStateMachine:
    """返回 Content Engine V1 默认运行时状态机。"""
    return RuntimeStateMachine(
        nodes=[
            OperatingClockNode(
                state="night_learn",
                node="night_settlement",
                meal_period="none",
                purpose="回收实验、沉淀结果、更新记忆",
                allowed_triggers=["RESULT", "CONTINUATION"],
                allow_owner_interrupt=False,
                expected_outputs=["result_odo", "memory_update", "thread_update"],
                forbidden_actions=["ask_owner_now", "push_strategy_frontstage"],
            ),
            OperatingClockNode(
                state="daily_deep_review",
                node="night_settlement",
                meal_period="none",
                purpose="完成昨日全链路深复盘并生成今日工作计划",
                allowed_triggers=["RESULT", "ANOMALY", "GOAL_DEVIATION", "CONTINUATION", "OPPORTUNITY"],
                allow_owner_interrupt=False,
                expected_outputs=["candidate_odo", "daily_operating_plan", "strategy_memory_update"],
                forbidden_actions=["multi_suggestion_frontstage"],
            ),
            OperatingClockNode(
                state="pre_open_check",
                node="morning_readiness",
                meal_period="all_day",
                purpose="判断今天有没有值得主动处理的事情",
                allowed_triggers=["TIME", "ANOMALY", "CONTINUATION"],
                allow_owner_interrupt=True,
                expected_outputs=["readiness_odo", "protect_odo"],
                forbidden_actions=["heavy_strategy_change"],
            ),
            OperatingClockNode(
                state="pre_peak_decision",
                node="pre_lunch_nba",
                meal_period="lunch",
                purpose="只找一个最值得做的动作",
                allowed_triggers=["TIME", "ANOMALY", "OPPORTUNITY", "GOAL_DEVIATION"],
                allow_owner_interrupt=True,
                expected_outputs=["next_best_action"],
                forbidden_actions=["multiple_owner_questions"],
            ),
            OperatingClockNode(
                state="peak_protect",
                node="lunch_protect",
                meal_period="lunch",
                purpose="Protect Mode，只护店，不引入新变量",
                allowed_triggers=["TIME", "ANOMALY"],
                allow_owner_interrupt=False,
                protect_mode=True,
                expected_outputs=["incident_odo", "stop_loss_action"],
                forbidden_actions=["new_experiment", "low_confidence_menu_change", "heavy_strategy_change"],
            ),
            OperatingClockNode(
                state="post_peak_review",
                node="post_lunch_review",
                meal_period="lunch",
                purpose="解释这餐发生了什么，并决定是否需要小范围调整",
                allowed_triggers=["RESULT", "ANOMALY", "GOAL_DEVIATION"],
                allow_owner_interrupt=False,
                expected_outputs=["meal_review_odo", "micro_adjustment_candidate"],
                forbidden_actions=["final_strategic_conclusion"],
            ),
            OperatingClockNode(
                state="inter_peak_strategy",
                node="pre_dinner_nba",
                meal_period="afternoon",
                purpose="判断午餐经验是否值得迁移到晚餐",
                allowed_triggers=["CONTINUATION", "RESULT", "OPPORTUNITY"],
                allow_owner_interrupt=True,
                expected_outputs=["transfer_check", "dinner_candidate_odo"],
                forbidden_actions=["blind_strategy_copy"],
            ),
            OperatingClockNode(
                state="day_close",
                node="weekly_strategy",
                meal_period="none",
                purpose="轻复盘并清点明早前必须处理的事情",
                allowed_triggers=["CONTINUATION", "TIME"],
                allow_owner_interrupt=False,
                expected_outputs=["closing_summary", "overnight_watch_items"],
                forbidden_actions=["deep_root_cause_analysis"],
            ),
        ],
        transitions=[
            RuntimeTransition(from_state="night_learn", to_state="daily_deep_review", condition="yesterday_data_complete"),
            RuntimeTransition(from_state="daily_deep_review", to_state="pre_open_check", condition="new_business_day_started"),
            RuntimeTransition(from_state="pre_open_check", to_state="pre_peak_decision", condition="peak_window_approaching"),
            RuntimeTransition(from_state="pre_peak_decision", to_state="peak_protect", condition="meal_period_started"),
            RuntimeTransition(from_state="peak_protect", to_state="post_peak_review", condition="meal_period_finished"),
            RuntimeTransition(from_state="post_peak_review", to_state="inter_peak_strategy", condition="next_peak_exists"),
            RuntimeTransition(from_state="inter_peak_strategy", to_state="pre_peak_decision", condition="next_peak_window_approaching"),
            RuntimeTransition(from_state="post_peak_review", to_state="day_close", condition="no_next_peak_today"),
            RuntimeTransition(from_state="day_close", to_state="night_learn", condition="settlement_window_open"),
        ],
    )


def build_daily_operating_state(
    *,
    current_state: RuntimeState,
    active_goal: str = "",
    active_threads: Optional[list[str]] = None,
    owner_interrupts_used: int = 0,
    pending_trigger_reasons: Optional[list[OperatingReason]] = None,
) -> DailyOperatingState:
    """根据状态构建当前运行态快照。"""
    machine = default_runtime_state_machine()
    node = next((item for item in machine.nodes if item.state == current_state), None)
    return DailyOperatingState(
        current_state=current_state,
        current_node=node.node if node else "morning_readiness",
        current_meal_period=node.meal_period if node else "none",
        active_goal=active_goal,
        protect_mode=bool(node.protect_mode) if node else False,
        owner_interrupts_used=owner_interrupts_used,
        pending_trigger_reasons=pending_trigger_reasons or (node.allowed_triggers if node else []),
        active_threads=active_threads or [],
        summary=node.purpose if node else "",
    )
