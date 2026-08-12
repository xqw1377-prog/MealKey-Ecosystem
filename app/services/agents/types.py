from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from app.models.entities import Store
from app.models.ohre import (
    Experiment,
    Hypothesis,
    Observation,
    Recommendation,
)
from app.schemas.store_state import StoreState

@dataclass
class _ItemSnapshot:
    item_id: str
    name: str
    category: Optional[str]
    price: Optional[float]
    description: Optional[str]
    observe_orders: float
    observe_gmv: float
    observe_impressions: float
    observe_visits: float
    observe_ctr: Optional[float]
    observe_cvr: Optional[float]
    baseline_orders: float
    baseline_impressions: float
    baseline_visits: float
    baseline_ctr: Optional[float]
    baseline_cvr: Optional[float]
    orders_delta_pct: Optional[float]
    impressions_delta_pct: Optional[float]
    order_share_pct: Optional[float]
    ctr_delta_pct: Optional[float]
    cvr_delta_pct: Optional[float]
    image_url: Optional[str] = None
    role: str = "Experimental Product"
    rationale: str = ""

@dataclass
class _AgentContext:
    store: Store
    store_state: StoreState
    document_alignment: dict[str, Any]
    observations: list[Observation]
    hypothesis: Optional[Hypothesis]
    recommendations: list[Recommendation]
    experiments: list[Experiment]
    menu_items: list[dict[str, Any]]
    item_snapshots: list[_ItemSnapshot]
    generated_at: datetime
    days: int
    system_mode: str = "operating"  # operating / safe（MOS + Safe Mode）
