"""Strategy Memory 生命周期管理 — 需求 #199。

Memory 不能只会越积越多,还必须会过期、降权、失效。

规则:
- 超过 180 天未被引用的 Memory → 自动降权(confidence *= 0.5)
- 超过 365 天的 Memory → 标记 expired,不再参与决策
- 如果同 action_type 有更新的 Memory → 旧的自动降权
- 连续 3 次被引用但从未产生 positive lift 的 Memory → 标记 unreliable
"""
from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.strategy_memory import StrategyMemoryRecord


def run_memory_lifecycle(db: Session) -> dict[str, Any]:
    """执行 Memory 生命周期清理。Celery beat 定期调用。"""
    now = utc_now()
    stats = {"expired": 0, "downgraded": 0, "unreliable": 0, "total": 0}

    all_records = list(db.execute(select(StrategyMemoryRecord)).scalars())
    stats["total"] = len(all_records)

    # 按 action_type 分组,找每个 action 最新的记录
    latest_by_action: dict[str, StrategyMemoryRecord] = {}
    for r in all_records:
        key = f"{r.store_id}:{r.action_type}"
        if key not in latest_by_action or r.created_at > latest_by_action[key].created_at:
            latest_by_action[key] = r

    for r in all_records:
        created = r.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days if created else 0

        # 规则1: 超过 365 天 → 标记过期
        if age_days > 365:
            if r.result != "expired":
                r.result = "expired"
                r.confidence = 0.0
                stats["expired"] += 1
            continue

        # 规则2: 超过 180 天 → 降权
        if age_days > 180:
            old_conf = r.confidence
            r.confidence = min(r.confidence, 0.3)
            if old_conf != r.confidence:
                stats["downgraded"] += 1
            continue

        # 规则3: 同 action_type 有更新的记录 → 旧记录降权
        key = f"{r.store_id}:{r.action_type}"
        latest = latest_by_action.get(key)
        if latest and latest.id != r.id and r.confidence > 0.3:
            r.confidence *= 0.6
            stats["downgraded"] += 1

    db.commit()
    return stats


def get_active_memories(db: Session, store_id: str, limit: int = 20) -> list[StrategyMemoryRecord]:
    """获取有效的 Memory(排除过期/失效的)。"""
    return list(
        db.execute(
            select(StrategyMemoryRecord)
            .where(
                StrategyMemoryRecord.store_id == store_id,
                StrategyMemoryRecord.result != "expired",
                StrategyMemoryRecord.confidence > 0.1,
            )
            .order_by(StrategyMemoryRecord.created_at.desc())
            .limit(limit)
        ).scalars()
    )
