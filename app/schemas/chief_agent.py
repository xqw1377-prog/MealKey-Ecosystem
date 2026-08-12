"""Chief Agent (AI 店长) 响应 schema。"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChiefAgentResponse(BaseModel):
    """店长 agent 的统一回答结构。

    设计原则（对齐产品文档）：
    - 先结论（conclusion），再理由（reasons），再动作（actions），再预期影响（expected）；
    - agents_called 透明记录调度了哪些专业 agent（可审计、前端可展示）；
    - mode 标识本次回答走 LLM ReAct 还是规则降级；
    - llm 携带 provider/model/tokens 供观测。
    """

    question: str
    question_type: str = "general"  # diagnosis/competition/menu/product/review/growth/...
    mode: str = "react"  # react | rule_fallback | heuristic | clarification
    conclusion: str = ""
    reasons: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    expected: str = ""
    confidence: str = "high"  # high | medium | low
    agents_called: list[str] = Field(default_factory=list)
    answer: str = ""  # 完整自然语言回答（前端可直接展示）
    llm: Optional[dict[str, Any]] = None  # provider/model/latency_ms/tokens/failover_used
    error: Optional[str] = None  # 降级时的错误原因（不抛给用户，记录观测）
    decision: Optional[dict[str, Any]] = None  # 单一经营对象
    execution_tier: Optional[str] = None  # draft | confirm | writeback
