from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ohre import Observation
from app.schemas.store_state import StoreState


def feature_engine(db: Session, store_state: StoreState, days: int = 7) -> list[Observation]:
    """
    V1 Feature Engine：把 KPI 变化变成 observation（异常/变化事件）。

    目标不是“覆盖所有异常”，而是：
    - 能稳定产出少量高信号 observation
    - 让 Diagnosis/Strategy 有明确输入
    - 同一观察窗 + metric 幂等复用，避免 daily_job 无限追加
    """
    obs_list: list[Observation] = []

    def add(metric: str, what: str, conf: float, evidence: Optional[dict[str, Any]] = None):
        existing = db.execute(
            select(Observation)
            .where(
                Observation.store_id == store_state.store.store_id,
                Observation.metric == metric,
                Observation.observe_from == store_state.window.from_day,
                Observation.observe_to == store_state.window.to_day,
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            existing.what_happened = what
            existing.confidence = conf
            existing.baseline_value = store_state.kpis.get(metric).baseline_value if metric in store_state.kpis else None
            existing.observed_value = store_state.kpis.get(metric).observed_value if metric in store_state.kpis else None
            existing.delta_pct = store_state.kpis.get(metric).delta_pct if metric in store_state.kpis else None
            existing.evidence_json = json.dumps(evidence or {}, ensure_ascii=False)
            db.add(existing)
            obs_list.append(existing)
            return

        o = Observation(
            store_id=store_state.store.store_id,
            scope="store",
            metric=metric,
            window_days=days,
            baseline_from=store_state.window.compare_from_day,
            baseline_to=store_state.window.compare_to_day,
            observe_from=store_state.window.from_day,
            observe_to=store_state.window.to_day,
            baseline_value=store_state.kpis.get(metric).baseline_value if metric in store_state.kpis else None,
            observed_value=store_state.kpis.get(metric).observed_value if metric in store_state.kpis else None,
            delta_pct=store_state.kpis.get(metric).delta_pct if metric in store_state.kpis else None,
            what_happened=what,
            confidence=conf,
            evidence_json=json.dumps(evidence or {}, ensure_ascii=False),
        )
        db.add(o)
        obs_list.append(o)

    k = store_state.kpis

    # CTR down is a strong signal for "first impression competitiveness"
    if k.get("ctr") and k["ctr"].delta_pct is not None and k["ctr"].delta_pct <= -5:
        add(
            "ctr",
            f"店铺 CTR 在近{days}天相较前{days}天下降 {k['ctr'].delta_pct:.1f}%",
            0.82,
            {"delta_pct": k["ctr"].delta_pct, "stage": "ctr"},
        )

    # CVR down
    if k.get("cvr") and k["cvr"].delta_pct is not None and k["cvr"].delta_pct <= -5:
        add(
            "cvr",
            f"店铺 CVR 在近{days}天相较前{days}天下降 {k['cvr'].delta_pct:.1f}%",
            0.78,
            {"delta_pct": k["cvr"].delta_pct, "stage": "cvr"},
        )

    # Orders down with impressions stable => likely conversion/competitiveness issue, not market downturn
    if (
        k.get("orders")
        and k["orders"].delta_pct is not None
        and k["orders"].delta_pct <= -5
        and k.get("impressions")
        and (k["impressions"].delta_pct is None or k["impressions"].delta_pct > -5)
    ):
        add(
            "orders",
            f"订单下降 {k['orders'].delta_pct:.1f}% 但曝光未同步下降，疑似转化/商品竞争力问题",
            0.76,
            {"orders_delta_pct": k["orders"].delta_pct, "impressions_delta_pct": k["impressions"].delta_pct},
        )

    return obs_list
