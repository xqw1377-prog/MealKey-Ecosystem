from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ohre import Hypothesis, Recommendation
from app.schemas.store_state import ActionCandidate, StoreState
from app.services.engines.opportunity_engine import Opportunity


@dataclass
class ScoredAction:
    object_ref: str
    action_type: str
    expected_metric: str
    expected_lift_pct_low: Optional[float]
    expected_lift_pct_high: Optional[float]
    window_hours: int
    rollback_rule: str
    confidence: float
    ease: float
    risk: float
    strategic_fit: float

    def score(self) -> float:
        # Opportunity Score = Impact * Confidence * Ease * Fit / Risk
        impact = float(self.expected_lift_pct_high or self.expected_lift_pct_low or 5)
        return (impact * self.confidence * self.ease * self.strategic_fit) / max(self.risk, 0.3)


def strategy_engine(
    db: Session,
    store_state: StoreState,
    hypothesis: Optional[Hypothesis],
    opportunities: list[Opportunity],
) -> list[Recommendation]:
    """
    V1 Strategy Engine：用 action library（规则）生成候选动作，计算 Opportunity Score，产出 Top 3 recommendation。
    对同 store + action_type + object_ref 的活跃建议幂等复用。
    """
    store_id = store_state.store.store_id

    # Determine main object (for V1: choose first core item if exists)
    core_item = store_state.core_items[0] if store_state.core_items else None
    object_ref = f"item:{core_item.item_id}" if core_item else f"store:{store_id}"

    actions: list[ScoredAction] = []

    # Action library (V1 hard-coded)
    if hypothesis and hypothesis.funnel_stage == "ctr":
        actions.append(
            ScoredAction(
                object_ref=object_ref,
                action_type="change_main_image",
                expected_metric="ctr",
                expected_lift_pct_low=6,
                expected_lift_pct_high=12,
                window_hours=24,
                rollback_rule="24h CTR 无提升且转化继续下滑则回滚主图",
                confidence=float(hypothesis.confidence),
                ease=0.9,
                risk=0.35,
                strategic_fit=0.9,
            )
        )
        actions.append(
            ScoredAction(
                object_ref=object_ref,
                action_type="change_title",
                expected_metric="ctr",
                expected_lift_pct_low=4,
                expected_lift_pct_high=10,
                window_hours=24,
                rollback_rule="24h CTR 无提升则回滚标题",
                confidence=float(hypothesis.confidence) - 0.05,
                ease=0.85,
                risk=0.35,
                strategic_fit=0.85,
            )
        )

    if hypothesis and hypothesis.funnel_stage == "cvr":
        actions.append(
            ScoredAction(
                object_ref=object_ref,
                action_type="add_set_meal",
                expected_metric="cvr",
                expected_lift_pct_low=3,
                expected_lift_pct_high=8,
                window_hours=72,
                rollback_rule="72h 转化无提升且客诉上升则回滚套餐",
                confidence=float(hypothesis.confidence) - 0.05,
                ease=0.6,
                risk=0.45,
                strategic_fit=0.8,
            )
        )

    # Only surface discount when no safer action exists.
    if not actions:
        actions.append(
            ScoredAction(
                object_ref=f"store:{store_id}",
                action_type="store_discount",
                expected_metric="orders",
                expected_lift_pct_low=8,
                expected_lift_pct_high=20,
                window_hours=72,
                rollback_rule="72h 利润下降超预期则停止折扣",
                confidence=0.42,
                ease=0.55,
                risk=0.9,
                strategic_fit=0.6,
            )
        )

    actions = sorted(actions, key=lambda a: a.score(), reverse=True)[:3]

    recs: list[Recommendation] = []
    for a in actions:
        evidence = []
        if opportunities:
            evidence.append(f"机会：{opportunities[0].title}（{opportunities[0].expected_metric}）")
        if hypothesis:
            evidence.append(f"假设：{hypothesis.root_cause}")

        existing = db.execute(
            select(Recommendation)
            .where(
                Recommendation.store_id == store_id,
                Recommendation.action_type == a.action_type,
                Recommendation.object_ref == a.object_ref,
                Recommendation.status.in_(("proposed", "adopted", "executed")),
            )
            .order_by(Recommendation.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            existing.hypothesis_id = hypothesis.id if hypothesis else existing.hypothesis_id
            existing.expected_metric = a.expected_metric
            existing.expected_lift_pct_low = a.expected_lift_pct_low
            existing.expected_lift_pct_high = a.expected_lift_pct_high
            existing.window_hours = a.window_hours
            existing.rollback_rule = a.rollback_rule
            existing.confidence = a.confidence
            existing.evidence_json = json.dumps(evidence, ensure_ascii=False)
            db.add(existing)
            recs.append(existing)
            continue

        rec = Recommendation(
            store_id=store_id,
            hypothesis_id=hypothesis.id if hypothesis else None,
            scope="item" if a.object_ref.startswith("item:") else "store",
            object_ref=a.object_ref,
            action_type=a.action_type,
            expected_metric=a.expected_metric,
            expected_lift_pct_low=a.expected_lift_pct_low,
            expected_lift_pct_high=a.expected_lift_pct_high,
            window_hours=a.window_hours,
            rollback_rule=a.rollback_rule,
            confidence=a.confidence,
            evidence_json=json.dumps(evidence, ensure_ascii=False),
            content_json=None,
            status="proposed",
        )
        db.add(rec)
        recs.append(rec)

    return recs


def to_action_candidates(recs: list[Recommendation]) -> list[ActionCandidate]:
    out: list[ActionCandidate] = []
    for r in recs:
        score = None
        # For V1: score not persisted; approximate with confidence * expected_lift_high
        if r.expected_lift_pct_high is not None:
            score = float(r.confidence) * float(r.expected_lift_pct_high)
        out.append(
            ActionCandidate(
                object_ref=r.object_ref,
                action_type=r.action_type,
                expected_metric=r.expected_metric,
                expected_lift_pct_low=r.expected_lift_pct_low,
                expected_lift_pct_high=r.expected_lift_pct_high,
                window_hours=r.window_hours,
                rollback_rule=r.rollback_rule,
                confidence=float(r.confidence),
                evidence=(json.loads(r.evidence_json) if r.evidence_json else []),
                score=score,
            )
        )
    return out
