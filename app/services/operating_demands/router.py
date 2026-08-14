"""把老板原话路由到一条经营需求，不改 intent kind。"""

from __future__ import annotations

from app.services.operating_demands.catalog import DEMANDS, by_id
from app.services.operating_demands.models import OperatingDemand

_NEXT_BEST_FALLBACK = (
    "最近生意",
    "生意怎么了",
    "现在最该",
    "只该做",
    "先做什么",
    "今天只需要",
    "现在该怎么办",
    "我现在该干嘛",
)


def match_demand(text: str) -> OperatingDemand | None:
    raw = (text or "").strip()
    if not raw:
        return None

    lowered = raw.lower()
    for item in DEMANDS:
        if item.question and (item.question in raw or raw in item.question):
            return item

    best: OperatingDemand | None = None
    best_score = 0
    for item in DEMANDS:
        score = 0
        for kw in item.keywords:
            needle = kw.lower()
            if needle and needle in lowered:
                score += min(len(kw), 10)
        if score > best_score:
            best_score = score
            best = item
    if best is not None and best_score >= 4:
        return best
    if any(token in raw for token in _NEXT_BEST_FALLBACK):
        return by_id(50)
    return None
