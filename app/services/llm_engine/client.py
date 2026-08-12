from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    """一条对话消息。

    tool_calls / tool_call_id / name 仅在 function calling 场景使用：
    - assistant 发起工具调用时，tool_calls 非空
    - tool 角色回传工具结果时，tool_call_id 标记对应哪次调用
    - name 携带工具名（部分 provider 要求）
    """
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """序列化为 provider 请求体里的 message 对象，只保留非空字段。"""
        msg: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        # tool 角色必须有 tool_call_id，不能有 content
        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            msg["name"] = self.name
        if self.tool_calls is not None:
            msg["tool_calls"] = self.tool_calls
        # content 可以为 None（assistant 发起 tool_call 时 provider 允许 content=null）
        if self.role == "assistant" and self.tool_calls and "content" not in msg:
            msg["content"] = None
        return msg


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str | None = None


def chat_completion(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[ChatMessage],
    temperature: float = 0.4,
    max_tokens: int = 2048,
    timeout_seconds: int = 60,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> ChatResult:
    """调用 OpenAI 兼容的 chat/completions 端点。

    tools / tool_choice 默认 None，此时行为与旧版完全一致（纯文本对话）。
    传入 tools 后，provider 会按需返回 tool_calls（原生 function calling）。
    """
    endpoint = base_url.rstrip("/") + "/chat/completions"
    is_kimi_k3 = model.startswith("kimi-k3")
    is_gpt5 = model.lower().startswith("gpt-5")

    payload: dict[str, Any] = {
        "model": model,
        "messages": [m.to_payload() for m in messages],
        "stream": False,
    }
    if is_gpt5:
        payload["max_completion_tokens"] = max_tokens
    elif is_kimi_k3:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = 1
        payload["reasoning_effort"] = "low"
    else:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = temperature

    # function calling：仅在传入 tools 时附加（默认不破坏旧调用）
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "MealKey-Ecosystem-LlmEngine/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"llm_http_{exc.code}: {detail[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"llm_unreachable: {exc.reason}") from exc

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = (message.get("content") or "").strip() or (message.get("reasoning_content") or "").strip()
    tool_calls = message.get("tool_calls") or None
    finish_reason = choice.get("finish_reason")
    usage = data.get("usage") or {}
    return ChatResult(
        content=content,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        raw=data,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
    )
