"""把 POIE 队列投影为右栏「AI 主动经营流」。"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Optional

from app.schemas.arbiter import (
    DecisionCard,
    OpsQueueBrief,
    ProactiveDomain,
    ProactiveEvent,
    ProactiveReason,
    ProactiveStatus,
)

_REASON_MAP: dict[str, ProactiveReason] = {
    "time": "TIME",
    "anomaly": "ANOMALY",
    "history": "CONTINUATION",
    "opportunity": "OPPORTUNITY",
    "goal": "GOAL_DEVIATION",
    "result": "RESULT",
    "understanding": "UNDERSTANDING",
}

_LABEL: dict[ProactiveReason, str] = {
    "TIME": "时间节点",
    "ANOMALY": "异常发现",
    "CONTINUATION": "继续上次的事",
    "OPPORTUNITY": "机会出现",
    "GOAL_DEVIATION": "目标偏差",
    "RESULT": "结果出来了",
    "UNDERSTANDING": "需要你告诉我",
}

_DOMAIN_LABEL: dict[ProactiveDomain, str] = {
    "PLATFORM": "平台与数据",
    "PRODUCT": "商品与店铺",
    "COMPETITION": "竞争与排名",
    "TRAFFIC": "流量与活动",
    "PROFIT": "订单与利润",
    "CUSTOMER": "用户经营",
    "REVIEW": "评价与客服",
    "STORE_GROWTH": "线上店增长",
}

_DOMAIN_HINTS: list[tuple[ProactiveDomain, tuple[str, ...]]] = [
    ("REVIEW", ("评价", "差评", "好评", "评分", "申诉", "客服", "回复")),
    ("CUSTOMER", ("用户", "老客", "复购", "召回", "流失", "高价值", "RFM")),
    ("STORE_GROWTH", ("一店多开", "线上店", "新店", "矩阵", "蚕食", "第二店", "第二线上店")),
    ("TRAFFIC", ("投流", "广告", "cpc", "曝光", "点击", "ctr", "cvr", "roi", "预算")),
    ("COMPETITION", ("竞品", "商圈", "排名", "top", "榜单", "首位", "第一眼点击")),
    ("PLATFORM", ("美团", "饿了么", "平台", "补贴", "活动", "授权", "履约", "售罄", "库存", "im")),
    ("PROFIT", ("利润", "到手", "毛利", "gmv", "订单", "客单", "转化漏斗")),
    ("PRODUCT", ("商品", "菜单", "sku", "主图", "图片", "标题", "套餐", "装修", "首屏")),
]


def _status_for(card: DecisionCard) -> ProactiveStatus:
    if card.queue_bucket == "need_you" or card.arbiter_state in {"confirm", "need_input"}:
        return "need_you"
    if card.arbiter_state == "auto_do":
        return "auto_done"
    if card.queue_bucket == "result" or card.arbiter_state == "report_result":
        return "done"
    if card.queue_bucket == "opportunity":
        return "analyzing"
    if card.queue_bucket == "working":
        return "observing"
    return "no_action"


def _owner_for(status: ProactiveStatus) -> str:
    if status == "need_you":
        return "boss"
    if status in {"auto_done", "done", "observing", "analyzing"}:
        return "ai"
    return "shared"


def _card_blob(card: DecisionCard) -> str:
    return " ".join(
        part
        for part in [
            card.title,
            card.why_now,
            card.ai_judgment,
            card.ai_already_did,
            card.need_from_owner,
            card.business_impact,
            card.meta,
            card.success_metric,
            *list(card.evidence or []),
        ]
        if part
    )


def _infer_domain_from_text(text: str) -> ProactiveDomain:
    haystack = text.lower()
    for domain, hints in _DOMAIN_HINTS:
        if any(token in haystack for token in hints):
            return domain
    return "PRODUCT"


def _infer_domain(card: DecisionCard) -> ProactiveDomain:
    if card.interrupt_reason == "understanding":
        key_blob = f"{card.id} {card.title} {card.ai_judgment}".lower()
        if "ads_daily_budget" in key_blob:
            return "TRAFFIC"
        if "profit_floor" in key_blob or "hero_item_floor_price" in key_blob:
            return "PROFIT"
        if "competitor_focus" in key_blob:
            return "COMPETITION"
        if "low_risk_auto" in key_blob:
            return "REVIEW"
        return "PLATFORM"
    return _infer_domain_from_text(_card_blob(card))


def _extract_object_name(card: DecisionCard, domain: ProactiveDomain) -> str:
    title = card.title or ""
    quoted = re.search(r"[“\"]([^”\"]{2,20})[”\"]", title)
    if quoted:
        return quoted.group(1)
    product_match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]{2,16}(?:牛肉饭|盖饭|套餐|主图|活动|排名|评价|投放|预算|线上店|新店))", title)
    if product_match:
        return product_match.group(1)
    if domain == "PLATFORM":
        platform_match = re.search(r"(美团|饿了么|平台活动|午餐活动|午餐补贴)", title)
        if platform_match:
            return platform_match.group(1)
    return ""


def _finding_for(card: DecisionCard) -> str:
    return (
        card.why_now
        or (card.evidence[0] if card.evidence else "")
        or card.summary
        or card.business_impact
        or ""
    )


def _decision_for(card: DecisionCard) -> str:
    return card.ai_judgment or card.summary or ""


def _action_for(card: DecisionCard, status: ProactiveStatus) -> str:
    if status == "need_you" and card.need_from_owner:
        return card.need_from_owner
    if card.ai_already_did:
        return card.ai_already_did
    return card.need_from_owner or ""


def _impact_for(card: DecisionCard) -> str:
    return card.business_impact or card.success_metric or card.meta or ""


def _next_check_for(card: DecisionCard) -> str:
    if card.next_check:
        return card.next_check
    if card.observation_window_hours and card.observation_window_hours > 0:
        return f"{card.observation_window_hours} 小时后复看"
    return ""


def _card_to_event(card: DecisionCard, occurred_at: datetime) -> ProactiveEvent:
    reason = _REASON_MAP.get(card.interrupt_reason or "anomaly", "ANOMALY")
    status = _status_for(card)
    domain = _infer_domain(card)
    return ProactiveEvent(
        id=card.id,
        reason=reason,
        domain=domain,
        occurred_at=occurred_at,
        summary=card.title,
        object_name=_extract_object_name(card, domain),
        why_now=card.why_now or "",
        finding=_finding_for(card),
        decision=_decision_for(card),
        action=_action_for(card, status),
        owner=_owner_for(status),  # type: ignore[arg-type]
        status=status,
        human_required=status == "need_you",
        business_impact=_impact_for(card),
        next_check=_next_check_for(card),
        related_workthread=card.id,
        label=_LABEL.get(reason, reason),
        domain_label=_DOMAIN_LABEL.get(domain, domain),
    )


def build_proactive_feed(
    queue: Optional[OpsQueueBrief],
    *,
    now: Optional[datetime] = None,
) -> list[ProactiveEvent]:
    if not queue:
        return []
    stamp = now or datetime.now(timezone.utc)
    # 需要你的排前，其余按原队列顺序交错；同 id 去重
    ordered: list[DecisionCard] = []
    seen: set[str] = set()
    for bucket in (queue.need_you, queue.results, queue.working, queue.opportunities):
        for card in bucket or []:
            if not card or card.id in seen:
                continue
            seen.add(card.id)
            ordered.append(card)

    # 目标偏差：有 active_goal 且带阻塞/判断时补一条
    events = [_card_to_event(c, stamp) for c in ordered[:12]]
    if queue.active_goal and queue.active_goal.blocked_by:
        gid = f"goal:{queue.active_goal.title}"
        if gid not in seen:
            goal_text = " ".join(
                part for part in [queue.active_goal.title, queue.active_goal.blocked_by, queue.active_goal.ai_judgment] if part
            )
            domain = _infer_domain_from_text(goal_text)
            events.append(
                ProactiveEvent(
                    id=gid,
                    reason="GOAL_DEVIATION",
                    domain=domain,
                    occurred_at=stamp,
                    summary=queue.active_goal.title,
                    object_name=_extract_object_name(
                        DecisionCard(
                            id=gid,
                            title=queue.active_goal.title,
                            arbiter_state="confirm",
                            queue_bucket="goal",
                        ),
                        domain,
                    ),
                    why_now=queue.active_goal.blocked_by,
                    finding=queue.active_goal.blocked_by,
                    decision=queue.active_goal.ai_judgment or queue.active_goal.progress_summary or "",
                    action=queue.active_goal.next_step or "我正在重新制定补救路径",
                    owner="ai",
                    status="analyzing",
                    human_required=False,
                    next_check="下一轮目标复盘时更新",
                    label=_LABEL["GOAL_DEVIATION"],
                    domain_label=_DOMAIN_LABEL.get(domain, domain),
                )
            )

    return events[:14]
