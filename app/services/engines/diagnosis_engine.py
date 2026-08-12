from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ohre import Hypothesis, Observation
from app.schemas.store_state import StoreState


def diagnosis_engine(db: Session, store_state: StoreState, observations: list[Observation]) -> Optional[Hypothesis]:
    """
    V1 Diagnosis Engine：把 observation 收敛成 "主因 1 + 次因 2" 的假设。
    同一 observation 幂等复用，避免 daily_job 重复写入。
    """
    if not observations:
        return None

    # pick the highest confidence observation
    obs = sorted(observations, key=lambda o: float(o.confidence or 0), reverse=True)[0]

    # LLM 诊断推理器（规则筛信号 + LLM 推理根因）
    from app.services.diagnosis_reasoner import llm_diagnose_root_cause

    llm_result = llm_diagnose_root_cause(
        metric=obs.metric,
        delta_pct=obs.delta_pct,
        store_name=getattr(store_state.store, "name", ""),
        kpis=store_state.kpis,
        competition_changes=getattr(store_state, "competition_changes", None),
        fallback_root_cause="",
        fallback_funnel_stage="",
    )

    funnel_stage = llm_result.get("funnel_stage")
    root_cause = llm_result.get("root_cause", "数据不足，暂无法判断主要原因")
    competing = llm_result.get("competing_causes", [])
    evidence_refs = llm_result.get("evidence", [])
    if obs.delta_pct is not None:
        evidence_refs.insert(0, f"{obs.metric.upper()} 变化：{obs.delta_pct:.1f}%")

    # 规则降级（LLM 不可用时保留原有逻辑）
    if llm_result.get("source") == "rule_fallback" and obs.metric == "ctr":
        funnel_stage = "ctr"
        root_cause = "主推商品的第一眼竞争力下降（主图/标题/价格感知）"
        competing = [
            "竞品近期换图/改标题，导致相对点击流失",
            "你的价格带出现缺口，用户更倾向点更具性价比的套餐",
        ]
        evidence_refs = [
            f"CTR 变化：{obs.delta_pct:.1f}%",
            "如有竞品快照，可追加：竞品主图/套餐变化",
        ]
    elif llm_result.get("source") == "rule_fallback" and obs.metric == "cvr":
        funnel_stage = "cvr"
        root_cause = "用户愿意点进来但不下单（价格/套餐/评价/配送预期）"
        competing = [
            "差评主题上升导致转化下滑",
            "套餐结构不足，客单与凑单承接不住",
        ]
        evidence_refs = [
            f"CVR 变化：{obs.delta_pct:.1f}%",
        ]
    elif obs.metric == "orders":
        funnel_stage = store_state.primary_problem.type if store_state.primary_problem else None
        root_cause = "订单下滑但曝光相对稳定，优先排查 CTR/CVR 与核心 SKU 表现"
        competing = ["商圈整体下行（需用商圈对照确认）", "活动结束导致转化下降（需补充活动数据）"]
        evidence_refs = [obs.what_happened]

    existing = db.execute(
        select(Hypothesis).where(Hypothesis.observation_id == obs.id).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        existing.funnel_stage = funnel_stage
        existing.root_cause = root_cause
        existing.competing_explanations = json.dumps(competing, ensure_ascii=False)
        existing.evidence_refs = json.dumps(evidence_refs, ensure_ascii=False)
        existing.confidence = float(obs.confidence or 0.7)
        db.add(existing)
        return existing

    h = Hypothesis(
        store_id=store_state.store.store_id,
        observation_id=obs.id,
        funnel_stage=funnel_stage,
        root_cause=root_cause,
        competing_explanations=json.dumps(competing, ensure_ascii=False),
        evidence_refs=json.dumps(evidence_refs, ensure_ascii=False),
        confidence=float(obs.confidence or 0.7),
    )
    db.add(h)
    return h
