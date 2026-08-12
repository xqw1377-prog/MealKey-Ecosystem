"""Merchant Understanding Engine 主入口。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.merchant_understanding import MerchantUnderstandingRecord
from app.schemas.merchant_understanding import (
    GapQuestion,
    MerchantUnderstanding,
    OperatingConstraints,
    OperatingPreferences,
    PermissionPolicy,
    InferredFact,
    UnderstandingUpdateResult,
)
from app.services.mue.bootstrap import (
    bootstrap_understanding,
    empty_shell,
    gap_question,
)
from app.services.mue.nl_update import apply_nl_update


def _dumps(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(obj, ensure_ascii=False)


def _loads(raw: str | None, default: Any):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _record_to_view(rec: MerchantUnderstandingRecord) -> MerchantUnderstanding:
    inferred_raw = _loads(rec.inferred_json, [])
    inferred = [InferredFact.model_validate(x) for x in inferred_raw] if inferred_raw else []
    return MerchantUnderstanding(
        store_id=rec.store_id,
        onboarding_stage=rec.onboarding_stage or "connect",  # type: ignore[arg-type]
        store_profile=_loads(rec.store_profile_json, {}),
        inferred=inferred,
        preferences=OperatingPreferences.model_validate(_loads(rec.preferences_json, {})),
        constraints=OperatingConstraints.model_validate(_loads(rec.constraints_json, {})),
        permissions=PermissionPolicy.model_validate(_loads(rec.permissions_json, {})),
        open_gaps=list(_loads(rec.open_gaps_json, [])),
        last_interview_key=rec.last_interview_key,
        known_count=len(_loads(rec.store_profile_json, {}) or {}),
        unknown_count=len(_loads(rec.open_gaps_json, []) or []),
        updated_at=rec.created_at,
    )


def _save(db: Session, view: MerchantUnderstanding) -> MerchantUnderstanding:
    rec = db.execute(
        select(MerchantUnderstandingRecord).where(MerchantUnderstandingRecord.store_id == view.store_id)
    ).scalar_one_or_none()
    if rec is None:
        rec = MerchantUnderstandingRecord(store_id=view.store_id)
        db.add(rec)
    rec.onboarding_stage = view.onboarding_stage
    rec.store_profile_json = _dumps(view.store_profile)
    rec.inferred_json = _dumps([f.model_dump(mode="json") for f in view.inferred])
    rec.preferences_json = _dumps(view.preferences)
    rec.constraints_json = _dumps(view.constraints)
    rec.permissions_json = _dumps(view.permissions)
    rec.open_gaps_json = _dumps(view.open_gaps)
    rec.last_interview_key = view.last_interview_key
    db.commit()
    db.refresh(rec)
    view.updated_at = datetime.now(timezone.utc)
    view.known_count = len(view.store_profile)
    view.unknown_count = len(view.open_gaps)
    return view


def load_understanding(db: Session, store_id: str) -> MerchantUnderstanding:
    rec = db.execute(
        select(MerchantUnderstandingRecord).where(MerchantUnderstandingRecord.store_id == store_id)
    ).scalar_one_or_none()
    if rec is None:
        return empty_shell(store_id)
    return _record_to_view(rec)


def ensure_understanding(
    db: Session,
    store_id: str,
    *,
    agents: Any | None = None,
) -> MerchantUnderstanding:
    """读取 + 用平台已知信息刷新 A/B，并持久化。"""
    existing = load_understanding(db, store_id)
    view = bootstrap_understanding(store_id, agents=agents, existing=existing)
    return _save(db, view)


def next_interview_question(understanding: MerchantUnderstanding) -> GapQuestion | None:
    """一次只问一件必须知道的事。"""
    for key in understanding.open_gaps:
        q = gap_question(key)
        if q:
            return q
    # B 类未确认：可插一条确认题
    for fact in understanding.inferred:
        if not fact.confirmed:
            return GapQuestion(
                key=f"confirm:{fact.key}",
                question=f"我判断主要客群是{fact.label}。我先按这个理解经营，有问题吗？",
                context="这是我的推断，你纠正即可，不用重新填写。",
                options=["没问题", "不太对"],
                tier="inferred",
            )
    return None


def begin_interview_turn(db: Session, store_id: str, *, agents: Any | None = None) -> dict[str, Any]:
    """返回下一道访谈题（供 ask / 首页 need_input）。"""
    u = ensure_understanding(db, store_id, agents=agents)
    q = next_interview_question(u)
    if q is None:
        return {
            "conclusion": "店的情况我已经够用来开始经营了。",
            "actions": ["我会持续盯数据，需要你时再找你"],
            "answer": "店的情况我已经够用来开始经营了。需要你时我会出现在「现在需要你」。",
            "intent": "understanding_ready",
            "mode": "mue_interview",
            "understanding": u.model_dump(mode="json"),
        }
    u.last_interview_key = q.key
    _save(db, u)

    known = u.known_count
    unknown = u.unknown_count
    lead = f"店我基本了解了（约 {known} 项已从平台读到）。" if known else "我先根据已有数据了解你的店。"
    if unknown:
        lead += f"还有 {unknown} 件事情我从平台无法确定，需要你告诉我。"

    opts = ""
    if q.options:
        opts = "\n" + "\n".join(f"{chr(65+i)}. {o}" for i, o in enumerate(q.options))

    answer = f"{lead}\n\n{q.context}\n\n**{q.question}**{opts}"
    return {
        "conclusion": q.question,
        "actions": q.options or ["直接用一句话说清楚就行"],
        "expected": "你答完我会记住，并继续下一项或开始经营",
        "confidence": "high",
        "answer": answer,
        "intent": "understanding_interview",
        "mode": "mue_interview",
        "gap_key": q.key,
        "question": q.question,
        "question_type": "mue_gap",
        "understanding": u.model_dump(mode="json"),
    }


def handle_understanding_intent(
    db: Session,
    store_id: str,
    question: str,
    *,
    agents: Any | None = None,
) -> Optional[dict[str, Any]]:
    """设置 / 偏好 / 权限类原话 → 更新理解；非此类返回 None。"""
    u = ensure_understanding(db, store_id, agents=agents)
    result = apply_nl_update(u, question)
    if result is None:
        return None
    saved = _save(db, result.understanding)
    next_q = next_interview_question(saved)
    follow = ""
    if next_q and saved.onboarding_stage == "interview":
        follow = f"\n\n还有一件：{next_q.question}"
        saved.last_interview_key = next_q.key
        _save(db, saved)
    elif saved.onboarding_stage == "operating":
        follow = "\n\n好了，我按这个继续管。需要你时再找你。"

    return {
        "conclusion": result.reply.split("\n")[0],
        "actions": [f"已更新：{k}" for k in result.changed_keys],
        "expected": "偏好会直接影响后续经营与打扰策略",
        "confidence": "high",
        "answer": result.reply + follow,
        "intent": "understanding_update",
        "mode": "mue_update",
        "changed_keys": result.changed_keys,
        "question": question,
        "question_type": "mue_nl_setting",
        "understanding": saved.model_dump(mode="json"),
    }


def understanding_gap_candidate(understanding: MerchantUnderstanding) -> Optional[dict[str, Any]]:
    """供 POIE 投影 need_input：最多抛当前最重要的一个缺口。"""
    q = next_interview_question(understanding)
    if q is None:
        return None
    return {
        "id": f"mue:{q.key}",
        "title": q.question,
        "insight": q.context,
        "why_now": "这会影响我能不能替你做对的决策，平台数据里读不到。",
        "key": q.key,
        "options": q.options,
    }
