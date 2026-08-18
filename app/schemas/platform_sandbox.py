"""PLATFORM-SB-01 — Delivery Sandbox contracts.

Test platform only. Sandbox facts never become production Business Truth.
Twin worlds exist so Incremental Result can be treatment − control, not before/after.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SandboxOp = Literal[
    "update_product_title",
    "update_product_image",
    "reply_review",
    "inject_orders",
    "inject_review",
    "simulate_tick",
]

SandboxScenario = Literal[
    "order_drop",
    "order_rise",
    "sku_stockout",
    "negative_review",
    "price_changed",
]

SandboxVerdict = Literal["PASS", "PASS_WITH_LIMITS", "REWORK", "STOP"]


class SandboxStoreState(BaseModel):
    store_id: str
    role: Literal["treatment", "control"]
    titles: dict[str, str] = Field(default_factory=dict)
    images: dict[str, str] = Field(default_factory=dict)
    reviews: dict[str, dict[str, Any]] = Field(default_factory=dict)
    orders: int = 0
    gmv: float = 0.0
    paused_skus: list[str] = Field(default_factory=list)


class WriteReceipt(BaseModel):
    ok: bool
    op: SandboxOp
    store_id: str
    expected: dict[str, Any] = Field(default_factory=dict)
    applied: dict[str, Any] = Field(default_factory=dict)
    read_back: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class TwinWorld(BaseModel):
    world_id: str
    seed: int = 1
    created_at: datetime
    treatment_store_id: str
    control_store_id: str
    ticks: int = 0
    source: Literal["sandbox"] = "sandbox"


class ContrastReport(BaseModel):
    world_id: str
    treatment_orders: int
    control_orders: int
    observed_lift_pct: Optional[float] = None
    incremental_orders: int
    evidence_grade: Literal["L0_RESEARCH"] = "L0_RESEARCH"
    may_authorize: bool = False
    may_rank_production: bool = False
    notes: str = ""
