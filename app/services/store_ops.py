"""门店线下动作：派给谁 → 催办 → 证据门禁 → 回看指标。

不新造模块。挂在 Closed Loop 上。老板仍只面对一个 AI 店长。
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business_facts import OpsMetricDaily
from app.models.closed_loop import ClosedLoopItem
from app.services.settings_store import get_setting, upsert_setting

HUMAN_TASK = "HUMAN_TASK"
OPEN_HUMAN = ("now",)
EVIDENCE_MAX_NOTE = 400
EVIDENCE_MAX_DATA_URL = 240_000

C_DEMAND_CODES = {
    "SOLD_OUT",
    "ESCALATE_COMPLAINT",
    "RESTOCK_WHO",
    "SLOW_COOK",
    "MERCHANT_CANCEL",
    "SPILL",
    "WRONG_ITEM",
    "CAPACITY_PEAK",
    "MATERIALS",
    "RECTIFY_EVIDENCE",
}

EVIDENCE_KINDS = {
    "SOLD_OUT": ("photo", "补货照片或当前库存数字"),
    "RESTOCK_WHO": ("photo", "补货照片或当前库存数字"),
    "ESCALATE_COMPLAINT": ("note", "谁处理了、怎么处理的"),
    "SLOW_COOK": ("checklist", "出餐检查表或后厨整改照片"),
    "MERCHANT_CANCEL": ("note", "商责取消原因和当场处理"),
    "SPILL": ("photo", "包装整改后的打包照片"),
    "WRONG_ITEM": ("checklist", "漏餐错餐核对表或打包照片"),
    "CAPACITY_PEAK": ("note", "加人/备料已到位的确认"),
    "MATERIALS": ("photo", "采购小票或到货照片"),
    "RECTIFY_EVIDENCE": ("note", "未完成整改的催办记录"),
}

_OPS_METRIC_MAP = {
    "cook_time": ("meal_prep_rate", "up"),
    "meal_prep_rate": ("meal_prep_rate", "up"),
    "merchant_cancel_rate": ("merchant_cancel_rate", "down"),
    "on_time_delivery_rate": ("on_time_delivery_rate", "up"),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_load(raw: str | None) -> Any:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _roster_key(store_id: str) -> str:
    return f"store_ops:{store_id}"


def _token_key(token: str) -> str:
    return f"store_ops_token:{token}"


def default_roster(store_id: str = "") -> dict[str, Any]:
    return {
        "store_id": store_id,
        "manager_name": "",
        "manager_phone": "",
        "notify_channel": "owner_relay",
        "shift_note": "",
        "task_token": "",
        "task_url": "",
        "ready": False,
    }


def load_roster(db: Session, store_id: str) -> dict[str, Any]:
    raw = get_setting(_roster_key(store_id), db)
    data = default_roster(store_id)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data.update(parsed)
        except json.JSONDecodeError:
            pass
    data["store_id"] = store_id
    data["ready"] = bool(str(data.get("manager_name") or "").strip())
    token = str(data.get("task_token") or "").strip()
    if token:
        data["task_url"] = f"/store-tasks?t={token}"
    return data


def save_roster(db: Session, store_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_roster(db, store_id)
    manager_name = str(payload.get("manager_name") or current.get("manager_name") or "").strip()[:40]
    manager_phone = str(payload.get("manager_phone") or current.get("manager_phone") or "").strip()[:32]
    notify_channel = str(payload.get("notify_channel") or current.get("notify_channel") or "owner_relay")
    if notify_channel not in {"phone", "wechat", "owner_relay"}:
        notify_channel = "owner_relay"
    shift_note = str(payload.get("shift_note") or current.get("shift_note") or "").strip()[:80]
    token = str(current.get("task_token") or "").strip() or secrets.token_urlsafe(10)
    body = {
        "store_id": store_id,
        "manager_name": manager_name,
        "manager_phone": manager_phone,
        "notify_channel": notify_channel,
        "shift_note": shift_note,
        "task_token": token,
    }
    upsert_setting(db, _roster_key(store_id), json.dumps(body, ensure_ascii=False), description="门店线下执行人")
    upsert_setting(db, _token_key(token), store_id, description="门店任务页令牌")
    db.commit()
    return load_roster(db, store_id)


def store_id_for_token(db: Session, token: str) -> str | None:
    raw = (token or "").strip()
    if not raw:
        return None
    return get_setting(_token_key(raw), db)


def is_human_task(item: ClosedLoopItem, pack: dict[str, Any] | None = None) -> bool:
    if str(getattr(item, "execution_mode", "") or "").upper() == HUMAN_TASK:
        return True
    payload = pack if isinstance(pack, dict) else {}
    if not payload and item.pack_json:
        try:
            payload = json.loads(item.pack_json)
        except json.JSONDecodeError:
            payload = {}
    return str(payload.get("execution_mode") or "").upper() == HUMAN_TASK


def evidence_list(item: ClosedLoopItem) -> list[dict[str, Any]]:
    rows = _json_load(item.evidence_json)
    return [row for row in rows if isinstance(row, dict)]


def has_evidence(item: ClosedLoopItem) -> bool:
    for row in evidence_list(item):
        if str(row.get("note") or "").strip() or str(row.get("data_url") or row.get("url") or "").strip():
            return True
    return False


def attach_evidence(
    db: Session,
    store_id: str,
    loop_id: str,
    *,
    kind: str = "note",
    note: str = "",
    data_url: str = "",
    by: str = "OWNER",
) -> ClosedLoopItem:
    item = db.get(ClosedLoopItem, loop_id)
    if item is None or item.store_id != store_id:
        raise ValueError("loop not found")
    if item.status not in {"now", "not_executed"}:
        raise ValueError("这件事不在待执行，不能再补证据")
    note = str(note or "").strip()[:EVIDENCE_MAX_NOTE]
    data_url = str(data_url or "").strip()
    if data_url and (len(data_url) > EVIDENCE_MAX_DATA_URL or not data_url.startswith("data:image")):
        raise ValueError("证据照片太大或格式不对，请传现场照片")
    if not note and not data_url:
        raise ValueError("至少写一句做了什么，或上传一张现场照片")
    kind = kind if kind in {"photo", "note", "checklist"} else "note"
    rows = evidence_list(item)
    rows.append(
        {
            "kind": kind,
            "note": note,
            "data_url": data_url[:EVIDENCE_MAX_DATA_URL] if data_url else "",
            "by": by,
            "at": _utcnow().isoformat(),
        }
    )
    item.evidence_json = json.dumps(rows, ensure_ascii=False)
    pack = {}
    try:
        pack = json.loads(item.pack_json or "{}")
    except json.JSONDecodeError:
        pack = {}
    history = pack.get("thread_history") if isinstance(pack.get("thread_history"), list) else []
    history.append({"state": "NEED_INFORMATION", "at": _utcnow().isoformat(), "note": f"已交证据：{note or '现场照片'}", "executor": by})
    pack["thread_history"] = history
    item.pack_json = json.dumps(pack, ensure_ascii=False)
    try:
        from app.services.thread_engine import sync_loop_thread

        sync_loop_thread(db, item, pack=pack)
    except Exception:  # noqa: BLE001
        pass
    db.commit()
    db.refresh(item)
    return item


def require_evidence(item: ClosedLoopItem) -> None:
    if is_human_task(item) and not has_evidence(item):
        raise ValueError("没有证据不能算门店做完。请先上传照片或写下现场处理。")


def list_open_human_tasks(db: Session, store_id: str) -> list[ClosedLoopItem]:
    rows = db.execute(
        select(ClosedLoopItem)
        .where(ClosedLoopItem.store_id == store_id, ClosedLoopItem.status.in_(OPEN_HUMAN))
        .order_by(ClosedLoopItem.created_at.desc())
    ).scalars().all()
    return [item for item in rows if is_human_task(item)]


def project_task(item: ClosedLoopItem) -> dict[str, Any]:
    pack = {}
    try:
        pack = json.loads(item.pack_json or "{}")
    except json.JSONDecodeError:
        pack = {}
    due = item.due_at.isoformat() if item.due_at else ""
    overdue = False
    if item.due_at and item.status == "now":
        due_at = item.due_at if item.due_at.tzinfo else item.due_at.replace(tzinfo=timezone.utc)
        overdue = _utcnow() > due_at
    return {
        "id": item.id,
        "title": item.title,
        "finding": item.finding,
        "judgment": item.judgment,
        "assignee_name": item.assignee_name,
        "assignee_role": item.assignee_role,
        "due_at": due,
        "overdue": overdue,
        "status": item.status,
        "evidence_count": len(evidence_list(item)),
        "has_evidence": has_evidence(item),
        "evidence_needed": str(pack.get("evidence_needed") or "现场处理说明或照片"),
        "success_metric": item.success_metric,
        "observe_hours": item.observe_hours,
    }


def nag_overdue_human_tasks(db: Session, store_id: str | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    query = select(ClosedLoopItem).where(ClosedLoopItem.status == "now", ClosedLoopItem.due_at.is_not(None))
    if store_id:
        query = query.where(ClosedLoopItem.store_id == store_id)
    nagged: list[str] = []
    for item in db.execute(query).scalars().all():
        if not is_human_task(item):
            continue
        due = item.due_at
        if due is None:
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due > now:
            continue
        if item.last_nagged_at:
            last = item.last_nagged_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < timedelta(hours=4):
                continue
        item.last_nagged_at = now
        nagged.append(item.id)
        try:
            from app.services.notification_service import notify_store_owner

            roster = load_roster(db, item.store_id)
            who = item.assignee_name or roster.get("manager_name") or "店长"
            notify_store_owner(
                db,
                store_id=item.store_id,
                notification_type="need_you",
                title=f"催办：{who}还没交「{item.title}」的证据",
                body="没有证据不能算做完。把门店任务页发给店长，或自己补一张现场照片。",
                priority="urgent",
                related_decision_id=item.id,
                suppress_if_budget_exceeded=False,
            )
        except Exception:  # noqa: BLE001
            pass
    if nagged:
        db.commit()
    return {"nagged": nagged, "count": len(nagged)}


def verify_ops_result(db: Session, item: ClosedLoopItem) -> tuple[str, str, float | None]:
    """观察窗到期：用运营指标回看，没有读数就诚实记 unknown。"""
    metric_label = str(item.success_metric or "")
    mapped = None
    direction = "down"
    for key, pair in _OPS_METRIC_MAP.items():
        if key in metric_label or metric_label == pair[0]:
            mapped, direction = pair
            break
    if mapped is None:
        if has_evidence(item):
            return "unknown", "门店已交证据，但还没有对应运营指标自动判定是否有效。", None
        return "unknown", "观察窗已到，还没有足够读数自动判定。", None

    executed = item.executed_at or _utcnow()
    if executed.tzinfo is None:
        executed = executed.replace(tzinfo=timezone.utc)
    observe_from = executed.date()
    observe_to = (item.observe_until or _utcnow()).date() if item.observe_until else executed.date()
    baseline_to = observe_from - timedelta(days=1)
    baseline_from = baseline_to - timedelta(days=6)

    def _avg(from_day, to_day) -> float | None:
        value = db.execute(
            select(OpsMetricDaily)
            .where(
                OpsMetricDaily.store_id == item.store_id,
                OpsMetricDaily.day >= from_day,
                OpsMetricDaily.day <= to_day,
            )
        ).scalars().all()
        nums = [getattr(row, mapped) for row in value if getattr(row, mapped) is not None]
        if not nums:
            return None
        return sum(float(n) for n in nums) / len(nums)

    after = _avg(observe_from, observe_to)
    before = _avg(baseline_from, baseline_to)
    if after is None or before is None or before == 0:
        return "unknown", f"门店已交证据。{mapped} 还没有足够日表读数，不能自动判定。", None
    lift = (after - before) / abs(before) * 100.0
    improved = lift > 2 if direction == "up" else lift < -2
    worsened = lift < -2 if direction == "up" else lift > 2
    if improved:
        return "positive", f"观察窗已到。{mapped} 变化 {lift:+.1f}%。整改有效。", lift
    if worsened:
        return "negative", f"观察窗已到。{mapped} 变化 {lift:+.1f}%。还没看见改善。", lift
    return "neutral", f"观察窗已到。{mapped} 变化 {lift:+.1f}%。变化不明显。", lift


def human_task_spec(demand_code: str) -> dict[str, Any]:
    kind, needed = EVIDENCE_KINDS.get(demand_code, ("note", "现场处理说明或照片"))
    return {"evidence_kind": kind, "evidence_needed": needed, "demand_code": demand_code}


def build_human_task_pack(
    *,
    title: str,
    diagnosis: str,
    action: str,
    assignee_name: str,
    demand_code: str = "",
    observe_hours: int = 24,
    metric: str = "task_done",
    guardrail: str = "",
    task_url: str = "",
) -> dict[str, Any]:
    spec = human_task_spec(demand_code)
    who = assignee_name or "店长"
    needed = spec["evidence_needed"]
    steps = [
        f"把这件事派给{who}",
        f"现场做完后提交证据：{needed}",
        "没有证据不能点「门店已做完」",
        f"{observe_hours} 小时后系统回看出餐/取消/差评等指标",
    ]
    if task_url:
        steps.insert(1, f"把门店任务页发给{who}：{task_url}")
    return {
        "action_type": "ops_hint",
        "execution_mode": HUMAN_TASK,
        "title": title,
        "object_name": demand_code or who,
        "goal": action,
        "current_problem": diagnosis,
        "copy_text": (
            f"【门店整改】{title}\n"
            f"执行人：{who}\n"
            f"要做：{action}\n"
            f"必须提交：{needed}\n"
            "口头说做了不算。交证据后进入观察窗，第二天回看有没有用。"
        ),
        "steps": steps,
        "watch": f"{observe_hours} 小时后回看 {metric}。无效就记入记忆，不要假装整改过。",
        "how_to_use": "这不是去美团改设置。这是厨房/门店实体动作。店长做完必须交证据。",
        "observe_hours": observe_hours,
        "success_metric": metric,
        "success_target": "整改后指标改善",
        "guardrail": guardrail or "不要只口头回复已经改了",
        "evidence_kind": spec["evidence_kind"],
        "evidence_needed": needed,
        "assignee_name": who,
        "requires_approval": False,
        "demand_code": demand_code,
        "task_url": task_url,
    }
