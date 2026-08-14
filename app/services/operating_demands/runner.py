"""把一条经营需求跑成 Verdict，并可挂上 Closed Loop。"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.services.operating_demands.catalog import by_code
from app.services.operating_demands.models import DemandVerdict, OperatingDemand
from app.services.operating_demands.playbooks import run_playbook
from app.services.operating_demands.router import match_demand


def facts_from_store_state(state: Any) -> dict[str, Any]:
    if state is None:
        return {}
    kpis = getattr(state, "kpis", None) or {}
    facts: dict[str, Any] = {}

    def delta(name: str) -> float | None:
        metric = kpis.get(name) if isinstance(kpis, dict) else None
        if metric is None:
            return None
        return getattr(metric, "delta_pct", None)

    facts["exposure"] = delta("impressions")
    facts["ctr"] = delta("ctr")
    facts["cvr"] = delta("cvr")
    facts["aov"] = delta("aov") or delta("avg_order_value")
    facts["orders"] = delta("orders")
    facts["profit"] = delta("profit") or delta("take_home_rate")
    facts["rating"] = delta("rating")
    facts["ads_roi"] = delta("ads_roi")
    facts["search_rank"] = delta("search_rank")
    facts["daypart_roi"] = delta("lunch_ads_roi") or delta("daypart_roi")
    facts["budget_pace"] = delta("budget_pace")
    facts["paid_cvr"] = delta("paid_cvr")
    facts["organic_orders"] = delta("organic_orders")
    facts["paid_orders"] = delta("paid_orders")
    facts["new_customers"] = delta("new_customers")
    facts["repeat_orders"] = delta("repeat_orders")

    profit = getattr(state, "profit", None)
    if profit is not None:
        facts["take_home_rate"] = getattr(profit, "take_home_rate", None)
        facts["refund_cost"] = getattr(profit, "refund_cost", None)
        facts["food_cost"] = getattr(profit, "food_cost", None)
        facts["packaging_cost"] = getattr(profit, "packaging_cost", None)
        facts["merchant_subsidy"] = getattr(profit, "merchant_subsidy", None)
        facts["ads_spend"] = getattr(profit, "ads_spend", None)
        facts["contribution_profit"] = getattr(profit, "contribution_profit", None)
        facts["unit_profit"] = getattr(profit, "contribution_profit_per_order", None)
        facts["multi_platform_profit"] = getattr(profit, "contribution_profit", None)

    feedback = getattr(state, "feedback", None)
    if feedback is not None:
        facts["reviews"] = getattr(feedback, "recent_review_count", None)
        facts["recent_bad_review_count"] = getattr(feedback, "recent_bad_review_count", None)
        facts["bad_review_rate"] = getattr(feedback, "bad_review_rate", None)

    customer = getattr(state, "customer", None)
    if customer is not None:
        facts["repurchase_rate"] = getattr(customer, "repurchase_rate", None)
        facts["new_customer_share_pct"] = getattr(customer, "new_customer_share_pct", None)
        facts["churn_risk_level"] = getattr(customer, "churn_risk_level", None)

    ads_summary = getattr(state, "ads_summary", None)
    if ads_summary is not None:
        facts["total_ads_cost"] = getattr(ads_summary, "total_cost", None)
        facts["ads_spend"] = facts.get("ads_spend") or getattr(ads_summary, "total_cost", None)
        facts["paid_orders"] = facts.get("paid_orders") or getattr(ads_summary, "total_ads_orders", None)
        facts["ads_roi"] = facts.get("ads_roi") or getattr(ads_summary, "avg_roas", None)

    competition_changes = getattr(state, "competition_changes", None) or []
    if competition_changes:
        facts["competition_changes_count"] = len(competition_changes)
        facts["competitor_price_changes"] = sum(1 for row in competition_changes if getattr(row, "type", "") == "price")
        facts["competitor_promo_changes"] = sum(1 for row in competition_changes if getattr(row, "type", "") == "promo")
        facts["competition_signal"] = getattr(competition_changes[0], "summary", None)

    platform_health = getattr(state, "platform_health", None)
    if platform_health is not None:
        facts["open_status"] = getattr(platform_health, "open_status", None)
        facts["business_hours_ok"] = getattr(platform_health, "business_hours_ok", None)
        facts["merchant_cancel_rate"] = getattr(platform_health, "merchant_cancel_rate", None)
        facts["hero_stock_rate"] = getattr(platform_health, "hero_sku_in_stock_rate", None)
        facts["meal_prep_rate"] = getattr(platform_health, "meal_prep_rate", None)

    benchmark = getattr(state, "benchmark", None)
    if benchmark is not None:
        facts["benchmark_available"] = getattr(benchmark, "available", None)
        facts["peer_count"] = getattr(benchmark, "peer_count", None)

    tasks = getattr(state, "tasks", None) or []
    if tasks:
        facts["open_human_tasks_count"] = len(tasks)
        facts["missing_evidence_tasks"] = sum(1 for row in tasks if not getattr(row, "evidence", None))

    problem = getattr(state, "primary_problem", None)
    if problem is not None:
        facts["primary_problem"] = getattr(problem, "type", None)
    return {key: value for key, value in facts.items() if value is not None}


def run_demand(
    demand: OperatingDemand | str | int,
    facts: dict[str, Any] | None = None,
) -> DemandVerdict:
    if isinstance(demand, int):
        from app.services.operating_demands.catalog import by_id

        demand = by_id(demand)
    elif isinstance(demand, str):
        demand = by_code(demand)
    return run_playbook(demand, facts or {})


def open_demand_loop(
    db: Session,
    store_id: str,
    verdict: DemandVerdict,
) -> Optional[Any]:
    from app.services.closed_loop import ensure_now_loop
    from app.services.store_ops import (
        C_DEMAND_CODES,
        HUMAN_TASK,
        build_human_task_pack,
        load_roster,
        nag_overdue_human_tasks,
    )

    demand = verdict.demand
    roster = load_roster(db, store_id)
    human = demand.loop == "C" or demand.execution == HUMAN_TASK or demand.code in C_DEMAND_CODES
    if demand.code == "RECTIFY_EVIDENCE":
        nag_overdue_human_tasks(db, store_id)
    if human:
        pack = build_human_task_pack(
            title=demand.question,
            diagnosis=verdict.diagnosis,
            action=verdict.action,
            assignee_name=roster.get("manager_name") or "店长",
            demand_code=demand.code,
            observe_hours=demand.window_hours,
            metric=demand.metric,
            guardrail=demand.guardrail,
            task_url=roster.get("task_url") or "",
        )
        pack["due_hours"] = 8 if demand.window_hours > 8 else max(2, demand.window_hours)
        pack["assignee_role"] = "manager"
        action_type = "ops_hint"
    else:
        action_type = _action_type(verdict)
        pack = {
            "action_type": action_type,
            "object_name": demand.code,
            "title": demand.question,
            "observe_hours": demand.window_hours,
            "success_metric": demand.metric,
            "success_target": verdict.action,
            "guardrail": demand.guardrail,
            "current_problem": verdict.diagnosis,
            "demand_code": demand.code,
            "demand_id": demand.id,
            "execution_mode": verdict.execution,
            "requires_approval": verdict.execution != "AUTO",
        }
    card_id = f"demand:{demand.code}:{date.today().isoformat()}"
    try:
        return ensure_now_loop(
            db,
            store_id,
            decision_flow={
                "now": {
                    "id": card_id,
                    "source_card_id": card_id,
                    "title": f"{demand.code} · {demand.question}",
                    "why_now": verdict.diagnosis,
                    "ai_already_did": verdict.action,
                    "business_impact": "；".join(verdict.evidence[:4]),
                    "execution_pack": pack,
                }
            },
        )
    except Exception:  # noqa: BLE001
        return None


def _action_type(verdict: DemandVerdict) -> str:
    action = verdict.action or ""
    code = getattr(verdict.demand, "code", "")
    if code == "APPEAL_PACK" or "申诉" in action:
        return "appeal_pack"
    if "主图" in action or "首屏" in action:
        return "change_main_image"
    if "标题" in action:
        return "change_title"
    if "评价" in action or "差评" in action or "回复" in action:
        return "reply_ordinary_reviews" if "普通" in action else "batch_reply_negative_reviews"
    if verdict.execution == "HUMAN_TASK":
        return "ops_hint"
    return "ops_hint"
