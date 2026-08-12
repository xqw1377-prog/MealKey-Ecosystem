from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.services.llm_engine.bindings import (
    is_purpose_chain_configured,
    resolve_candidate_api_key,
    resolve_purpose_model_chain,
)
from app.services.llm_engine.client import ChatMessage, chat_completion
from app.services.llm_engine.failover import execute_with_failover


@dataclass
class LlmResult:
    ok: bool
    content: str = ""
    purpose: str = "general.consulting"
    provider: str = ""
    model: str = ""
    model_slug: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    failover_used: bool = False
    reason: str = ""
    fallback_to_heuristic: bool = False
    attempts: list[dict[str, Any]] | None = None
    # function calling 扩展（默认 None，纯文本调用时无变化）
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str | None = None


def is_llm_configured(purpose: str = "general.consulting") -> bool:
    return is_purpose_chain_configured(purpose)


def call_llm(
    *,
    messages: list[dict[str, str]],
    purpose: str = "general.consulting",
    temperature: float = 0.4,
    max_tokens: int = 2048,
    prefer_model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> LlmResult:
    """调用 LLM。tools/tool_choice 默认 None，行为与旧版完全一致。

    messages 支持完整 OpenAI 消息格式：除 role/content 外，可携带
    tool_calls / tool_call_id / name（function calling 多轮对话用）。
    """
    started = time.perf_counter()

    def _run(candidate, api_key: str):
        chat_messages = [
            ChatMessage(
                role=m.get("role", "user"),
                content=m.get("content"),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
            )
            for m in messages
        ]
        return chat_completion(
            api_key=api_key,
            base_url=candidate.base_url,
            model=candidate.model,
            messages=chat_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )

    outcome = execute_with_failover(purpose=purpose, run=_run, prefer_model=prefer_model)
    latency_ms = int((time.perf_counter() - started) * 1000)
    attempts = [
        {
            "candidate_id": row.candidate_id,
            "provider": row.provider,
            "model": row.model,
            "ok": row.ok,
            "detail": row.detail,
        }
        for row in outcome.attempts
    ]

    if not outcome.ok or outcome.candidate is None or outcome.value is None:
        return LlmResult(
            ok=False,
            purpose=purpose,
            fallback_to_heuristic=True,
            failover_used=outcome.failover_used,
            reason=outcome.reason or "all_candidates_failed",
            attempts=attempts,
            latency_ms=latency_ms,
        )

    chat = outcome.value
    # 纯文本模式：content 为空视为失败（保持旧行为）
    # function calling 模式：content 可能为空但 tool_calls 非空，视为成功
    if not getattr(chat, "content", "") and not getattr(chat, "tool_calls", None):
        return LlmResult(
            ok=False,
            purpose=purpose,
            fallback_to_heuristic=True,
            failover_used=outcome.failover_used,
            reason="empty_content",
            attempts=attempts,
            latency_ms=latency_ms,
        )

    return LlmResult(
        ok=True,
        content=chat.content,
        purpose=purpose,
        provider=outcome.candidate.provider,
        model=outcome.candidate.model,
        model_slug=outcome.candidate.id,
        latency_ms=latency_ms,
        prompt_tokens=chat.prompt_tokens,
        completion_tokens=chat.completion_tokens,
        total_tokens=chat.total_tokens,
        failover_used=outcome.failover_used,
        reason="ok",
        attempts=attempts,
        tool_calls=chat.tool_calls,
        finish_reason=chat.finish_reason,
    )


def llm_status() -> dict[str, Any]:
    purposes = (
        "general.consulting",
        "general.polish",
        "menu.analysis",
        "brand.structured_output",
        "space.structured_output",
    )
    return {
        "configured": is_llm_configured(),
        "standalone": True,
        "depends_on_main_repo": False,
        "engine": "mealky-llm-engine-v1",
        "source": "standalone-copy-of-Mealkey-Ai/llm-engine",
        "function_calling_supported": True,
        "purposes": {
            purpose: {
                "configured": is_purpose_chain_configured(purpose),
                "candidates": [
                    {
                        "id": c.id,
                        "provider": c.provider,
                        "model": c.model,
                        "base_url": c.base_url,
                        "has_key": bool(resolve_candidate_api_key(c)),
                    }
                    for c in resolve_purpose_model_chain(purpose)
                ],
            }
            for purpose in purposes
        },
    }
