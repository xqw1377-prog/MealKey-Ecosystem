"""MealKey 大模型智能引擎 — 独立部署副本（不依赖主仓进程）。"""

from app.services.llm_engine.client import ChatMessage, ChatResult
from app.services.llm_engine.gateway import LlmResult, call_llm, is_llm_configured, llm_status

__all__ = [
    "call_llm",
    "is_llm_configured",
    "llm_status",
    "LlmResult",
    "ChatMessage",
    "ChatResult",
]
