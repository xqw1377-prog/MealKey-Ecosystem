"""把 CandidateAction 仲裁成 DecisionCard，并合并进经营队列。"""

from __future__ import annotations

from app.schemas.arbiter import DecisionAction, DecisionCard, OpsQueueBrief
from app.schemas.poie import CandidateAction

# 低于此分：知道但不打扰
_INTERRUPT_THRESHOLD = 42.0


def candidate_to_card(candidate: CandidateAction) -> DecisionCard | None:
    state = candidate.suggested_state
    priority = candidate.score.priority

    if state == "noop" or (state == "auto_do" and priority < 25):
        # auto_do 仍可进入 working；noop 直接丢弃
        if state == "noop":
            return None

    if state in {"confirm", "need_input"} and priority < _INTERRUPT_THRESHOLD:
        return None

    if state == "auto_do":
        bucket = "working"
    elif state == "report_result":
        bucket = "result"
    elif candidate.trigger == "opportunity":
        bucket = "opportunity"
    elif candidate.trigger == "goal":
        bucket = "need_you"
    else:
        bucket = "need_you" if state in {"confirm", "need_input"} else "working"

    actions: list[DecisionAction] = []
    if bucket == "need_you":
        if state == "need_input" or candidate.trigger == "understanding":
            actions = [
                DecisionAction(label="在下方告诉我", kind="focus_intent", class_name="primary"),
                DecisionAction(label="稍后再说", kind="focus_intent", class_name="ghost"),
            ]
        else:
            actions = [
                DecisionAction(label="交给 MealKey 执行", kind="focus_intent", class_name="primary"),
                DecisionAction(label="先说说你的顾虑", kind="focus_intent", class_name="ghost"),
                DecisionAction(label="先不处理", kind="focus_intent", class_name="ghost"),
            ]
    elif bucket == "opportunity":
        actions = [
            DecisionAction(label="可以，你去推进", kind="focus_intent", class_name="primary"),
            DecisionAction(label="先记下", kind="focus_intent", class_name="ghost"),
        ]

    need_copy = "不需要你操作。"
    if bucket == "need_you":
        need_copy = (
            "在下方用一句话告诉我就行。"
            if state == "need_input" or candidate.trigger == "understanding"
            else "需要你确认或协助。"
        )

    return DecisionCard(
        id=candidate.id,
        title=candidate.title,
        arbiter_state=state if state != "noop" else "auto_do",
        interrupt_reason=candidate.interrupt_reason,
        queue_bucket=bucket,  # type: ignore[arg-type]
        priority_score=priority,
        why_now=candidate.why_now,
        ai_judgment=candidate.insight,
        ai_already_did=candidate.already_did,
        need_from_owner=need_copy,
        success_metric=candidate.success_metric,
        summary=candidate.insight[:120],
        meta=candidate.trigger,
        actions=actions,
    )


def merge_candidates_into_queue(
    queue: OpsQueueBrief,
    candidates: list[CandidateAction],
) -> OpsQueueBrief:
    """仲裁候选并合并；保持「少打扰」：need_you 最多 3。"""
    cards = [c for c in (candidate_to_card(x) for x in candidates) if c]
    seen = {c.title for c in queue.need_you + queue.working + queue.results + queue.opportunities}

    for card in sorted(cards, key=lambda c: c.priority_score, reverse=True):
        if card.title in seen:
            continue
        seen.add(card.title)
        if card.queue_bucket == "need_you":
            queue.need_you.append(card)
        elif card.queue_bucket == "working":
            queue.working.append(card)
        elif card.queue_bucket == "result":
            queue.results.append(card)
        elif card.queue_bucket == "opportunity":
            queue.opportunities.append(card)

    # 重新按优先级排序并截断
    before = len(queue.need_you)
    queue.need_you = sorted(queue.need_you, key=lambda c: c.priority_score, reverse=True)[:3]
    queue.filtered_noop_count += max(0, before - len(queue.need_you))
    queue.working = queue.working[:6]
    queue.results = queue.results[:4]
    queue.opportunities = queue.opportunities[:2]
    return queue
