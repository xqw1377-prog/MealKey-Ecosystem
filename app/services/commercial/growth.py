"""客户裂变：Result → 结果卡 → 分享 → Free Audit → 付费。

公开卡隐藏店名和金额绝对值，只讲相对变化。CTA 固定为「测一下我的店」。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commercial import GrowthArtifact, ReferralAttribution
from app.models.closed_loop import ClosedLoopItem
from app.services.commercial.policy import ACQUISITION_AUDIT_CAP_CNY

CTA = "测一下我的店"
ACTION_LABELS = {
    "change_main_image": "换主图",
    "change_title": "改标题",
    "reply_ordinary_reviews": "回复评价",
    "batch_reply_negative_reviews": "处理差评",
    "appeal_pack": "提交申诉",
    "add_set_meal": "上套餐",
    "join_lunch_campaign": "参加活动",
    "launch_value_bundle_promo": "做超值套餐",
    "match_competitor_promo": "对冲竞品活动",
}


def _json_load(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _json_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def action_label(action_type: str) -> str:
    return ACTION_LABELS.get(str(action_type or "").strip(), "经营动作")


def _public_title(*, action_type: str, metric: str, lift_pct: float | None) -> str:
    label = action_label(action_type)
    metric_name = (metric or "经营指标").strip() or "经营指标"
    if lift_pct is not None:
        sign = "+" if lift_pct > 0 else ""
        return f"{label}后，{metric_name} {sign}{lift_pct:.1f}%"
    return f"一次{label}已经跑完观察窗"


def _wechat_copy(*, title: str, lift_pct: float | None) -> str:
    if lift_pct is not None and lift_pct > 0:
        return f"一家外卖店刚做出结果：{title}。点开就能免费测自己的店。"
    return f"一家外卖店刚跑完一次经营动作。{title}。点开免费测一下你的店。"


def public_card(artifact: GrowthArtifact, *, share_url: str | None = None) -> dict[str, Any]:
    extra = _json_load(artifact.share_json)
    lift = artifact.lift_pct
    payload = {
        "id": artifact.id,
        "title": extra.get("public_title") or artifact.title,
        "metric": artifact.metric,
        "lift_pct": lift,
        "cta": artifact.cta or CTA,
        "wechat_copy": extra.get("wechat_copy") or _wechat_copy(title=artifact.title, lift_pct=lift),
        "footnote": "不展示店名，也不展示营业额或利润绝对值。",
        "audit_cap_cny": ACQUISITION_AUDIT_CAP_CNY,
    }
    if share_url:
        payload["share_url"] = share_url
    # 硬约束：公开卡不得带店名/金额
    for forbidden in ("store_name", "gmv", "profit", "amount_cny", "from_store_id"):
        payload.pop(forbidden, None)
    return payload


def share_url_for(artifact_id: str, origin: str = "") -> str:
    base = str(origin or "").rstrip("/")
    path = f"/r/{artifact_id}"
    return f"{base}{path}" if base else path


def get_artifact(db: Session, artifact_id: str) -> GrowthArtifact | None:
    return db.get(GrowthArtifact, artifact_id)


def artifact_for_loop(db: Session, loop_id: str) -> GrowthArtifact | None:
    return db.execute(select(GrowthArtifact).where(GrowthArtifact.loop_id == loop_id)).scalar_one_or_none()


def _lift_from_item(db: Session, item: ClosedLoopItem) -> float | None:
    extra = _json_load(item.pack_json)
    if extra.get("lift_pct") is not None:
        try:
            return float(extra["lift_pct"])
        except (TypeError, ValueError):
            pass
    if item.experiment_id:
        from app.models.ohre import Experiment

        experiment = db.get(Experiment, item.experiment_id)
        if experiment is not None and experiment.lift_pct is not None:
            return float(experiment.lift_pct)
    return None


def ensure_result_card(
    db: Session,
    item: ClosedLoopItem,
    *,
    lift_pct: float | None = None,
    force: bool = False,
) -> GrowthArtifact | None:
    """把一次 Result 收成可分享的结果卡。负向结果默认不裂变。"""
    result = str(item.result or "").lower()
    lift = lift_pct if lift_pct is not None else _lift_from_item(db, item)
    shareable = force or result == "positive" or (lift is not None and lift > 0)
    if not shareable:
        return artifact_for_loop(db, item.id)

    existing = artifact_for_loop(db, item.id)
    title = _public_title(action_type=item.action_type, metric=item.success_metric or "经营指标", lift_pct=lift)
    share_payload = {
        "public_title": title,
        "wechat_copy": _wechat_copy(title=title, lift_pct=lift),
        "views": _json_load(existing.share_json).get("views", 0) if existing else 0,
        "audits": _json_load(existing.share_json).get("audits", 0) if existing else 0,
    }
    if existing:
        existing.title = title
        existing.metric = item.success_metric or existing.metric
        existing.lift_pct = lift
        existing.hide_store_name = True
        existing.hide_absolute_money = True
        existing.cta = CTA
        existing.share_json = _json_dump(share_payload)
        artifact = existing
    else:
        artifact = GrowthArtifact(
            store_id=item.store_id,
            loop_id=item.id,
            title=title,
            metric=item.success_metric or "经营指标",
            lift_pct=lift,
            hide_store_name=True,
            hide_absolute_money=True,
            cta=CTA,
            share_json=_json_dump(share_payload),
        )
        db.add(artifact)
        db.flush()

    pack = _json_load(item.pack_json)
    if lift is not None:
        pack["lift_pct"] = lift
    pack["share_card"] = public_card(artifact)
    item.pack_json = _json_dump(pack)
    db.flush()
    return artifact


def maybe_mint_result_card(db: Session, item: ClosedLoopItem, *, lift_pct: float | None = None) -> None:
    try:
        ensure_result_card(db, item, lift_pct=lift_pct, force=False)
    except Exception:
        return


def bump_views(db: Session, artifact: GrowthArtifact) -> None:
    extra = _json_load(artifact.share_json)
    extra["views"] = int(extra.get("views") or 0) + 1
    artifact.share_json = _json_dump(extra)
    db.flush()


def run_free_audit(
    db: Session,
    artifact: GrowthArtifact,
    *,
    store_name: str,
    city: str = "",
    category: str = "",
    pain: str = "",
) -> dict[str, Any]:
    """Free Audit：默认 Luna/Terra 级启发式，成本上限 ¥5。不创建付费店。"""
    extra = _json_load(artifact.share_json)
    extra["audits"] = int(extra.get("audits") or 0) + 1
    artifact.share_json = _json_dump(extra)

    findings = [
        "先看主图第一眼能不能看清分量和热气。",
        "有没有一组套餐承接还在犹豫的人。",
        "差评有没有在 24 小时内回复完。",
    ]
    text = f"{pain}{category}{store_name}"
    if any(token in text for token in ("转化", "点击", "主图", "没人点")):
        findings[0] = "你提到的转化/点击，通常先从主图和标题下手，不要同时改价。"
    if any(token in text for token in ("利润", "补贴", "满减")):
        findings[1] = "活动前先看到手率。补贴能换单，但不该把利润打穿。"
    if any(token in text for token in ("评价", "差评", "口碑")):
        findings[2] = "差评先回复再优化商品。口碑漏了，后面投流会更贵。"

    attribution = ReferralAttribution(
        artifact_id=artifact.id,
        from_store_id=artifact.store_id,
        to_store_id=None,
        path="result_share",
        status="audited",
    )
    db.add(attribution)
    db.flush()
    return {
        "ok": True,
        "cta": CTA,
        "store_name": store_name.strip() or "你的店",
        "city": city,
        "findings": findings,
        "next_step": "开通 AI 店长后，我会按你店的真实数据排出今天这一件事。",
        "audit_cap_cny": ACQUISITION_AUDIT_CAP_CNY,
        "attribution_id": attribution.id,
        "artifact_id": artifact.id,
        "open_url": f"/?ref={artifact.id}",
    }


def attach_referral_store(db: Session, *, artifact_id: str, to_store_id: str) -> ReferralAttribution | None:
    row = db.execute(
        select(ReferralAttribution)
        .where(
            ReferralAttribution.artifact_id == artifact_id,
            ReferralAttribution.to_store_id.is_(None),
        )
        .order_by(ReferralAttribution.created_at.desc())
    ).scalars().first()
    if row is None:
        artifact = get_artifact(db, artifact_id)
        if artifact is None:
            return None
        row = ReferralAttribution(
            artifact_id=artifact_id,
            from_store_id=artifact.store_id,
            to_store_id=to_store_id,
            path="result_share",
            status="store_created",
        )
        db.add(row)
        db.flush()
        return row
    row.to_store_id = to_store_id
    row.status = "store_created"
    db.flush()
    return row
