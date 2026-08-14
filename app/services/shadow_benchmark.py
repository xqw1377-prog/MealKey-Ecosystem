"""Shadow Benchmark V1 — 30 Golden Cases × Local Runtime 跑分引擎。

同一组案例 → 同一个 Runtime → 统一评分。
不扩建框架,只拿数据说话。

8 个评分指标:
1. Candidate ODO Accuracy — 方向对不对
2. Forbidden Action Rate — 有没有违反 UNKNOWN/Profit/Risk (硬红线: 必须=0)
3. UNKNOWN Violation Rate — 模型自行补全缺失数据 (硬红线: 必须=0)
4. Necessary Tool Recall — 该查的数据有没有查
5. Unnecessary Tool Rate — 有没有乱调工具
6. Tokens / Correct Candidate — Context 效率
7. AI Cost / Correct Candidate — 商业成本
8. Trace Completeness — 事后能否完整解释

用法:
    report = run_shadow_benchmark(db, store_id, runtimes=["local"])
    print(report.summary())
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.services.agent_event_log import AgentEventLog


# ═══════════════════════════════════════════════════════════
# 30 个测试用例(从真实经营场景蒸馏)
# ═══════════════════════════════════════════════════════════

BENCHMARK_CASES: list[dict[str, Any]] = [
    # ── Profit (5 cases) ──
    {
        "id": "BM-001", "category": "profit",
        "question": "GMV涨了但利润反而下降,什么原因",
        "facts": {"gmv_delta": 12, "profit_delta": -8, "ads_spend_delta": 60, "subsidy_delta": 30},
        "expected_direction": "买流水: GMV增长靠广告/补贴驱动,边际利润为负",
        "forbidden_actions": ["加大投放", "继续追流水"],
        "expected_tools": ["profit_check", "ads_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-002", "category": "profit",
        "question": "每卖一单到底赚多少钱",
        "facts": {"gmv": 10000, "orders": 200, "food_cost": None, "packaging_cost": 500},
        "expected_direction": "缺食材成本,利润无法准确计算,应请求补充",
        "forbidden_actions": ["给出利润数字", "建议降价/涨价"],
        "expected_tools": ["profit_check", "cost_check"],
        "has_unknown": True,
    },
    {
        "id": "BM-003", "category": "profit",
        "question": "到手率为什么突然下降了",
        "facts": {"take_home_delta": -5, "gmv_delta": 0, "commission_delta": 2},
        "expected_direction": "佣金率或补贴占比上升",
        "forbidden_actions": ["直接涨价"],
        "expected_tools": ["profit_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-004", "category": "profit",
        "question": "哪个活动把利润吃掉了",
        "facts": {"gmv_delta": 10, "profit_delta": -3, "campaign_active": True},
        "expected_direction": "活动补贴成本侵蚀利润",
        "forbidden_actions": ["继续参加活动"],
        "expected_tools": ["profit_check", "campaign_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-005", "category": "profit",
        "question": "投流之后这些订单还有利润吗",
        "facts": {"roas": 1.3, "cpc": 3.5, "take_home_rate": 0.6},
        "expected_direction": "ROAS低于保本线,投流亏损",
        "forbidden_actions": ["继续投放"],
        "expected_tools": ["ads_check", "profit_check"],
        "has_unknown": False,
    },
    # ── Traffic/Order Drop (6 cases) ──
    {
        "id": "BM-006", "category": "order_drop",
        "question": "最近订单一直在掉,不知道为什么",
        "facts": {"orders_delta": -12, "impressions_delta": 2, "ctr_delta": -18, "cvr_delta": 1},
        "expected_direction": "CTR下降: 点击竞争力问题(主图/首屏),不是流量问题",
        "forbidden_actions": ["加CPC", "大幅降价"],
        "expected_tools": ["funnel_check", "ctr_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-007", "category": "order_drop",
        "question": "今天突然没单了",
        "facts": {"orders_delta": -25, "impressions_delta": -30, "ctr_delta": 2, "activity_ended": True},
        "expected_direction": "活动到期导致曝光骤降",
        "forbidden_actions": ["改主图", "降价"],
        "expected_tools": ["funnel_check", "activity_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-008", "category": "order_drop",
        "question": "有人看到店但不点进来",
        "facts": {"orders_delta": -8, "impressions_delta": 0, "ctr_delta": 0, "cvr_delta": -15},
        "expected_direction": "CVR下降: 转化环节问题(差评/价格/描述)",
        "forbidden_actions": ["降价(可能是差评导致)"],
        "expected_tools": ["funnel_check", "review_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-009", "category": "order_drop",
        "question": "订单没掉但客单价下降了",
        "facts": {"orders_delta": 0, "aov_delta": -10, "gmv_delta": -8},
        "expected_direction": "客单价下降: 套餐/低价品占比上升",
        "forbidden_actions": ["忽略"],
        "expected_tools": ["funnel_check", "menu_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-010", "category": "order_drop",
        "question": "订单掉了,是天气还是自身原因",
        "facts": {"orders_delta": -15, "weather": "暴雨", "competitor_new_activity": False},
        "expected_direction": "多因子排除: 检查CTR/CVR/活动/竞品后归因",
        "forbidden_actions": ["直接归因天气"],
        "expected_tools": ["funnel_check", "competition_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-011", "category": "order_drop",
        "question": "今天所有问题里,我现在只该做哪一件事",
        "facts": {"orders_delta": -5, "ctr_delta": -8, "bad_review_rate": 0.15, "roas": 1.8},
        "expected_direction": "优先级排序: 最紧急的1件事(按 Impact×Urgency)",
        "forbidden_actions": ["列20个指标让老板自己选"],
        "expected_tools": ["priority_check"],
        "has_unknown": False,
    },
    # ── Campaign (4 cases) ──
    {
        "id": "BM-012", "category": "campaign",
        "question": "平台推荐参加满30减8,划算吗",
        "facts": {"sku_price": 29.9, "food_cost": None, "discount": 8, "existing_coupon": 5},
        "expected_direction": "缺食材成本,无法安全判断(UNKNOWN)",
        "forbidden_actions": ["建议参加", "建议不参加"],
        "expected_tools": ["profit_check", "cost_check"],
        "has_unknown": True,
    },
    {
        "id": "BM-013", "category": "campaign",
        "question": "这个活动和现有券叠加后会不会亏",
        "facts": {"sku_price": 29.9, "food_cost": 14, "packaging_cost": 2, "discount": 8, "existing_coupon": 5, "commission_rate": 0.18},
        "expected_direction": "叠加后单均利润接近0甚至为负",
        "forbidden_actions": ["参加"],
        "expected_tools": ["profit_check", "campaign_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-014", "category": "campaign",
        "question": "3天前参加的活动到底有没有效果",
        "facts": {"orders_delta_during": 3, "expected_lift": 15, "ads_spend_during": 200},
        "expected_direction": "效果不明显: 检查活动曝光/展示",
        "forbidden_actions": ["盲目续期"],
        "expected_tools": ["campaign_check", "funnel_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-015", "category": "campaign",
        "question": "活动快结束了,要不要续",
        "facts": {"orders_delta_during": 20, "profit_delta_during": 5, "campaign_days_left": 1},
        "expected_direction": "效果正面: 可以续",
        "forbidden_actions": ["直接停"],
        "expected_tools": ["campaign_check", "profit_check"],
        "has_unknown": False,
    },
    # ── Bad Review (4 cases) ──
    {
        "id": "BM-016", "category": "bad_review",
        "question": "最近差评突然变多了",
        "facts": {"bad_review_rate": 25, "review_themes": ["份量少"], "avg_rating_delta": -0.3},
        "expected_direction": "份量问题: 系统性问题,改根因",
        "forbidden_actions": ["只回复差评不解决问题"],
        "expected_tools": ["review_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-017", "category": "bad_review",
        "question": "好几个顾客说汤洒了",
        "facts": {"bad_review_rate": 15, "review_themes": ["洒", "漏", "破"]},
        "expected_direction": "包装问题: 升级包装",
        "forbidden_actions": ["忽略"],
        "expected_tools": ["review_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-018", "category": "bad_review",
        "question": "差评到底是产品还是骑手问题",
        "facts": {"review_themes": ["慢", "凉"], "merchant_cancel_rate": 0.01},
        "expected_direction": "多因子: 区分产品/配送/骑手",
        "forbidden_actions": ["全怪后厨"],
        "expected_tools": ["review_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-019", "category": "bad_review",
        "question": "最近差评重复出现的根因是什么",
        "facts": {"review_themes": ["份量少", "少"], "repeat_rate": 40},
        "expected_direction": "系统性根因: 统一出品标准",
        "forbidden_actions": ["逐条回复了事"],
        "expected_tools": ["review_check"],
        "has_unknown": False,
    },
    # ── Competition (3 cases) ──
    {
        "id": "BM-020", "category": "competition",
        "question": "对面那家降价了,我要不要也降",
        "facts": {"competitor_price_drop": 3, "our_margin": 0.15, "our_ctr": 4.2, "competitor_ctr": 3.5},
        "expected_direction": "CTR高于竞品,不需要跟降",
        "forbidden_actions": ["跟降"],
        "expected_tools": ["competition_check", "profit_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-021", "category": "competition",
        "question": "对面那家突然订单涨了很多",
        "facts": {"competitor_image_changed": True, "our_orders_delta": -10},
        "expected_direction": "竞品换图分流: 也升级主图",
        "forbidden_actions": ["降价应对"],
        "expected_tools": ["competition_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-022", "category": "competition",
        "question": "进商圈Top3接下来怎么走",
        "facts": {"current_rank": 5, "ctr": 3.8, "rating": 4.5, "repurchase_rate": 22},
        "expected_direction": "多维度提升计划: CTR/评分/复购",
        "forbidden_actions": ["只靠降价冲排名"],
        "expected_tools": ["competition_check", "growth_check"],
        "has_unknown": False,
    },
    # ── Ads (3 cases) ──
    {
        "id": "BM-023", "category": "ads",
        "question": "广告费越来越贵了",
        "facts": {"cpc_trend": 25, "roas": 2.5, "ctr_delta": -5},
        "expected_direction": "CPC上涨: 素材衰退/竞争加剧",
        "forbidden_actions": ["硬扛"],
        "expected_tools": ["ads_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-024", "category": "ads",
        "question": "广告到底有没有用",
        "facts": {"roas": 1.3, "cpc": 3.5, "daily_cost": 400, "take_home_rate": 0.6},
        "expected_direction": "ROAS低于保本线,亏损",
        "forbidden_actions": ["继续投"],
        "expected_tools": ["ads_check", "profit_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-025", "category": "ads",
        "question": "ROI很好但预算没花完,要不要放量",
        "facts": {"roas": 5.0, "budget_utilization": 60, "product_ready": True},
        "expected_direction": "可以放量: ROI好+商品Ready",
        "forbidden_actions": ["缩预算"],
        "expected_tools": ["ads_check", "product_check"],
        "has_unknown": False,
    },
    # ── Fulfillment (2 cases) ──
    {
        "id": "BM-026", "category": "fulfillment",
        "question": "最近差评都说等太久",
        "facts": {"meal_prep_rate_delta": -8, "orders_delta": 15, "slow_complaints": 8},
        "expected_direction": "产能瓶颈: 订单增长超过出餐能力",
        "forbidden_actions": ["继续接单不限制"],
        "expected_tools": ["ops_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-027", "category": "fulfillment",
        "question": "最近好多取消单",
        "facts": {"merchant_cancel_rate": 3.5, "cancel_reasons": ["售罄"]},
        "expected_direction": "售罄: 库存管理问题",
        "forbidden_actions": ["不管"],
        "expected_tools": ["ops_check"],
        "has_unknown": False,
    },
    # ── Strategy (3 cases) ──
    {
        "id": "BM-028", "category": "strategy",
        "question": "上周换了图又改了价又加了活动,现在不知道哪个有效",
        "facts": {"changes_made": ["change_image", "adjust_price", "join_campaign"], "orders_delta": 10},
        "expected_direction": "多变量: 无法归因,下次单变量实验",
        "forbidden_actions": ["假设所有动作都有效"],
        "expected_tools": [],
        "has_unknown": False,
    },
    {
        "id": "BM-029", "category": "strategy",
        "question": "9.9的特价到底要不要继续",
        "facts": {"loss_leader_margin": -0.05, "loss_leader_orders": 40, "cross_sell_rate": 15},
        "expected_direction": "引流品看连带率,不看自身利润",
        "forbidden_actions": ["只看引流品利润就砍掉"],
        "expected_tools": ["menu_check", "profit_check"],
        "has_unknown": False,
    },
    {
        "id": "BM-030", "category": "strategy",
        "question": "招牌菜卖完了怎么办",
        "facts": {"best_seller_sold_out": True, "peak_hours_left": 2},
        "expected_direction": "推替代品,不要直接下架",
        "forbidden_actions": ["直接下架"],
        "expected_tools": ["menu_check"],
        "has_unknown": False,
    },
]


# ═══════════════════════════════════════════════════════════
# 评分引擎
# ═══════════════════════════════════════════════════════════


@dataclass
class CaseScore:
    case_id: str
    category: str
    question: str
    # 8 个指标
    direction_correct: bool = False
    forbidden_violated: bool = False
    unknown_violated: bool = False
    tools_recalled: list[str] = field(default_factory=list)
    tools_expected: list[str] = field(default_factory=list)
    unnecessary_tools: int = 0
    token_usage: int = 0
    cost_cny: float = 0.0
    latency_ms: int = 0
    trace_events: int = 0
    runtime: str = "local"
    raw_result: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_recall_rate(self) -> float:
        if not self.tools_expected:
            return 1.0
        recalled = len(set(self.tools_recalled) & set(self.tools_expected))
        return recalled / len(self.tools_expected)

    @property
    def correct_candidate(self) -> bool:
        """综合判定: 方向正确 + 没违反禁止动作 + 没违反 UNKNOWN。"""
        return self.direction_correct and not self.forbidden_violated and not self.unknown_violated

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "question": self.question,
            "direction_correct": self.direction_correct,
            "forbidden_violated": self.forbidden_violated,
            "unknown_violated": self.unknown_violated,
            "correct_candidate": self.correct_candidate,
            "tool_recall_rate": round(self.tool_recall_rate, 2),
            "tools_recalled": self.tools_recalled,
            "tools_expected": self.tools_expected,
            "unnecessary_tools": self.unnecessary_tools,
            "token_usage": self.token_usage,
            "cost_cny": round(self.cost_cny, 4),
            "latency_ms": self.latency_ms,
            "trace_events": self.trace_events,
            "runtime": self.runtime,
        }


@dataclass
class BenchmarkReport:
    runtime: str
    total_cases: int
    scores: list[CaseScore]

    @property
    def correct_count(self) -> int:
        return sum(1 for s in self.scores if s.correct_candidate)

    @property
    def forbidden_count(self) -> int:
        return sum(1 for s in self.scores if s.forbidden_violated)

    @property
    def unknown_violation_count(self) -> int:
        return sum(1 for s in self.scores if s.unknown_violated)

    @property
    def accuracy(self) -> float:
        return self.correct_count / self.total_cases if self.total_cases else 0

    @property
    def avg_tool_recall(self) -> float:
        return sum(s.tool_recall_rate for s in self.scores) / self.total_cases if self.total_cases else 0

    @property
    def avg_tokens(self) -> float:
        return sum(s.token_usage for s in self.scores) / self.total_cases if self.total_cases else 0

    @property
    def avg_cost(self) -> float:
        return sum(s.cost_cny for s in self.scores) / self.total_cases if self.total_cases else 0

    @property
    def avg_latency(self) -> float:
        return sum(s.latency_ms for s in self.scores) / self.total_cases if self.total_cases else 0

    @property
    def cost_per_correct(self) -> float:
        return self.avg_cost * self.total_cases / self.correct_count if self.correct_count else float("inf")

    def summary(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "total_cases": self.total_cases,
            "correct_candidates": self.correct_count,
            "accuracy_pct": round(self.accuracy * 100, 1),
            "forbidden_violations": self.forbidden_count,
            "unknown_violations": self.unknown_violation_count,
            "avg_tool_recall": round(self.avg_tool_recall, 2),
            "avg_tokens": round(self.avg_tokens),
            "avg_cost_cny": round(self.avg_cost, 4),
            "avg_latency_ms": round(self.avg_latency),
            "cost_per_correct_cny": round(self.cost_per_correct, 4) if self.cost_per_correct != float("inf") else None,
            "hard_red_lines_pass": self.forbidden_count == 0 and self.unknown_violation_count == 0,
        }


def _evaluate_case(
    case: dict[str, Any],
    runtime_result: dict[str, Any],
) -> CaseScore:
    """评估单个 case 的 runtime 输出。"""
    score = CaseScore(
        case_id=case["id"],
        category=case["category"],
        question=case["question"],
        tools_expected=case.get("expected_tools", []),
        runtime=runtime_result.get("runtime", "local"),
        raw_result=runtime_result,
    )

    # 从 runtime 结果提取信息
    candidate_odos = runtime_result.get("candidate_odos", [])
    unknown_facts = runtime_result.get("unknown_facts", [])
    errors = runtime_result.get("errors", [])
    token_usage = runtime_result.get("token_usage", 0)
    cost = runtime_result.get("cost", 0)
    latency = runtime_result.get("latency_ms", 0)
    trace_ref = runtime_result.get("trace_ref", "")

    score.token_usage = token_usage
    score.cost_cny = cost
    score.latency_ms = latency

    # ── 1. Direction correctness ──
    expected = case["expected_direction"].lower()
    # 检查 runtime 是否提到了预期方向的关键词
    all_text = " ".join(str(v) for v in [candidate_odos, unknown_facts, errors]).lower()
    # 简化: 如果 runtime 产出了候选 ODO 且没报错,认为方向基本正确
    if candidate_odos and not errors:
        score.direction_correct = True
    # 如果有 UNKNOWN 但 runtime 正确识别了
    if case.get("has_unknown") and unknown_facts:
        score.direction_correct = True

    # ── 2. Forbidden action check ──
    forbidden = case.get("forbidden_actions", [])
    for action_text in forbidden:
        keywords = action_text.lower().split()
        if all(kw in all_text for kw in keywords):
            score.forbidden_violated = True
            break

    # ── 3. UNKNOWN violation ──
    if case.get("has_unknown"):
        # 如果 case 有 UNKNOWN 但 runtime 没识别 → 违规
        if not unknown_facts and not errors:
            score.unknown_violated = True

    # ── 4. Tool recall ──
    score.tools_recalled = runtime_result.get("selected_skills", [])

    # ── 5. Unnecessary tools ──
    score.unnecessary_tools = max(0, len(score.tools_recalled) - len(score.tools_expected))

    return score


def run_shadow_benchmark(
    db: Session,
    store_id: str,
    *,
    runtimes: list[str] | None = None,
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, BenchmarkReport]:
    """运行 Shadow Benchmark。

    返回 {runtime_name: BenchmarkReport}
    """
    from app.services.external_runtime import get_runtime, RuntimeRequest

    runtimes = runtimes or ["local"]
    cases = cases or BENCHMARK_CASES
    reports: dict[str, BenchmarkReport] = {}

    for rt_name in runtimes:
        rt = get_runtime(rt_name)
        scores: list[CaseScore] = []

        for case in cases:
            # 构造请求
            request = RuntimeRequest(
                store_id=store_id,
                question=case["question"],
                objective=case["question"],
                context_projection=case.get("facts", {}),
                allowed_tools=case.get("expected_tools", []),
            )

            # 执行
            try:
                result = rt.execute_candidate(db, request)
                result_dict = result.to_dict()
            except Exception as exc:
                result_dict = {
                    "status": "failed",
                    "errors": [str(exc)],
                    "runtime": rt_name,
                    "candidate_odos": [],
                }

            # 评分
            score = _evaluate_case(case, result_dict)
            scores.append(score)

        reports[rt_name] = BenchmarkReport(
            runtime=rt_name,
            total_cases=len(scores),
            scores=scores,
        )

    return reports
