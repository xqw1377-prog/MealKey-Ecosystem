from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.models.ohre import Experiment, Recommendation


@dataclass(frozen=True)
class ActionFeedback:
    result: str
    score_delta: float
    note: str
    lift_pct: float | None = None


_FEEDBACK_SCORE_DELTA = {
    "positive": 1.25,
    "neutral": -0.35,
    "negative": -1.25,
    "pending": -1.75,
}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_loads_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _latest_experiment_map(experiments: Iterable[Experiment]) -> dict[str, Experiment]:
    latest: dict[str, tuple[datetime, Experiment]] = {}
    for experiment in experiments:
        recommendation_id = getattr(experiment, "recommendation_id", None)
        if not recommendation_id:
            continue
        created_at = _as_utc(getattr(experiment, "created_at", None)) or datetime.min.replace(tzinfo=timezone.utc)
        current = latest.get(recommendation_id)
        if current is None or created_at >= current[0]:
            latest[recommendation_id] = (created_at, experiment)
    return {recommendation_id: row[1] for recommendation_id, row in latest.items()}


def _matches_source(rec: Recommendation, source_tag: str | None) -> bool:
    if not source_tag:
        return True
    payload = _json_loads_dict(rec.content_json)
    return payload.get("source") == source_tag


def _feedback_result(rec: Recommendation, experiment: Experiment | None) -> str | None:
    has_execution = rec.status in {"executed", "archived"} or rec.executed_at is not None
    if not has_execution:
        return None
    if experiment is None:
        return "pending" if rec.status == "executed" else None
    result = getattr(experiment, "result", None)
    if result in {None, "pending"}:
        return "pending"
    if result in {"positive", "neutral", "negative"}:
        return result
    return None


def _feedback_note(result: str, lift_pct: float | None) -> str:
    if result == "positive":
        lift_text = f"（lift {lift_pct:+.1f}%）" if lift_pct is not None else ""
        return f"近 21 天同类动作验证有效{lift_text}，下一轮可前置这条杠杆。"
    if result == "negative":
        lift_text = f"（lift {lift_pct:+.1f}%）" if lift_pct is not None else ""
        return f"近 21 天同类动作反馈为负{lift_text}，这轮先压后，优先换别的低风险动作。"
    if result == "neutral":
        return "近 21 天同类动作效果一般，这轮先降一级，除非现场证据明显更强。"
    return "近 21 天同类动作仍在观察窗，先不要叠加第二个同类动作。"


def find_recent_action_feedback(
    recommendations: Iterable[Recommendation],
    experiments: Iterable[Experiment],
    *,
    action_type: str,
    object_ref: str,
    source_tag: str | None = None,
) -> ActionFeedback | None:
    experiment_map = _latest_experiment_map(experiments)
    matched: list[tuple[datetime, Recommendation, Experiment | None, str]] = []
    for recommendation in recommendations:
        if recommendation.action_type != action_type or recommendation.object_ref != object_ref:
            continue
        if not _matches_source(recommendation, source_tag):
            continue
        experiment = experiment_map.get(recommendation.id)
        result = _feedback_result(recommendation, experiment)
        if result is None:
            continue
        event_at = _as_utc(recommendation.executed_at or recommendation.adopted_at or recommendation.created_at)
        matched.append(
            (
                event_at or datetime.min.replace(tzinfo=timezone.utc),
                recommendation,
                experiment,
                result,
            )
        )

    if not matched:
        return None

    _event_at, _recommendation, experiment, result = sorted(matched, key=lambda row: row[0], reverse=True)[0]
    lift_pct = getattr(experiment, "lift_pct", None) if experiment is not None else None
    return ActionFeedback(
        result=result,
        score_delta=_FEEDBACK_SCORE_DELTA[result],
        note=_feedback_note(result, lift_pct),
        lift_pct=lift_pct,
    )
