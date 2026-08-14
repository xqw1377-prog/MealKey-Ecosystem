"""Decision Flow — 对的时间，干对的事。

把经营节律 + POIE 队列投影成老板能看懂的决策流：
  now（这一刻只做这一件）→ next（下一窗）→ later（今晚/明早）

不依赖 Celery：workspace / 首页加载时按当前小时即时投影。
高峰保护：只告警，不推增长/改菜单。静默时段：不打断。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.schemas.arbiter import DecisionCard, OpsQueueBrief
from app.schemas.events import EventEngineResult, OperatingEvent
from app.services.operating_rhythm import StoreRhythm, is_in_quiet_hours, local_now, match_phase, resolve_store_rhythm

GROWTH_HINTS = (
    "投流",
    "广告",
    "cpc",
    "加预算",
    "涨价",
    "改价",
    "调价",
    "改主图",
    "换主图",
    "换图",
    "改标题",
    "报名活动",
    "放量",
    "改菜单",
)
PROTECT_HINTS = ("售罄", "闭店", "骤降", "断货", "库存", "履约", "差评爆发", "客服超时", "掉线")
CRITICAL_EVENT_TYPES = {
    "STORE_ABNORMAL_CLOSED",
    "HERO_SKU_SOLD_OUT",
    "IM_REPLY_DROP",
    "RATING_DROP",
}

PHASE_META: dict[str, dict[str, Any]] = {
    "quiet": {
        "label": "静默时段",
        "clock_why": "现在是休息窗。没有急事我不会叫你，店里的事我继续盯着。",
        "interrupt_ok": False,
        "protect": False,
        "growth_ok": False,
        "now_title": "我继续盯店，有急事再叫你",
        "now_prompt": "休息时段不推新动作。售罄、闭店这类异常除外。",
        "if_skip": "不用做任何事。",
        "next_when": "下一经营窗",
        "later_when": "开店前",
        "guide_type": "INFO",
        "owner": "ai",
        "status": "静默中",
    },
    "night_learn": {
        "label": "夜间学习",
        "clock_why": "数据刚结算完。这是学习窗，不是拍板窗——我在回收今天的实验、更新策略记忆。",
        "interrupt_ok": False,
        "protect": False,
        "growth_ok": False,
        "now_title": "我在复盘今天，明早再给你结论",
        "now_prompt": "夜间只学习、不改菜单、不加投流。",
        "if_skip": "你现在什么都不用做。",
        "next_when": "明早深度复盘",
        "later_when": "开店前检查",
        "guide_type": "INFO",
        "owner": "ai",
        "status": "学习中",
    },
    "deep_review": {
        "label": "深度复盘",
        "clock_why": "昨天的数据已经齐了。这是看清问题的时间，不是改菜单的时间。",
        "interrupt_ok": False,
        "protect": False,
        "growth_ok": False,
        "now_title": "我在把昨天看清楚",
        "now_prompt": "完整复盘后，开店前只会给你一件该拍的事。",
        "if_skip": "你现在不用拍板。等开店前那一小时。",
        "next_when": "开店前检查",
        "later_when": "高峰前拍板",
        "guide_type": "PROGRESS",
        "owner": "ai",
        "status": "复盘中",
    },
    "morning_readiness": {
        "label": "开店前检查",
        "clock_why": "开店前这一小时，改完还能赶上午餐。过了这个点再改，这一餐就赶不上了。",
        "interrupt_ok": True,
        "protect": False,
        "growth_ok": False,
        "now_title": "开店前先把卡住的事清掉",
        "now_prompt": "先确认主推、活动、库存有没有卡住。增长动作放到高峰前再拍。",
        "if_skip": "跳过的话，这一餐可能带着隐患开张：售罄、活动过期、主推没挂上。",
        "next_when": "高峰前拍板",
        "later_when": "高峰保护",
        "guide_type": "APPROVAL",
        "owner": "boss",
        "status": "现在需要你",
    },
    "lunch_nba": {
        "label": "高峰前 · 今天只拍这一板",
        "clock_why": "高峰前这一小时是今天最适合拍板的窗口。现在定，这一餐还能吃到效果。",
        "interrupt_ok": True,
        "protect": False,
        "growth_ok": True,
        "now_title": "今天只拍这一板",
        "now_prompt": "一件就够。拍完我去执行，高峰里不再找你。",
        "if_skip": "跳过的话，这一餐还是按现在的菜单和活动走，窗口过了今晚再议。",
        "next_when": "高峰保护",
        "later_when": "餐段复盘",
        "guide_type": "APPROVAL",
        "owner": "boss",
        "status": "现在需要你",
    },
    "lunch_protect": {
        "label": "高峰保护",
        "clock_why": "高峰期间只盯异常：售罄、闭店、骤降。现在改菜单或加投流，会把这一餐打乱。",
        "interrupt_ok": False,
        "protect": True,
        "growth_ok": False,
        "now_title": "高峰保护中，我只盯异常",
        "now_prompt": "不改菜单、不加投流、不推战略。有售罄或骤降我会立刻叫你。",
        "if_skip": "现在不需要你做战略决定。",
        "next_when": "餐段复盘",
        "later_when": "下一餐策略",
        "guide_type": "INFO",
        "owner": "ai",
        "status": "保护中",
    },
    "lunch_review": {
        "label": "餐段复盘",
        "clock_why": "这一餐刚过。先看有没有打到，再决定下一餐要不要调——午餐有效不代表晚餐有效。",
        "interrupt_ok": False,
        "protect": False,
        "growth_ok": False,
        "now_title": "我在看这一餐打没打到",
        "now_prompt": "有明确偏差时我才会叫你。没有的话，晚餐前再拍一板。",
        "if_skip": "没有紧急偏差，你可以先不管。",
        "next_when": "晚餐策略",
        "later_when": "晚高峰保护",
        "guide_type": "PROGRESS",
        "owner": "ai",
        "status": "复盘中",
    },
    "dinner_strategy": {
        "label": "晚餐策略",
        "clock_why": "午餐有效不代表晚餐有效。现在是独立判断晚餐要不要调的窗口。",
        "interrupt_ok": True,
        "protect": False,
        "growth_ok": True,
        "now_title": "晚餐要不要单独调一板",
        "now_prompt": "按午餐结果独立判断。不确定就先观察，不要把午餐动作原样搬过来。",
        "if_skip": "跳过的话，晚餐按现有方案走，不再临时加动作。",
        "next_when": "晚高峰保护",
        "later_when": "日终复盘",
        "guide_type": "APPROVAL",
        "owner": "boss",
        "status": "现在需要你",
    },
    "evening_review": {
        "label": "日终轻复盘",
        "clock_why": "今天的动作窗口已经关了。我把结果收好，明天开店前再拍板。",
        "interrupt_ok": False,
        "protect": False,
        "growth_ok": False,
        "now_title": "今晚不再新开动作",
        "now_prompt": "数据还没完全落地。有结果我记在右栏，明早再给你一件该做的事。",
        "if_skip": "你现在什么都不用做。",
        "next_when": "夜间学习",
        "later_when": "明早复盘",
        "guide_type": "INFO",
        "owner": "ai",
        "status": "收工中",
    },
}

RUNTIME_TO_PHASE = {
    "night_learn": "night_learn",
    "daily_deep_review": "deep_review",
    "pre_open_check": "morning_readiness",
    "pre_peak_decision": "lunch_nba",
    "peak_protect": "lunch_protect",
    "inter_peak_strategy": "lunch_review",
    "post_peak_review": "evening_review",
    "day_close": "evening_review",
}


def _now_shanghai() -> datetime:
    return local_now()


def _hour(hour: int | None) -> int:
    return hour if hour is not None else _now_shanghai().hour


def resolve_operating_phase(
    rhythm: StoreRhythm,
    *,
    hour: int | None = None,
) -> str:
    """当前经营相位。match_phase 的空隙（午后空档、静默）在这里补齐，保证永远有相位。"""
    h = _hour(hour)
    phase = match_phase(h, rhythm)
    quiet = is_in_quiet_hours(rhythm, h)
    if quiet:
        # 夜宵店的静默可能落在白天：若命中了真实高峰/拍板窗，以相位为准
        if phase in {"lunch_nba", "lunch_protect", "morning_readiness", "dinner_strategy"}:
            return phase
        # 凌晨学习 / 早晨复盘发生在休息钟点里，保留 AI 内部相位
        if phase in {"night_learn", "deep_review"}:
            return phase
        return "quiet"
    if phase:
        return phase
    lunch_end = int(rhythm.lunch_peak_end.split(":")[0])
    dinner_start = int(rhythm.dinner_peak_start.split(":")[0])
    if lunch_end <= h < dinner_start:
        return "dinner_strategy" if h >= 15 else "lunch_review"
    if 0 <= h < 2:
        return "evening_review"
    return "deep_review"


def _blob(card: DecisionCard | None) -> str:
    if card is None:
        return ""
    return " ".join(
        part
        for part in (
            card.title,
            card.why_now,
            card.ai_judgment,
            card.meta,
            card.business_impact,
        )
        if part
    ).lower()


def is_growth_action(card: DecisionCard | None) -> bool:
    text = _blob(card)
    return any(hint in text for hint in GROWTH_HINTS)


def is_protect_alert(card: DecisionCard | None) -> bool:
    if card is None:
        return False
    if card.interrupt_reason == "anomaly":
        text = _blob(card)
        return any(hint in text for hint in PROTECT_HINTS) or card.priority_score >= 80
    return any(hint in _blob(card) for hint in PROTECT_HINTS)


def _event_is_critical(event: OperatingEvent) -> bool:
    if event.severity in {"critical", "high"}:
        return True
    return event.event_type in CRITICAL_EVENT_TYPES


def _card_actions(card: DecisionCard) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in (card.actions or [])[:3]]


def _card_choices(card: DecisionCard) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for action in (card.actions or [])[:4]:
        out.append(
            {
                "id": action.kind,
                "label": action.label,
                "prompt": action.label,
                "value": action.label,
            }
        )
    return out


def _execution_pack_for_card(card: DecisionCard) -> dict[str, Any] | None:
    from app.services.execution_pack import pack_from_card

    return pack_from_card(card)


def _step_from_card(
    card: DecisionCard,
    *,
    owner: str,
    execution: str,
    if_skip: str,
    when: str = "现在",
) -> dict[str, Any]:
    return {
        "id": card.id,
        "title": card.title,
        "why_now": card.why_now or card.ai_judgment,
        "if_skip": if_skip,
        "owner": owner,
        "execution": execution,
        "when": when,
        "ai_already_did": card.ai_already_did,
        "success_metric": card.success_metric,
        "business_impact": card.business_impact,
        "choices": _card_choices(card),
        "actions": _card_actions(card),
        "source_card_id": card.id,
        "interrupt_reason": card.interrupt_reason,
        "execution_pack": _execution_pack_for_card(card),
    }


def _synthetic_step(
    *,
    phase: str,
    meta: dict[str, Any],
    title: str | None = None,
    prompt: str | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    return {
        "id": f"flow:{phase}:now",
        "title": title or meta["now_title"],
        "why_now": prompt or meta["now_prompt"],
        "if_skip": meta["if_skip"],
        "owner": "ai",
        "execution": "OBSERVE",
        "when": "现在",
        "ai_already_did": "",
        "success_metric": "",
        "business_impact": "",
        "choices": [],
        "actions": [],
        "source_card_id": "",
        "interrupt_reason": "time",
    }


def _pick_now_card(
    phase: str,
    meta: dict[str, Any],
    queue: OpsQueueBrief,
    events: EventEngineResult | None,
) -> tuple[Optional[DecisionCard], str]:
    """选出这一相位真正该出现的那一张卡。返回 (card, execution)。"""
    need_you = list(queue.need_you or [])
    working = list(queue.working or [])
    results = list(queue.results or [])
    opportunities = list(queue.opportunities or [])

    if meta["protect"]:
        alerts = [c for c in need_you if is_protect_alert(c)]
        if alerts:
            return alerts[0], "ASK_APPROVAL"
        if events:
            critical = [e for e in events.events if _event_is_critical(e) and e.status == "open"]
            if critical:
                event = critical[0]
                return (
                    DecisionCard(
                        id=f"protect:{event.id}",
                        title=event.title,
                        arbiter_state="confirm",
                        interrupt_reason="anomaly",
                        queue_bucket="need_you",
                        why_now=event.detail or "高峰里出现必须处理的异常。",
                        ai_judgment=event.estimated_impact or event.detail,
                        business_impact=event.estimated_impact or "",
                    ),
                    "ASK_APPROVAL",
                )
        return None, "OBSERVE"

    if not meta["interrupt_ok"]:
        if results:
            return results[0], "AUTO_AND_REPORT"
        if working:
            return working[0], "AUTO"
        return None, "OBSERVE"

    # 拍板窗：先 need_you，再机会，再工作中
    eligible = need_you
    if not meta["growth_ok"]:
        eligible = [c for c in eligible if not is_growth_action(c)] or eligible[:0]
        # 开店前：优先非增长的运营卡；没有则不硬推增长
        if not eligible and need_you:
            ops = [c for c in need_you if not is_growth_action(c)]
            eligible = ops
    if eligible:
        card = eligible[0]
        execution = "ASK_INFORMATION" if card.arbiter_state == "need_input" else "ASK_APPROVAL"
        return card, execution
    if meta["growth_ok"] and opportunities:
        return opportunities[0], "ASK_APPROVAL"
    if working:
        return working[0], "AUTO"
    return None, "OBSERVE"


def _next_later(
    phase: str,
    meta: dict[str, Any],
    queue: OpsQueueBrief,
    now_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    leftovers = [
        c
        for c in list(queue.need_you or []) + list(queue.opportunities or []) + list(queue.working or [])
        if c.id != now_id
    ]
    next_card = leftovers[0] if leftovers else None
    later_card = leftovers[1] if len(leftovers) > 1 else None
    nxt = {
        "id": next_card.id if next_card else f"flow:{phase}:next",
        "title": next_card.title if next_card else meta["next_when"],
        "when": meta["next_when"],
        "why": (next_card.why_now if next_card else "到点我再叫你，现在先把眼前这件事做完。"),
        "owner": "boss" if next_card and next_card.queue_bucket == "need_you" else "ai",
    }
    later = {
        "id": later_card.id if later_card else f"flow:{phase}:later",
        "title": later_card.title if later_card else meta["later_when"],
        "when": meta["later_when"],
        "why": (later_card.why_now if later_card else "不在这一窗，先放着。"),
        "owner": "ai",
    }
    return nxt, later


def _auto_doing(queue: OpsQueueBrief, *, protect: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if protect:
        items.append({"title": "盯售罄 / 闭店 / 骤降", "status": "running"})
    for card in list(queue.working or [])[:3]:
        items.append({"title": card.title, "status": "running", "id": card.id})
    # 去重
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = item.get("id") or item["title"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:4]


def _guide_from_flow(
    *,
    phase: str,
    meta: dict[str, Any],
    now: dict[str, Any],
    interrupt_ok: bool,
) -> dict[str, Any]:
    owner = now.get("owner") or meta["owner"]
    execution = now.get("execution") or "OBSERVE"
    real = bool(now.get("source_card_id"))
    if real and owner == "boss" and interrupt_ok:
        guide_type = "QUESTION" if execution == "ASK_INFORMATION" else "APPROVAL"
        status = "现在需要你"
    else:
        guide_type = "INFO" if not real else ("PROGRESS" if owner == "ai" else meta["guide_type"])
        status = meta["status"]
    choices = list(now.get("choices") or [])
    if real and guide_type in {"APPROVAL", "QUESTION"} and not choices:
        choices = [
            {"id": "adopt", "label": "按这个做", "prompt": f"按「{now.get('title') or ''}」做", "value": "按这个做"},
            {"id": "defer", "label": "先放一放", "prompt": "这件事先放一放，先盯着就行", "value": "先放一放"},
        ]
    return {
        "id": now.get("id") or f"flow:{phase}",
        "type": guide_type,
        "title": now.get("title") or meta["now_title"],
        "prompt": now.get("why_now") or meta["now_prompt"],
        "explanation": now.get("ai_already_did") or meta["clock_why"],
        "success_metric": now.get("success_metric") or "",
        "choices": choices,
        "actions": list(now.get("actions") or []),
        "allow_free_text": guide_type in {"APPROVAL", "QUESTION"},
        "allow_file": False,
        "trigger_reason": "TIME" if now.get("interrupt_reason") == "time" else str(now.get("interrupt_reason") or "TIME").upper(),
        "status": status,
        "request_label": status,
        "phase": phase,
        "phase_label": meta["label"],
        "clock_why": meta["clock_why"],
        "if_skip": now.get("if_skip") or meta["if_skip"],
        "execution_pack": now.get("execution_pack"),
    }


def build_decision_flow(
    *,
    queue: OpsQueueBrief,
    events: EventEngineResult | None = None,
    db: Session | None = None,
    store_id: str = "",
    hour: int | None = None,
    rhythm: StoreRhythm | None = None,
) -> dict[str, Any]:
    """投影当前决策流。纯函数为主，db 只用来读门店节律。"""
    if rhythm is None:
        if db is not None and store_id:
            rhythm = resolve_store_rhythm(db, store_id)
        else:
            rhythm = StoreRhythm()
    h = _hour(hour)
    quiet = is_in_quiet_hours(rhythm, h)
    phase = resolve_operating_phase(rhythm, hour=h)
    meta = PHASE_META.get(phase) or PHASE_META["deep_review"]
    protect = bool(meta["protect"])
    interrupt_ok = bool(meta["interrupt_ok"])

    now_card, execution = _pick_now_card(phase, meta, queue, events)
    if db is not None and store_id and interrupt_ok:
        try:
            from app.services.operating_clock import apply_nba_pin, load_nba_pin

            pinned = apply_nba_pin(queue, load_nba_pin(db, store_id, phase))
            if pinned is not None:
                now_card = pinned
                execution = "ASK_INFORMATION" if pinned.arbiter_state == "need_input" else "ASK_APPROVAL"
        except Exception:  # noqa: BLE001
            pass
    # 保护 / 静默：增长卡不能成为 now
    if now_card and (protect or quiet or not meta["growth_ok"]) and is_growth_action(now_card) and not is_protect_alert(now_card):
        now_card = None
        execution = "OBSERVE"

    if now_card and (interrupt_ok or is_protect_alert(now_card)):
        owner = "boss" if now_card.queue_bucket == "need_you" or now_card.arbiter_state in {"confirm", "need_input"} else "ai"
        if protect and is_protect_alert(now_card):
            interrupt_ok = True
            owner = "boss"
        now = _step_from_card(
            now_card,
            owner=owner,
            execution=execution,
            if_skip=meta["if_skip"] if not is_protect_alert(now_card) else "现在不处理，这一餐可能继续漏单或停业。",
        )
    else:
        now = _synthetic_step(phase=phase, meta=meta)
        interrupt_ok = False

    nxt, later = _next_later(phase, meta, queue, str(now.get("id") or ""))
    auto_doing = _auto_doing(queue, protect=protect)
    guide = _guide_from_flow(phase=phase, meta=meta, now=now, interrupt_ok=interrupt_ok)

    return {
        "phase": phase,
        "phase_label": meta["label"],
        "clock_why": meta["clock_why"],
        "hour": h,
        "quiet": quiet and phase == "quiet",
        "protect_mode": protect,
        "interrupt_ok": interrupt_ok,
        "growth_ok": bool(meta["growth_ok"]),
        "now": now,
        "next": nxt,
        "later": later,
        "auto_doing": auto_doing,
        "guide": guide,
    }


def attach_decision_flow(guide: dict[str, Any], flow: dict[str, Any]) -> dict[str, Any]:
    """把决策流挂到中栏 guide 上，前端只读这一份。"""
    merged = dict(guide or {})
    flow_guide = flow.get("guide") or {}
    merged.setdefault("id", flow_guide.get("id"))
    merged["decision_flow"] = flow
    merged["phase"] = flow.get("phase")
    merged["phase_label"] = flow.get("phase_label")
    merged["clock_why"] = flow.get("clock_why")
    now = flow.get("now") or {}
    merged["if_skip"] = now.get("if_skip") or flow_guide.get("if_skip")
    if not merged.get("actions") and flow_guide.get("actions"):
        merged["actions"] = flow_guide["actions"]
    if not merged.get("choices") and flow_guide.get("choices"):
        merged["choices"] = flow_guide["choices"]
    if now.get("execution_pack") and not merged.get("execution_pack"):
        merged["execution_pack"] = now["execution_pack"]
    now_id = str(now.get("id") or now.get("source_card_id") or "").strip()
    if now_id:
        merged["id"] = now_id
    return merged
