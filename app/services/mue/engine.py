"""Merchant Understanding Engine 主入口。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
from app.services.mos_engine import update_mos_status


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


def _apply_view_to_record(rec: MerchantUnderstandingRecord, view: MerchantUnderstanding) -> None:
    rec.onboarding_stage = view.onboarding_stage
    rec.store_profile_json = _dumps(view.store_profile)
    rec.inferred_json = _dumps([f.model_dump(mode="json") for f in view.inferred])
    rec.preferences_json = _dumps(view.preferences)
    rec.constraints_json = _dumps(view.constraints)
    rec.permissions_json = _dumps(view.permissions)
    rec.open_gaps_json = _dumps(view.open_gaps)
    rec.last_interview_key = view.last_interview_key


def _refresh_platform_flag(db: Session, view: MerchantUnderstanding) -> MerchantUnderstanding:
    from app.models.settings import PlatformConnection

    connected = db.execute(
        select(PlatformConnection.id)
        .where(
            PlatformConnection.store_id == view.store_id,
            PlatformConnection.status == "connected",
        )
        .limit(1)
    ).scalar_one_or_none()
    view.platform_connected = connected is not None
    if view.platform_connected:
        view.store_profile = {**view.store_profile, "platform_connected": True}
    return view


def light_agents_for_store(db: Session, store_id: str) -> Any | None:
    """访谈/理解刷新用的轻量 agents：只带门店档案，不跑 13 个专业 agent。"""
    from types import SimpleNamespace

    from app.models.entities import Store

    store = db.execute(select(Store).where(Store.id == store_id)).scalar_one_or_none()
    if store is None:
        return None
    store_view = SimpleNamespace(
        name=store.name,
        city=store.city,
        area=store.area,
        category=None,
        primary_audience=store.primary_audience,
    )
    state = SimpleNamespace(
        store=store_view,
        store_name=store.name,
        city=store.city,
        area=store.area,
        category=None,
        kpis={},
        profit=None,
    )
    return SimpleNamespace(store_state=state)


def _save(db: Session, view: MerchantUnderstanding) -> MerchantUnderstanding:
    view = update_mos_status(view)
    rec = db.execute(
        select(MerchantUnderstandingRecord).where(MerchantUnderstandingRecord.store_id == view.store_id)
    ).scalar_one_or_none()
    if rec is None:
        rec = MerchantUnderstandingRecord(store_id=view.store_id)
        db.add(rec)
    _apply_view_to_record(rec, view)
    try:
        db.commit()
    except IntegrityError:
        # 并发初始化同一家店时，退回到读取已存在记录并覆盖更新。
        db.rollback()
        rec = db.execute(
            select(MerchantUnderstandingRecord).where(MerchantUnderstandingRecord.store_id == view.store_id)
        ).scalar_one()
        _apply_view_to_record(rec, view)
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
        view = empty_shell(store_id)
    else:
        view = _record_to_view(rec)
    _refresh_platform_flag(db, view)
    return update_mos_status(view)


def ensure_understanding(
    db: Session,
    store_id: str,
    *,
    agents: Any | None = None,
) -> MerchantUnderstanding:
    """读取 + 用平台已知信息刷新 A/B，并持久化。"""
    existing = load_understanding(db, store_id)
    view = bootstrap_understanding(store_id, agents=agents, existing=existing)
    _refresh_platform_flag(db, view)
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


def _interview_payload(
    u: MerchantUnderstanding,
    *,
    q: GapQuestion | None = None,
    intent: str,
    mode: str,
    question_type: str,
    answer: str,
    conclusion: str,
    actions: list[str] | None = None,
    expected: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    u = update_mos_status(u)
    payload: dict[str, Any] = {
        "conclusion": conclusion,
        "actions": actions or (q.options if q and q.options else ["直接用一句话说清楚就行"]),
        "expected": expected,
        "confidence": "high",
        "answer": answer,
        "intent": intent,
        "mode": mode,
        "gap_key": q.key if q else None,
        "question": q.question if q else None,
        "options": list(q.options) if q and q.options else [],
        "question_type": question_type,
        "understanding": u.model_dump(mode="json"),
        "accepted": True,
    }
    if extra:
        payload.update(extra)
    return payload


def begin_interview_turn(db: Session, store_id: str, *, agents: Any | None = None) -> dict[str, Any]:
    """返回下一道访谈题（供 ask / 首页 need_input）。"""
    u = ensure_understanding(db, store_id, agents=agents)
    q = next_interview_question(u)
    if q is None:
        return _interview_payload(
            u,
            intent="understanding_ready",
            mode="mue_interview",
            question_type="mue_ready",
            answer="店的情况我已经够用来开始经营了。需要你时我会出现在「现在需要你」。",
            conclusion="店的情况我已经够用来开始经营了。",
            actions=["我会持续盯数据，需要你时再找你"],
            expected="需要你时我会出现在「现在需要你」",
        )
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
    return _interview_payload(
        u,
        q=q,
        intent="understanding_interview",
        mode="mue_interview",
        question_type="mue_gap",
        answer=answer,
        conclusion=q.question,
        expected="你答完我会记住，并继续下一项或开始经营",
    )


def handle_understanding_intent(
    db: Session,
    store_id: str,
    question: str,
    *,
    agents: Any | None = None,
    key: str | None = None,
) -> Optional[dict[str, Any]]:
    """设置 / 偏好 / 权限类原话 → 更新理解；非此类返回 None。"""
    u = ensure_understanding(db, store_id, agents=agents)
    gap_key = str(key or "").strip() or u.last_interview_key
    if gap_key:
        u.last_interview_key = gap_key
    result = apply_nl_update(u, question)
    if result is None:
        return None
    saved = _save(db, result.understanding)
    next_q = next_interview_question(saved)
    follow = ""
    if next_q and (saved.onboarding_stage == "interview" or not saved.mos_satisfied):
        follow = f"\n\n还有一件：{next_q.question}"
        saved.last_interview_key = next_q.key
        saved = _save(db, saved)
    elif saved.mos_satisfied or saved.onboarding_stage == "operating":
        follow = "\n\n好了，我按这个继续管。需要你时再找你。"

    return _interview_payload(
        saved,
        q=next_q,
        intent="understanding_update",
        mode="mue_update",
        question_type="mue_nl_setting",
        answer=result.reply + follow,
        conclusion=result.reply.split("\n")[0],
        actions=[f"已更新：{k}" for k in result.changed_keys],
        expected="偏好会直接影响后续经营与打扰策略",
        extra={"changed_keys": result.changed_keys},
    )


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
