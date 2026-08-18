"""Strategy Memory: persist Experiment Result lessons for next decisions."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ohre import Experiment, Recommendation
from app.models.strategy_memory import MemoryChangedDecision, StrategyMemoryRecord
from app.schemas.strategy_memory import ExperimentResultView, StrategyMemoryItem, StrategyMemorySnapshot


def build_experiment_result_view(
    experiment: Experiment,
    recommendation: Recommendation | None = None,
) -> ExperimentResultView:
    content = {}
    if recommendation and recommendation.content_json:
        try:
            content = json.loads(recommendation.content_json)
        except json.JSONDecodeError:
            content = {}
    summary = {
        "positive": "策略有效，已进入经营经验库。",
        "negative": "策略无效或负面，后续同类场景降权。",
        "neutral": "策略效果不明显，保持观察。",
        "unknown": "证据不足，结果未知。",
        "pending": "实验仍在观察窗。",
    }.get(experiment.result, "实验已评估。")
    return ExperimentResultView(
        experiment_id=experiment.id,
        recommendation_id=experiment.recommendation_id,
        store_id=experiment.store_id,
        action_type=recommendation.action_type if recommendation else "unknown",
        object_ref=recommendation.object_ref if recommendation else "",
        object_name=content.get("object_name") or content.get("title"),
        metric=recommendation.expected_metric if recommendation else "orders",
        lift_pct=experiment.lift_pct,
        result=experiment.result if experiment.result in {"positive", "neutral", "negative", "unknown", "pending"} else "unknown",
        attribution_quality=experiment.attribution_quality or "medium",
        window_hours=recommendation.window_hours if recommendation else None,
        summary=summary,
        evaluated_at=datetime.now(timezone.utc) if experiment.result != "pending" else None,
        evidence=[experiment.notes] if experiment.notes else [],
    )


def upsert_strategy_memory_from_experiment(db: Session, experiment: Experiment) -> StrategyMemoryRecord | None:
    if experiment.result in {None, "pending", "unknown"}:
        return None
    recommendation = db.execute(
        select(Recommendation).where(Recommendation.id == experiment.recommendation_id)
    ).scalar_one_or_none()
    view = build_experiment_result_view(experiment, recommendation)

    existing = db.execute(
        select(StrategyMemoryRecord).where(StrategyMemoryRecord.experiment_id == experiment.id)
    ).scalar_one_or_none()

    if view.result == "positive":
        lesson = f"「{view.action_type}」有效" + (
            f"，{view.metric} {view.lift_pct:+.1f}%" if view.lift_pct is not None else ""
        )
        reuse_when = f"当再次出现同类指标压力且对象类似时，优先复用 {view.action_type}。"
        avoid_when = None
        tags = ["effective", view.metric, view.action_type, "observed"]
    elif view.result == "negative":
        lesson = f"「{view.action_type}」未带来正向结果，避免重复盲目执行。"
        reuse_when = "仅在根因变化或证据更强时谨慎重试。"
        avoid_when = f"在相似窗口内不要连续叠加 {view.action_type}。"
        tags = ["ineffective", view.metric, view.action_type, "observed"]
    else:
        lesson = f"「{view.action_type}」效果不明显。"
        reuse_when = "可保留为低优先级备选。"
        avoid_when = "不要作为今日唯一主动作。"
        tags = ["neutral", view.metric, view.action_type, "observed"]

    # attribution_quality 降权：low 质量的实验结论可信度折半
    quality_multiplier = {"high": 1.0, "medium": 0.8, "low": 0.5}.get(view.attribution_quality, 0.8)
    base_confidence = 0.72 if view.result == "positive" else 0.64
    adjusted_confidence = round(base_confidence * quality_multiplier, 2)

    if existing is None:
        existing = StrategyMemoryRecord(
            store_id=experiment.store_id,
            experiment_id=experiment.id,
            recommendation_id=experiment.recommendation_id,
            action_type=view.action_type,
            result=view.result,
            lift_pct=view.lift_pct,
            context_tags_json=json.dumps(tags, ensure_ascii=False),
            lesson=lesson[:400],
            reuse_when=reuse_when[:300],
            avoid_when=(avoid_when[:300] if avoid_when else None),
            confidence=adjusted_confidence,
        )
        db.add(existing)
    else:
        existing.result = view.result
        existing.lift_pct = view.lift_pct
        existing.lesson = lesson[:400]
        existing.reuse_when = reuse_when[:300]
        existing.avoid_when = avoid_when[:300] if avoid_when else None
        existing.context_tags_json = json.dumps(tags, ensure_ascii=False)
        existing.confidence = adjusted_confidence
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


def load_strategy_memory(db: Session, store_id: str, limit: int = 20) -> StrategyMemorySnapshot:
    rows = db.execute(
        select(StrategyMemoryRecord)
        .where(StrategyMemoryRecord.store_id == store_id)
        .order_by(StrategyMemoryRecord.created_at.desc())
        .limit(limit)
    ).scalars().all()
    items: list[StrategyMemoryItem] = []
    positive: list[str] = []
    negative: list[str] = []
    for row in rows:
        tags = []
        if row.context_tags_json:
            try:
                tags = json.loads(row.context_tags_json)
            except json.JSONDecodeError:
                tags = []
        kind = "observed"
        lowered = {str(tag).strip().lower() for tag in tags}
        if "incremental" in lowered:
            kind = "incremental"
        elif "attributed" in lowered:
            kind = "attributed"
        item = StrategyMemoryItem(
            id=row.id,
            store_id=row.store_id,
            action_type=row.action_type,
            context_tags=tags,
            result=row.result if row.result in {"positive", "neutral", "negative", "unknown", "pending"} else "unknown",
            lift_pct=row.lift_pct,
            lesson=row.lesson,
            reuse_when=row.reuse_when,
            avoid_when=row.avoid_when,
            source_experiment_id=row.experiment_id,
            confidence=row.confidence,
            evidence_kind=kind,  # type: ignore[arg-type]
            created_at=row.created_at,
        )
        items.append(item)
        if row.result == "positive":
            positive.append(row.lesson)
        elif row.result == "negative":
            negative.append(row.lesson)
    return StrategyMemorySnapshot(
        store_id=store_id,
        items=items,
        positive_patterns=positive[:5],
        negative_patterns=negative[:5],
    )


# ═══ P2-9: 跨店策略记忆复用 ═══


def load_cross_store_memory(
    db: Session,
    *,
    action_type: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """跨店查询策略记忆："相似快餐店换主图有效"。

    按动作类型聚合所有门店的经验，返回成功率统计。
    """
    from sqlalchemy import func

    # 按 action_type + result 聚合
    query = (
        db.execute(
            select(
                StrategyMemoryRecord.action_type,
                StrategyMemoryRecord.result,
                func.count(StrategyMemoryRecord.id).label("count"),
                func.avg(StrategyMemoryRecord.lift_pct).label("avg_lift"),
                func.avg(StrategyMemoryRecord.confidence).label("avg_confidence"),
            )
            .group_by(StrategyMemoryRecord.action_type, StrategyMemoryRecord.result)
        ).all()
    )
    # 组织成 {action_type: {positive: {count, avg_lift}, negative: {...}, ...}}
    from collections import defaultdict
    stats: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for row in query:
        action, result, count, avg_lift, avg_conf = row
        stats[action][result] = {
            "count": count,
            "avg_lift": round(float(avg_lift or 0), 1),
            "avg_confidence": round(float(avg_conf or 0), 2),
        }

    # 计算成功率
    knowledge: list[dict] = []
    for action_type_key, results in stats.items():
        positive_count = results.get("positive", {}).get("count", 0)
        total = sum(r.get("count", 0) for r in results.values())
        success_rate = round(positive_count / total * 100, 1) if total > 0 else 0
        if total >= 2:  # 至少 2 个样本才输出
            knowledge.append({
                "action_type": action_type_key,
                "total_samples": total,
                "success_rate": success_rate,
                "positive_count": positive_count,
                "negative_count": results.get("negative", {}).get("count", 0),
                "avg_lift": results.get("positive", {}).get("avg_lift", 0),
                "lesson": f"跨 {total} 家店：{action_type_key} 成功率 {success_rate}%"
                + (f"，平均 lift +{results['positive']['avg_lift']}%" if positive_count > 0 else ""),
            })
    knowledge.sort(key=lambda x: x["total_samples"], reverse=True)
    return {
        "knowledge_base": knowledge[:limit],
        "total_actions": len(knowledge),
        "principle": "跨店经验只作参考，单店实验仍优先。",
    }


def record_memory_changed_decision(
    db: Session,
    *,
    store_id: str,
    action_type: str,
    naive_mode: str,
    learned_mode: str,
    cause: str,
    memory_result: str,
    source: str = "execution_policy",
) -> MemoryChangedDecision | None:
    """同一店、同一动作、同一天只记一次：证明记忆改了判断，不是刷次数。"""
    if not store_id or naive_mode == learned_mode:
        return None
    fingerprint = f"{store_id}:{action_type}:{naive_mode}:{learned_mode}:{date.today().isoformat()}"
    existing = db.execute(
        select(MemoryChangedDecision).where(MemoryChangedDecision.fingerprint == fingerprint)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = MemoryChangedDecision(
        store_id=store_id,
        fingerprint=fingerprint,
        action_type=action_type,
        naive_mode=naive_mode,
        learned_mode=learned_mode,
        cause=cause,
        source=source,
        memory_result=memory_result,
    )
    db.add(row)
    db.flush()
    return row

