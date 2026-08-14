"""CORS 来源解析：环境变量按逗号分隔，也兼容 JSON 数组。"""

from __future__ import annotations

import json
from typing import Any


def parse_cors_origins(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("CORS_ORIGINS JSON must be a list of origins")
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip().strip("\"'") for part in text.split(",") if part.strip().strip("\"'")]


def cors_allows_credentials(origins: list[str]) -> bool:
    """通配来源不得携带凭证，否则违反 CORS 规范。"""
    return bool(origins) and "*" not in origins
