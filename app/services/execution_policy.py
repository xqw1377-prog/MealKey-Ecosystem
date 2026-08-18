"""Execution Policy — 执行分级仲裁（WP2：AI 自己干 vs 找老板）。

核心：把 execution_mode 六档真正分档。
trust_level（0-3）是店级设置，老板可调。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ohre import Recommendation
from app.models.strategy_memory import StrategyMemoryRecord

logger = logging.getLogger(__name__)

# 仅允许与平台写回 allowlist 对齐的系统内动作；改价/投流/活动不自动执行
AUTO_EXECUTABLE_ACTIONS = {
    "change_title",
    "change_main_image",
}

# trust_level=1 时可自动执行的零风险动作
ZERO_RISK_ACTIONS = {
    "change_title",
    "change_description",
}


def get_trust_level(db: Session, store_id: str) -> int:
    """获取店级信任等级（0-3）。"""
    try:
        from app.services.settings_store import get_setting

        val = get_setting("auto_pilot_level", db=db)
        return int(val) if val and val.strip() in {"0", "1", "2", "3"} else 0
    except Exception:  # noqa: BLE001
        return 0


def _has_negative_memory(db: Session, store_id: str, action_type: str, object_ref: str) -> bool:
    """查 strategy_memory：同 action_type + 同 object 的历史 negative 记录。"""
    try:
        existing = db.execute(
            select(StrategyMemoryRecord)
            .where(
                StrategyMemoryRecord.store_id == store_id,
                StrategyMemoryRecord.action_type == action_type,
                StrategyMemoryRecord.result == "negative",
            )
            .limit(1)
        ).scalar_one_or_none()
        return existing is not None
    except Exception:  # noqa: BLE001
        return False


def _has_positive_memory(db: Session, store_id: str, action_type: str, object_ref: str = "") -> dict[str, Any] | None:
    """查 strategy_memory：同 action_type 的历史 positive 记录。

    返回记忆记录(含 lift_pct / lesson)或 None。
    这是"系统会不会学习"的核心——上次成功了,这次更敢做。
    """
    try:
        record = db.execute(
            select(StrategyMemoryRecord)
            .where(
                StrategyMemoryRecord.store_id == store_id,
                StrategyMemoryRecord.action_type == action_type,
                StrategyMemoryRecord.result == "positive",
            )
            .order_by(StrategyMemoryRecord.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if record is None:
            return None
        return {
            "action_type": record.action_type,
            "result": record.result,
            "lift_pct": record.lift_pct,
            "lesson": record.lesson,
            "reuse_when": record.reuse_when,
        }
    except Exception:  # noqa: BLE001
        return None


def _get_memory_boost(
    db: Session | None, store_id: str, action_type: str, object_ref: str = ""
) -> dict[str, Any] | None:
    """综合判断记忆加成:positive 加分,negative 减分。

    返回 None 表示无相关记忆,或 {"positive": {...}} / {"negative": True}
    """
    if db is None or not store_id or not action_type:
        return None
    neg = _has_negative_memory(db, store_id, action_type, object_ref)
    if neg:
        return {"negative": True}
    pos = _has_positive_memory(db, store_id, action_type, object_ref)
    if pos:
        return {"positive": pos}
    return None


def _core_arbitrate(
    *,
    action_type: str,
    risk_level: str,
    reversibility: str,
    confidence: float,
    profit_gate_passed: bool,
    trust_level: int,
    is_in_system: bool,
    negative_memory: bool,
    positive_memory: dict[str, Any] | None,
) -> str:
    if confidence < 0.5:
        return "OBSERVE"
    if negative_memory:
        return "DROP"

    effective_trust = min(3, trust_level + (1 if positive_memory else 0))
    if effective_trust == 0:
        return "ASK_APPROVAL"
    if effective_trust >= 1 and action_type in ZERO_RISK_ACTIONS and is_in_system:
        return "AUTO_AND_REPORT"
    if positive_memory and is_in_system and action_type in AUTO_EXECUTABLE_ACTIONS:
        return "AUTO_AND_REPORT"
    if (
        effective_trust >= 2
        and risk_level == "low"
        and reversibility == "easy"
        and confidence >= 0.8
        and profit_gate_passed
        and is_in_system
        and action_type in AUTO_EXECUTABLE_ACTIONS
    ):
        return "AUTO_AND_REPORT"
    if (
        effective_trust >= 3
        and risk_level in ("low", "medium")
        and reversibility in ("easy", "medium")
        and confidence >= 0.75
        and profit_gate_passed
    ):
        return "AUTO_AND_REPORT"
    return "ASK_APPROVAL"


def arbitrate_execution_mode(
    *,
    action_type: str,
    risk_level: str = "medium",
    reversibility: str = "medium",
    confidence: float = 0.7,
    profit_gate_passed: bool = True,
    trust_level: int = 0,
    is_in_system: bool = False,
    db: Session | None = None,
    store_id: str = "",
    object_ref: str = "",
) -> str:
    """决定执行模式：AUTO / AUTO_AND_REPORT / ASK_APPROVAL / OBSERVE / DROP。

    记忆复用：negative → DROP；positive → 降低门槛。
    若有记忆时的判断与无记忆不同，记一条 Memory-Changed Decision。
    """
    negative_memory = False
    positive_memory: dict[str, Any] | None = None
    if db is not None and store_id and action_type:
        negative_memory = _has_negative_memory(db, store_id, action_type, object_ref)
        if not negative_memory:
            positive_memory = _has_positive_memory(db, store_id, action_type, object_ref)

    naive = _core_arbitrate(
        action_type=action_type,
        risk_level=risk_level,
        reversibility=reversibility,
        confidence=confidence,
        profit_gate_passed=profit_gate_passed,
        trust_level=trust_level,
        is_in_system=is_in_system,
        negative_memory=False,
        positive_memory=None,
    )
    learned = _core_arbitrate(
        action_type=action_type,
        risk_level=risk_level,
        reversibility=reversibility,
        confidence=confidence,
        profit_gate_passed=profit_gate_passed,
        trust_level=trust_level,
        is_in_system=is_in_system,
        negative_memory=negative_memory,
        positive_memory=positive_memory,
    )
    if db is not None and store_id and naive != learned:
        try:
            from app.services.strategy_memory import record_memory_changed_decision

            record_memory_changed_decision(
                db,
                store_id=store_id,
                action_type=action_type,
                naive_mode=naive,
                learned_mode=learned,
                cause="negative_drop" if negative_memory else "positive_boost",
                memory_result="negative" if negative_memory else "positive",
            )
        except Exception:  # noqa: BLE001
            logger.warning("memory-changed decision not recorded for %s", action_type)
    return learned


# ---------------------------------------------------------------------------
# 自动执行入口（Clock/POIE 调用）：让 AUTO_AND_REPORT 真正落地
# ---------------------------------------------------------------------------

# 动作固有风险映射（菜单写入类；投流/活动等非系统内动作不会进入本流程）
_ACTION_RISK: dict[str, tuple[str, str]] = {
    # action_type: (risk_level, reversibility)
    "change_title": ("low", "easy"),
    "change_main_image": ("low", "easy"),
    "add_set_meal": ("low", "easy"),
    "menu_patch": ("low", "easy"),
    "adjust_price_value": ("medium", "easy"),
    "menu_cleanup": ("medium", "easy"),
}


def auto_execute_recommendations(
    db: Session,
    store_id: str,
    *,
    max_actions: int = 3,
    lookback_days: int = 3,
) -> list[dict[str, Any]]:
    """对近 N 天 proposed 的系统内建议做执行分级仲裁；AUTO_AND_REPORT 直接执行。

    执行后：status=executed、executor 记 AI、推 auto_done 通知（含可回滚提示）。
    trust_level=0 时直接返回空（全部等老板）。
    """
    from datetime import datetime, timedelta, timezone

    trust = get_trust_level(db, store_id)
    if trust <= 0:
        return []

    from app.services.execution_plan import apply_plan, build_change_plan

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recs = (
        db.execute(
            select(Recommendation)
            .where(
                Recommendation.store_id == store_id,
                Recommendation.status == "proposed",
                Recommendation.action_type.in_(tuple(AUTO_EXECUTABLE_ACTIONS)),
                Recommendation.created_at >= cutoff,
            )
            .order_by(Recommendation.confidence.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )

    executed: list[dict[str, Any]] = []
    for rec in recs:
        if len(executed) >= max_actions:
            break
        plan = build_change_plan(db, rec)
        if plan.mode != "in_system" or not plan.reversible:
            continue
        risk, reversibility = _ACTION_RISK.get(rec.action_type or "", ("medium", "medium"))
        mode = arbitrate_execution_mode(
            action_type=rec.action_type or "",
            risk_level=risk,
            reversibility=reversibility,
            confidence=float(rec.confidence or 0.7),
            profit_gate_passed=True,  # 菜单写入类不涉及补贴/投流支出
            trust_level=trust,
            is_in_system=True,
            db=db,
            store_id=store_id,
            object_ref=rec.object_ref or "",
        )
        if mode == "DROP":
            rec.status = "archived"
            db.add(rec)
            executed.append({"recommendation_id": rec.id, "mode": "DROP", "applied": False})
            continue
        if mode != "AUTO_AND_REPORT":
            continue

        result = apply_plan(db, rec, plan)
        if not result.get("applied"):
            continue

        now = datetime.now(timezone.utc)
        from app.services.action_pipeline import commit_recommendation_executed

        rec.adopted_at = rec.adopted_at or now
        commit_recommendation_executed(
            rec, now=now, actor="auto_pilot", domain={"mode": mode, "applied": True}, verified=True
        )
        # 审计：谁执行的 + 当时的仲裁依据
        import json as _json

        content = {}
        try:
            content = _json.loads(rec.content_json or "{}")
        except Exception:  # noqa: BLE001
            content = {}
        content["execution_mode"] = mode
        content["executor"] = "AI"
        content["permission_basis"] = {"rule": "auto_pilot_level", "level": trust}
        rec.content_json = _json.dumps(content, ensure_ascii=False)
        db.add(rec)

        try:
            from app.services.notification_service import notify_store_owner

            notify_store_owner(
                db,
                store_id=store_id,
                notification_type="auto_done",
                title=f"已替你完成：{plan.detail[:50]}",
                body=f"{plan.detail}。预计影响 {plan.expected.get('metric', '')}"
                f"，观察窗 {plan.expected.get('window_hours') or 48}h。不满意可一键回滚。",
                priority="normal",
            )
        except Exception as exc:  # noqa: BLE001 — 通知失败不阻塞执行
            logger.warning("auto_done notify failed: %s", exc)

        executed.append(
            {
                "recommendation_id": rec.id,
                "mode": mode,
                "applied": True,
                "detail": plan.detail,
            }
        )

    if executed:
        db.commit()
    return executed
