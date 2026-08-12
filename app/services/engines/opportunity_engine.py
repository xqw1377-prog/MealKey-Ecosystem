from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from app.models.ohre import Hypothesis
from app.schemas.store_state import StoreState


@dataclass
class Opportunity:
    key: str
    title: str
    why: str
    expected_metric: str
    expected_lift_pct_low: Optional[float]
    expected_lift_pct_high: Optional[float]
    confidence: float

    def to_dict(self):
        return asdict(self)


def opportunity_engine(store_state: StoreState, hypothesis: Optional[Hypothesis]) -> list[Opportunity]:
    """
    V1 Opportunity Engine：把 diagnosis/hypothesis 变成 “最多 3 个机会点”。
    """
    if hypothesis is None:
        return []

    ops: list[Opportunity] = []

    if hypothesis.funnel_stage == "ctr":
        ops.append(
            Opportunity(
                key="ctr_competitiveness",
                title="核心商品正在丢失点击",
                why="CTR 下滑通常意味着主图/标题/价格感知在第一屏输给竞品",
                expected_metric="ctr",
                expected_lift_pct_low=6,
                expected_lift_pct_high=12,
                confidence=float(hypothesis.confidence),
            )
        )

    if hypothesis.funnel_stage == "cvr":
        ops.append(
            Opportunity(
                key="cvr_conversion",
                title="用户愿意看但不愿意买",
                why="CVR 下滑通常与套餐结构、价格、评价主题有关",
                expected_metric="cvr",
                expected_lift_pct_low=3,
                expected_lift_pct_high=8,
                confidence=float(hypothesis.confidence) - 0.05,
            )
        )

    # fallback: menu gap based on store tags
    if store_state.store.category and store_state.market.market_type:
        ops.append(
            Opportunity(
                key="menu_structure_gap",
                title="菜单结构可能存在缺口",
                why="当商圈价格带与本店 SKU 分布错位时，需要补齐套餐/价格梯度",
                expected_metric="orders",
                expected_lift_pct_low=4,
                expected_lift_pct_high=10,
                confidence=0.65,
            )
        )

    # keep Top 3
    ops = sorted(ops, key=lambda x: x.confidence, reverse=True)[:3]
    return ops

