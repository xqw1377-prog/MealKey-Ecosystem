"""ContinuationPacket — Agent 能死,事情不能死。

借鉴 dsh 的 session resume + 用户提出的 ContinuationPacket 设计。

当 agent 被杀死/崩溃后,MealKey 可以:
1. 从 AgentEvent 重放推理过程
2. 从 ContinuationPacket 恢复任务状态
3. 用新 agent 继续执行

用法:
    # 保存
    packet = ContinuationPacket.save(db, work_thread_id, session_id, state)

    # 恢复
    packet = ContinuationPacket.load(db, work_thread_id)
    if packet and packet.can_resume:
        new_session = resume_from(packet)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.agent_event import AgentEvent


class ContinuationPacket:
    """任务续传包 — 记录 agent 中断时的完整状态。"""

    def __init__(
        self,
        *,
        work_thread_id: str,
        session_id: str,
        store_id: str = "",
        step_index: int = 0,
        objective: str = "",
        context_summary: str = "",
        pending_tools: list[str] | None = None,
        last_conclusion: str = "",
        runtime: str = "local",
    ):
        self.work_thread_id = work_thread_id
        self.session_id = session_id
        self.store_id = store_id
        self.step_index = step_index
        self.objective = objective
        self.context_summary = context_summary
        self.pending_tools = pending_tools or []
        self.last_conclusion = last_conclusion
        self.runtime = runtime
        self.saved_at = utc_now()

    @property
    def can_resume(self) -> bool:
        """是否可以续传。"""
        return bool(self.session_id and self.objective)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_thread_id": self.work_thread_id,
            "session_id": self.session_id,
            "store_id": self.store_id,
            "step_index": self.step_index,
            "objective": self.objective,
            "context_summary": self.context_summary,
            "pending_tools": self.pending_tools,
            "last_conclusion": self.last_conclusion,
            "runtime": self.runtime,
            "saved_at": self.saved_at.isoformat() if self.saved_at else None,
        }

    @staticmethod
    def save(
        db: Session,
        *,
        work_thread_id: str,
        session_id: str,
        store_id: str = "",
        objective: str = "",
        context_summary: str = "",
        pending_tools: list[str] | None = None,
        last_conclusion: str = "",
        runtime: str = "local",
    ) -> "ContinuationPacket":
        """保存续传包到 AgentEvent(作为特殊事件)。"""
        # 从 event log 获取当前 step
        events = list(
            db.execute(
                select(AgentEvent)
                .where(AgentEvent.session_id == session_id)
                .order_by(AgentEvent.step_index.desc())
                .limit(1)
            ).scalars()
        )
        step_index = events[0].step_index + 1 if events else 0

        packet = ContinuationPacket(
            work_thread_id=work_thread_id,
            session_id=session_id,
            store_id=store_id,
            step_index=step_index,
            objective=objective,
            context_summary=context_summary,
            pending_tools=pending_tools or [],
            last_conclusion=last_conclusion,
            runtime=runtime,
        )

        # 存为 AgentEvent (continuation 类型)
        event = AgentEvent(
            session_id=session_id,
            store_id=store_id or None,
            event_type="continuation",
            step_index=step_index,
            payload_json=json.dumps(packet.to_dict(), ensure_ascii=False),
            runtime=runtime,
            occurred_at=utc_now(),
        )
        db.add(event)
        db.commit()

        return packet

    @staticmethod
    def load(db: Session, work_thread_id: str) -> Optional["ContinuationPacket"]:
        """从 AgentEvent 恢复续传包。"""
        event = db.execute(
            select(AgentEvent)
            .where(
                AgentEvent.event_type == "continuation",
                AgentEvent.payload_json.contains(work_thread_id),
            )
            .order_by(AgentEvent.occurred_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not event or not event.payload_json:
            return None

        data = json.loads(event.payload_json)
        # 确认 work_thread_id 匹配
        if data.get("work_thread_id") != work_thread_id:
            return None

        return ContinuationPacket(
            work_thread_id=data["work_thread_id"],
            session_id=data["session_id"],
            store_id=data.get("store_id", ""),
            step_index=data.get("step_index", 0),
            objective=data.get("objective", ""),
            context_summary=data.get("context_summary", ""),
            pending_tools=data.get("pending_tools", []),
            last_conclusion=data.get("last_conclusion", ""),
            runtime=data.get("runtime", "local"),
        )


def resume_from(packet: ContinuationPacket) -> dict[str, Any]:
    """从续传包生成恢复指令。"""
    return {
        "action": "resume",
        "session_id": packet.session_id,
        "from_step": packet.step_index,
        "objective": packet.objective,
        "context": packet.context_summary,
        "last_conclusion": packet.last_conclusion,
        "pending_tools": packet.pending_tools,
        "instruction": f"继续上次未完成的任务: {packet.objective}。上次执行到第 {packet.step_index} 步,结论: {packet.last_conclusion[:100]}",
    }
