"""Decision Core API — 活动测算 + 利润诊断端点。

让老板能直接在对话里说"帮我算算这个活动要不要参加"，
系统调用 Decision Core 引擎，返回结构化决策。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.decision_core import (
    CampaignDecision,
    CampaignRule,
    ProfitDiagnosisResult,
)
from app.services.decision_core import (
    calculate_campaign,
    diagnose_profit_change,
)

router = APIRouter()


class CampaignCalcRequest(BaseModel):
    """活动测算请求。"""
    rule: CampaignRule
    sku_id: Optional[str] = None
    sku_name: str = ""
    sku_price: float = 0
    food_cost: Optional[float] = None
    packaging_cost: Optional[float] = None
    platform_commission_rate: float = 0.18
    delivery_fee_borne: float = 0.0
    avg_daily_orders: int = 100
    expected_lift_pct: float = 10.0
    profit_floor: float = 0.17
    existing_discounts: Optional[list[dict]] = None
    capacity_per_hour: Optional[int] = None


class ProfitDiagnosisRequest(BaseModel):
    """利润诊断请求。"""
    current: dict[str, Optional[float]]
    baseline: dict[str, Optional[float]]
    orders_current: Optional[int] = None
    orders_baseline: Optional[int] = None


@router.post("/stores/{store_id}/campaign/calculate")
def calc_campaign(
    store_id: str,
    request: CampaignCalcRequest,
    db: Session = Depends(get_db),
):
    """活动测算——输入活动规则 + SKU 成本，输出 GREEN/YELLOW/RED/BLACK 决策。

    这是 MealKey 第一个真正的经营决策引擎。
    老板点"同意测试"后，后端自动生成 Recommendation + Experiment + WorkThread。
    """
    decision = calculate_campaign(
        request.rule,
        sku_price=request.sku_price,
        food_cost=request.food_cost,
        packaging_cost=request.packaging_cost,
        platform_commission_rate=request.platform_commission_rate,
        delivery_fee_borne=request.delivery_fee_borne,
        avg_daily_orders=request.avg_daily_orders,
        expected_lift_pct=request.expected_lift_pct,
        profit_floor=request.profit_floor,
        existing_discounts=request.existing_discounts,
        capacity_per_hour=request.capacity_per_hour,
    )
    return {"decision": decision.model_dump(mode="json")}


@router.post("/stores/{store_id}/campaign/decide-and-execute")
def campaign_decide_and_execute(
    store_id: str,
    request: CampaignCalcRequest,
    db: Session = Depends(get_db),
):
    """活动测算 + 自动进入闭环。

    GREEN/YELLOW → 自动生成 Recommendation(proposed) + Experiment(pending) + WorkThread
    RED/BLACK → 不生成动作，只返回结论
    """
    decision = calculate_campaign(
        request.rule,
        sku_price=request.sku_price,
        food_cost=request.food_cost,
        packaging_cost=request.packaging_cost,
        platform_commission_rate=request.platform_commission_rate,
        delivery_fee_borne=request.delivery_fee_borne,
        avg_daily_orders=request.avg_daily_orders,
        expected_lift_pct=request.expected_lift_pct,
        profit_floor=request.profit_floor,
        existing_discounts=request.existing_discounts,
        capacity_per_hour=request.capacity_per_hour,
    )

    result: dict[str, Any] = {"decision": decision.model_dump(mode="json")}

    # GREEN/YELLOW → 进入闭环
    if decision.verdict in ("GREEN", "YELLOW"):
        import json
        from app.models.ohre import Recommendation, Experiment
        from app.services.thread_engine import create_thread, update_thread_progress

        test_days = decision.test_duration_days or request.rule.applicable_days
        action_type = "join_lunch_campaign" if "午餐" in (request.rule.campaign_name or "") else "match_competitor_promo"

        # 1. 先创建经营线程(贯穿闭环的对象)
        thread = create_thread(
            db,
            store_id=store_id,
            title=f"活动测试：{request.rule.campaign_name}",
            goal_text=decision.strategy,
        )

        # 2. 创建 Recommendation,绑定 work_thread_id
        rec = Recommendation(
            store_id=store_id,
            work_thread_id=thread.id,
            scope="store",
            object_ref=f"store:{store_id}",
            action_type=action_type,
            expected_metric="orders",
            expected_lift_pct_low=decision.calc.expected_order_lift_pct,
            expected_lift_pct_high=decision.calc.expected_order_lift_pct,
            window_hours=test_days * 24,
            confidence=decision.confidence,
            status="proposed",
            content_json=json.dumps({
                "source": "decision_core_campaign",
                "campaign_name": request.rule.campaign_name,
                "verdict": decision.verdict,
                "strategy": decision.strategy,
                "calc": decision.calc.model_dump(mode="json"),
                "guardrail_metrics": decision.guardrail_metrics,
                "stop_conditions": decision.stop_conditions,
                "expected_total_profit_delta": decision.calc.expected_total_profit_delta,
            }, ensure_ascii=False),
        )
        db.add(rec)
        db.flush()

        # 3. 创建 Experiment,绑定同一个 work_thread_id
        exp = Experiment(
            recommendation_id=rec.id,
            store_id=store_id,
            work_thread_id=thread.id,
            baseline_value=request.sku_price,
            observed_value=None,
            lift_pct=None,
            attribution_quality="medium",
            result="pending",
            notes=f"活动测试：{request.rule.campaign_name}，{test_days}天后评估",
        )
        db.add(exp)
        db.flush()

        # 4. 回写线程进度(同一件事的三栏信息)
        update_thread_progress(
            db,
            thread.id,
            doing=[f"测试中：{request.rule.campaign_name}（剩余{test_days}天）"],
            next_step=f"{test_days}天后评估：订单/实收/利润/复购/差评",
            current_result=None,
            ai_judgment=decision.reasoning,
            needs_owner=False,
        )
        db.commit()

        result["recommendation_id"] = rec.id
        result["experiment_id"] = exp.id
        result["work_thread_id"] = thread.id
        result["message"] = f"已创建活动测试任务，{test_days}天后系统会自动回来评估结果。"

    return result


@router.post("/stores/{store_id}/profit/diagnose")
def diagnose_profit(
    store_id: str,
    request: ProfitDiagnosisRequest,
    db: Session = Depends(get_db),
):
    """利润诊断——回答"为什么利润变差"。

    8 因子归因拆解：订单量/客单/补贴/佣金/配送/食材/包装/广告/退款。
    纯确定性计算，不用 LLM。
    """
    result = diagnose_profit_change(
        current=request.current,
        baseline=request.baseline,
        orders_current=request.orders_current,
        orders_baseline=request.orders_baseline,
    )
    return result.model_dump(mode="json")
