"""矩阵 Agent 阈值集中配置（审计 P1-1）。

把 builders.py 里散落的魔法数字收敛到这里，方便：
- 调参时不用翻业务代码；
- 后续按品类/门店覆盖（预留 category_overrides 钩子）。

所有数值都是"经验启发式"，不是统计拟合结果——改它们不会破坏逻辑，
只改变信号灵敏度。修改后建议跑 tests/test_matrix_agents.py 回归。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromoThresholds:
    impressions_down_signal_pct: float = -8.0       # 曝光下滑多少触发活动建议
    impressions_down_blocker_pct: float = -3.0      # 自然转化未稳的判定线
    natural_cvr_stable_delta: float = -5.0          # ctr/cvr delta >= 该值视为"稳"
    health_base: int = 72
    health_high_signal_penalty: int = 8
    health_medium_signal_penalty: int = 4
    health_unlock_bonus: int = 4


@dataclass(frozen=True)
class AdsThresholds:
    health_unlock_base: int = 70
    health_locked_base: int = 42
    health_hero_bonus: int = 8
    health_blocker_penalty: int = 6
    default_budget: float = 300.0
    cvr_hero_threshold: float = 0.08                # cvr 高于此值给更高 ROI 估计
    impressions_down_signal_pct: float = -5.0
    orders_down_tolerance_pct: float = -3.0


@dataclass(frozen=True)
class CrmThresholds:
    repurchase_down_signal_pct: float = -5.0        # 复购下滑多少触发召回
    low_repurchase_base: float = 0.22               # 复购底座偏低阈值
    base_population_min: int = 40
    orders_to_population_multiplier: float = 7.0
    # 代理分群占比（无真实 CRM 数据时使用）
    segment_share_new: float = 0.35
    segment_share_active: float = 0.40
    segment_share_vip: float = 0.12
    segment_share_churn_normal: float = 0.10
    segment_share_churn_down: float = 0.18
    health_base: int = 68


@dataclass(frozen=True)
class ServiceThresholds:
    pending_signal_threshold: int = 3               # 待处理负向反馈多少触发动作
    theme_signal_threshold: int = 2                 # 主题出现多少次固化话术
    negative_rating_max: float = 3.5                # 评分 <= 此值视为负向
    negative_sentiment_max: float = 0.4             # NLP sentiment < 此值视为负向
    review_load_limit: int = 60
    health_base: int = 78
    health_pending_penalty: int = 3
    health_portion_penalty: int = 2
    batch_reply_cap: int = 12


@dataclass(frozen=True)
class ReviewThresholds:
    theme_dominant_share_pct: float = 30.0          # 主题占比 >= 此值视为高严重
    theme_dominant_health_penalty: int = 8
    rating_signal_min_samples: int = 3              # 至少多少条评价才出动作
    health_rating_base: int = 40
    health_rating_multiplier: float = 12.0
    health_rating_delta_cap: int = 10
    health_rating_delta_floor: int = -15


@dataclass(frozen=True)
class StoreMatrixThresholds:
    health_base: int = 70
    orders_delta_health_cap: int = 12
    locked_health_penalty: int = 15


@dataclass(frozen=True)
class ScoreClamp:
    low: int = 20
    high: int = 98


@dataclass(frozen=True)
class MatrixThresholds:
    promo: PromoThresholds = field(default_factory=PromoThresholds)
    ads: AdsThresholds = field(default_factory=AdsThresholds)
    crm: CrmThresholds = field(default_factory=CrmThresholds)
    service: ServiceThresholds = field(default_factory=ServiceThresholds)
    review: ReviewThresholds = field(default_factory=ReviewThresholds)
    store_matrix: StoreMatrixThresholds = field(default_factory=StoreMatrixThresholds)
    clamp: ScoreClamp = field(default_factory=ScoreClamp)
    # 预留：未来按品类覆盖，例如快餐 vs 火锅的复购基线不同
    category_overrides: dict[str, dict] = field(default_factory=dict)


# 默认全局实例（大多数场景直接 import 用这个）
DEFAULT_THRESHOLDS = MatrixThresholds()


def get_thresholds(category: str | None = None) -> MatrixThresholds:
    """按品类取阈值。当前只返回默认；预留 category_overrides 接入点。"""
    if category and category in DEFAULT_THRESHOLDS.category_overrides:
        # 简单的 flat override：把 dict 里的 key 覆盖到对应 dataclass
        # （真正用到时再实现深合并，现在留钩子）
        return DEFAULT_THRESHOLDS
    return DEFAULT_THRESHOLDS
