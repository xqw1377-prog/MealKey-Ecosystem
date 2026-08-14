"""Agent Event Log — AI 执行过程的记录、重放、成本追踪。

核心原则(借鉴 dsh):
- "model-visible means logged"
- append-only: 只追加,不修改
- 重放事件 = 重建推理过程
- Agent 可以死,事件不能丢

用法:
    log = AgentEventLog(db, session_id="sess_xxx", store_id="s1", runtime="local")
    log.turn_start(question="为什么订单掉了")
    log.llm_call(model="deepseek-chat", messages=[...], token_input=1200)
    log.tool_call(tool_name="query_product", arguments={...})
    log.tool_result(tool_name="query_product", result={...}, duration_ms=230)
    log.llm_response(content="CTR下降了...", token_output=800, cost_cny=0.02)
    log.turn_end(conclusion="建议换主图")

    # 重放
    events = log.replay()
    summary = log.cost_summary()
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.agent_event import AgentEvent


class AgentEventLog:
    """Agent 执行事件日志。"""

    def __init__(
        self,
        db: Session,
        *,
        session_id: str | None = None,
        store_id: str = "",
        runtime: str = "local",
    ):
        self.db = db
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.store_id = store_id
        self.runtime = runtime
        self._step = 0

    def _emit(
        self,
        event_type: str,
        *,
        payload: Any = None,
        tool_name: str | None = None,
        duration_ms: int | None = None,
        token_input: int | None = None,
        token_output: int | None = None,
        cost_cny: float | None = None,
        error: str | None = None,
    ) -> AgentEvent:
        event = AgentEvent(
            session_id=self.session_id,
            store_id=self.store_id or None,
            event_type=event_type,
            step_index=self._step,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
            tool_name=tool_name,
            duration_ms=duration_ms,
            token_input=token_input,
            token_output=token_output,
            cost_cny=cost_cny,
            runtime=self.runtime,
            error_message=error,
            occurred_at=utc_now(),
        )
        self.db.add(event)
        self.db.flush()
        self._step += 1
        return event

    # ── 高级事件 ──

    def turn_start(self, *, question: str, context_summary: str = "") -> AgentEvent:
        return self._emit("turn_start", payload={"question": question, "context": context_summary})

    def llm_call(self, *, model: str, messages: list, token_input: int = 0) -> AgentEvent:
        # 只记录摘要,不存完整 messages(可能很大)
        return self._emit("llm_call", payload={
            "model": model,
            "message_count": len(messages),
            "roles": [m.get("role") for m in messages[-3:]],
        }, token_input=token_input)

    def llm_response(
        self, *, content: str, token_output: int = 0, cost_cny: float = 0, duration_ms: int | None = None
    ) -> AgentEvent:
        return self._emit("llm_response", payload={"content": content[:500]}, token_output=token_output, cost_cny=cost_cny, duration_ms=duration_ms)

    def tool_call(self, *, tool_name: str, arguments: dict) -> AgentEvent:
        return self._emit("tool_call", payload={"arguments": arguments}, tool_name=tool_name)

    def tool_result(self, *, tool_name: str, result: Any, duration_ms: int | None = None) -> AgentEvent:
        # 只记录摘要
        summary = result
        if isinstance(result, dict):
            summary = {k: v for k, v in list(result.items())[:5]}
        elif isinstance(result, str) and len(result) > 200:
            summary = result[:200]
        return self._emit("tool_result", payload={"result_summary": summary}, tool_name=tool_name, duration_ms=duration_ms)

    def error(self, *, message: str, context: Any = None) -> AgentEvent:
        return self._emit("error", error=message, payload={"context": context})

    def turn_end(self, *, conclusion: str, actions: list[str] | None = None) -> AgentEvent:
        return self._emit("turn_end", payload={"conclusion": conclusion, "actions": actions or []})

    # ── 查询 ──

    def replay(self) -> list[dict[str, Any]]:
        """重放整个会话的事件序列。"""
        events = list(
            self.db.execute(
                select(AgentEvent)
                .where(AgentEvent.session_id == self.session_id)
                .order_by(AgentEvent.step_index)
            ).scalars()
        )
        return [
            {
                "step": e.step_index,
                "type": e.event_type,
                "tool": e.tool_name,
                "payload": json.loads(e.payload_json) if e.payload_json else None,
                "duration_ms": e.duration_ms,
                "tokens_in": e.token_input,
                "tokens_out": e.token_output,
                "cost_cny": e.cost_cny,
                "error": e.error_message,
                "at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in events
        ]

    def cost_summary(self) -> dict[str, Any]:
        """会话成本汇总。"""
        events = list(
            self.db.execute(
                select(AgentEvent).where(AgentEvent.session_id == self.session_id)
            ).scalars()
        )
        total_tokens_in = sum(e.token_input or 0 for e in events)
        total_tokens_out = sum(e.token_output or 0 for e in events)
        total_cost = sum(e.cost_cny or 0 for e in events)
        tool_calls = sum(1 for e in events if e.event_type == "tool_call")
        llm_calls = sum(1 for e in events if e.event_type == "llm_call")
        errors = sum(1 for e in events if e.event_type == "error")
        total_duration = sum(e.duration_ms or 0 for e in events)

        return {
            "session_id": self.session_id,
            "total_events": len(events),
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "errors": errors,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "cost_cny": round(total_cost, 4),
            "total_duration_ms": total_duration,
            "runtime": self.runtime,
        }


def replay_session(db: Session, session_id: str) -> list[dict[str, Any]]:
    """静态方法:重放指定 session。"""
    log = AgentEventLog(db, session_id=session_id)
    return log.replay()


def session_cost_summary(db: Session, session_id: str) -> dict[str, Any]:
    """静态方法:获取 session 成本。"""
    log = AgentEventLog(db, session_id=session_id)
    return log.cost_summary()
