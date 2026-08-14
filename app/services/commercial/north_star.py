"""Production Evidence Phase：五条验收，不是「V1 开发完成」。

20 Paid Stores — 证明商业
100 Verified Closed Loops — 证明经营闭环（PMF Evidence Seed，不是护城河）
10 Memory-Changed Decisions — 证明学习飞轮
1 Natural Renewal — 证明价值不是新鲜感
真实 AI Cost / Store — 证明单位经济可以扩张
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.closed_loop import ClosedLoopItem
from app.models.commercial import AIUsageLedger, StoreLicense, Subscription
from app.models.strategy_memory import MemoryChangedDecision
from app.services.commercial.policy import (
    COMPANY_GOAL_MEMORY_CHANGED,
    COMPANY_GOAL_NATURAL_RENEWALS,
    COMPANY_GOAL_PAID_STORES,
    COMPANY_GOAL_VERIFIED_LOOPS,
    TWENTY_STORE_COHORTS,
    policy_snapshot,
)

VERIFIED_RESULTS = ("positive", "negative", "neutral")
VERIFIED_STATUSES = ("result_ready", "closed")
PAID_SUB_STATUSES = ("collected", "paid")


def count_paid_stores(db: Session) -> int:
    licenses = db.execute(
        select(func.count()).select_from(StoreLicense).where(StoreLicense.status == "paid")
    ).scalar() or 0
    if licenses:
        return int(licenses)
    subs = db.execute(
        select(func.count(func.distinct(Subscription.merchant_id)))
        .select_from(Subscription)
        .where(Subscription.status.in_(PAID_SUB_STATUSES))
    ).scalar() or 0
    return int(subs)


def count_verified_closed_loops(db: Session) -> int:
    count = db.execute(
        select(func.count()).select_from(ClosedLoopItem).where(
            ClosedLoopItem.result.in_(VERIFIED_RESULTS),
            ClosedLoopItem.status.in_(VERIFIED_STATUSES),
        )
    ).scalar() or 0
    return int(count)


def count_memory_changed_decisions(db: Session) -> int:
    count = db.execute(select(func.count()).select_from(MemoryChangedDecision)).scalar() or 0
    return int(count)


def count_natural_renewals(db: Session) -> int:
    """同一商户出现第二笔已收款订阅，计一次自然续费证据。"""
    rows = db.execute(
        select(Subscription.merchant_id, func.count(Subscription.id))
        .where(Subscription.status.in_(PAID_SUB_STATUSES))
        .group_by(Subscription.merchant_id)
        .having(func.count(Subscription.id) >= 2)
    ).all()
    return len(rows)


def observed_ai_cost_per_store(db: Session, paid_stores: int) -> dict:
    month = date.today().strftime("%Y-%m")
    used = db.execute(
        select(func.coalesce(func.sum(AIUsageLedger.actual_cost_cny), 0.0)).where(
            AIUsageLedger.period_month == month,
            AIUsageLedger.lane == "operating",
        )
    ).scalar() or 0.0
    used = round(float(used), 2)
    if paid_stores <= 0 or used <= 0:
        return {
            "period_month": month,
            "actual_cost_cny": used,
            "per_store_cny": None,
            "status": "unmeasured",
        }
    return {
        "period_month": month,
        "actual_cost_cny": used,
        "per_store_cny": round(used / paid_stores, 2),
        "status": "observed",
    }


def _evidence_row(key: str, proves: str, current: int, goal: int) -> dict:
    return {
        "key": key,
        "proves": proves,
        "current": current,
        "goal": goal,
        "remaining": max(goal - current, 0),
        "progress_pct": round(min(current / goal, 1.0) * 100, 1) if goal else 0.0,
    }


def company_north_star(db: Session) -> dict:
    paid = count_paid_stores(db)
    loops = count_verified_closed_loops(db)
    memory_changed = count_memory_changed_decisions(db)
    renewals = count_natural_renewals(db)
    ai_cost = observed_ai_cost_per_store(db, paid)
    policy = policy_snapshot()
    evidence = [
        _evidence_row("paid_stores", "商业", paid, COMPANY_GOAL_PAID_STORES),
        _evidence_row("verified_closed_loops", "经营闭环", loops, COMPANY_GOAL_VERIFIED_LOOPS),
        _evidence_row("memory_changed_decisions", "学习飞轮", memory_changed, COMPANY_GOAL_MEMORY_CHANGED),
        _evidence_row("natural_renewals", "价值不是新鲜感", renewals, COMPANY_GOAL_NATURAL_RENEWALS),
    ]
    return {
        "phase": "production_evidence",
        "goal": policy["company_goal"],
        "paid_stores": paid,
        "verified_closed_loops": loops,
        "memory_changed_decisions": memory_changed,
        "natural_renewals": renewals,
        "ai_cost_per_store": ai_cost,
        "paid_stores_remaining": max(COMPANY_GOAL_PAID_STORES - paid, 0),
        "verified_loops_remaining": max(COMPANY_GOAL_VERIFIED_LOOPS - loops, 0),
        "paid_progress_pct": round(min(paid / COMPANY_GOAL_PAID_STORES, 1.0) * 100, 1),
        "loop_progress_pct": round(min(loops / COMPANY_GOAL_VERIFIED_LOOPS, 1.0) * 100, 1),
        "evidence": evidence,
        "cohorts": list(TWENTY_STORE_COHORTS),
        "commercial_traction": "unproven" if paid <= 0 else "in_progress",
        "loop_ladder_note": "100 条闭环是 PMF Evidence Seed，不是护城河。",
        "note": "尽快把设计优势转化成真实 Outcome Data 优势。",
    }
