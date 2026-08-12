"""Merchant Understanding Engine — 商家理解契约（非传统 Settings 表单）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.content_engine import ChecklistAskPolicy, ChecklistBlockingMode, OperatingDomain

KnowledgeTier = Literal["known", "inferred", "must_ask"]
OnboardingStage = Literal[
    "connect",
    "reading",
    "interview",
    "operating",
]
PriorityStyle = Literal["profit", "orders", "rank", "balanced"]
SystemMode = Literal["operating", "safe"]  # operating=正常 / safe=缺关键信息时降级


class InfoFieldMeta(BaseModel):
    """信息字段元数据：每个经营信息项的属性（Content Engine V1 规格）。

    让 AI 知道"这个信息我有多确定、多久会变、谁需要它、缺失会不会阻塞、值不值得问"。
    """

    key: str
    label: str = ""
    domain: Optional[OperatingDomain] = None
    value: Any = None
    source: Literal["platform", "user", "inferred", "file", "experiment", "default"] = "default"
    source_priority: list[str] = Field(default_factory=list)
    confidence: float = 0.5  # 0-1
    last_verified_at: Optional[str] = None  # ISO date
    first_required_at: Optional[str] = None
    expires_at: Optional[str] = None  # 绝对过期时间（Content Engine V1 补全）
    volatility_days: Optional[int] = None  # 多久可能变化（None=稳定）
    stage: Literal["bootstrap", "early_learning", "contextual", "dynamic"] = "dynamic"
    required_for: list[str] = Field(default_factory=list)  # 哪些决策需要它
    used_by: list[str] = Field(default_factory=list)
    blocking: bool = False  # 缺失是否阻止 AI 行动
    blocking_mode: ChecklistBlockingMode = "none"
    ask_policy: ChecklistAskPolicy = "ask_contextual"
    stale_after: Optional[str] = None
    fallback: str = ""
    ask_score: Optional[float] = None  # 提问优先级分（Ask Engine 产出）


class ContextFact(BaseModel):
    """场景化短生命周期信息（Content Engine V1 §04 Stage 2）。

    例如"今天午高峰备料多 30%""炸锅坏了""店长请假"。
    过了 valid_until 自动失效，不记成长期偏好。
    """

    key: str
    value: str
    valid_from: Optional[str] = None  # ISO datetime
    valid_until: Optional[str] = None  # ISO datetime，过了自动失效
    source: str = "user"  # user / detected / platform
    category: Literal["inventory", "staff", "equipment", "menu_change", "hours", "weather", "other"] = "other"


class InferredFact(BaseModel):
    """B 类：AI 推断，等老板纠正或默认采纳。"""

    key: str
    value: Any = None
    label: str = ""
    confidence: float = 0.6
    confirmed: bool = False
    source: str = "inference"


class GapQuestion(BaseModel):
    """C 类：必须问的一项；一次只抛一个。"""

    key: str
    question: str
    context: str = ""
    options: list[str] = Field(default_factory=list)
    tier: KnowledgeTier = "must_ask"


class OperatingPreferences(BaseModel):
    priority_style: Optional[PriorityStyle] = None
    promotion_aggressiveness: float = 0.5  # 0 保守 … 1 激进
    weekend_more_aggressive: bool = False
    notes: str = ""


class OperatingConstraints(BaseModel):
    lunch_capacity_per_hour: Optional[float] = None
    dinner_capacity_per_hour: Optional[float] = None
    item_cost_floor: dict[str, float] = Field(default_factory=dict)  # 菜名 → 成本
    item_min_price: dict[str, float] = Field(default_factory=dict)  # 菜名 → 最低可接受售价
    profit_floor_rate: Optional[float] = None  # 到手率底线（如 0.58）
    notes: str = ""


class PermissionPolicy(BaseModel):
    """信任渐进：随结果放宽，而非注册日一次勾选。"""

    auto_reply_good_reviews: bool = False
    monitor_promo_expiry: bool = True
    monitor_stockout: bool = True
    monitor_competitors: bool = True
    ads_auto_daily_limit_cny: Optional[float] = None  # None = 未授权自动调投流
    low_risk_auto_ok: Optional[bool] = None  # None = 未确认；True/False 都算已表态
    notes: str = ""


class MerchantUnderstanding(BaseModel):
    store_id: str
    onboarding_stage: OnboardingStage = "connect"
    system_mode: SystemMode = "safe"
    store_profile: dict[str, Any] = Field(default_factory=dict)
    inferred: list[InferredFact] = Field(default_factory=list)
    field_meta: dict[str, InfoFieldMeta] = Field(default_factory=dict)
    context_facts: list[ContextFact] = Field(default_factory=list)  # V1 §04 短生命周期信息
    preferences: OperatingPreferences = Field(default_factory=OperatingPreferences)
    constraints: OperatingConstraints = Field(default_factory=OperatingConstraints)
    permissions: PermissionPolicy = Field(default_factory=PermissionPolicy)
    open_gaps: list[str] = Field(default_factory=list)
    last_interview_key: Optional[str] = None
    known_count: int = 0
    unknown_count: int = 0
    updated_at: Optional[datetime] = None
    principle: str = "Ask Only What AI Cannot Know."
    platform_connected: bool = False  # 真实 PlatformConnection.status==connected
    # Minimum Operating State 检查结果
    mos_satisfied: bool = False  # MOS 是否满足
    mos_blocking_fields: list[str] = Field(default_factory=list)  # MOS 聚合字段
    mos_gap_keys: list[str] = Field(default_factory=list)  # 对应访谈 open_gaps key


class UnderstandingUpdateResult(BaseModel):
    understanding: MerchantUnderstanding
    changed_keys: list[str] = Field(default_factory=list)
    reply: str = ""
    mode: str = "mue_update"
