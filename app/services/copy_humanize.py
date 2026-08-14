"""前台经营文案：技术字段名不得出现在老板界面。"""

from __future__ import annotations

import re

_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"baseline_window", "基线期"),
    (r"benchmark_window", "对照期"),
    (r"delta_pct", "变化"),
    (r"\bCTR\b", "点击率"),
    (r"\bctr\b", "点击率"),
    (r"\bCVR\b", "转化率"),
    (r"\bcvr\b", "转化率"),
    (r"\bGMV\b", "营业额"),
    (r"\bgmv\b", "营业额"),
    (r"\bSKU\b", "商品"),
    (r"\bsku\b", "商品"),
    (r"impressions", "曝光"),
    (r"\bvisits\b", "进店"),
    (r"\borders\b", "订单"),
    (r"benchmark", "对照"),
)


def humanize_operator_text(text: str | None) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for pattern, repl in _REPLACEMENTS:
        value = re.sub(pattern, repl, value, flags=re.IGNORECASE)
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("较 ", "较").replace(" 下降", "下降").replace(" 上升", "上升")
    return value


def looks_like_jargon(text: str | None) -> bool:
    raw = str(text or "")
    return bool(
        re.search(
            r"baseline_window|\bctr\b|\bcvr\b|\bgmv\b|\bsku\b|delta_pct",
            raw,
            flags=re.IGNORECASE,
        )
    )
