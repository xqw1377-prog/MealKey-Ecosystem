"""菜单经营诊断引擎 — 领域模型（从主仓 menu-diagnosis-engine 迁移）。

数据成熟度分级 D0–D4 + 12 诊断引擎 + 置信度卡片 + 建议卡。
权威：Mealwork 菜单经营诊断 Agent PRD V1.0
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

DataMaturityLevel = Literal["D0", "D1", "D2", "D3", "D4"]
DiagnosisEngineId = Literal[
    "menu_structure",
    "cost_profit",
    "ingredient_supply",
    "flavor_spice",
    "diet_nutrition",
    "speed_capacity",
    "menu_reading",
    "visual_appearance",
    "repurchase_memory",
    "customer_journey",
    "dish_role_joint",
    "compliance_risk",
]
ConfidenceLevel = Literal["high", "medium", "low"]
DiagnosisSeverity = Literal["critical", "warning", "info", "positive"]

ENGINE_METADATA: dict[str, dict[str, str]] = {
    "menu_structure": {"name": "菜单结构与价格带", "min_level": "D1", "description": "分类路径、菜品数量、角色完整度、价格断档"},
    "cost_profit": {"name": "成本卡与盈利", "min_level": "D2", "description": "毛利率、贡献毛利、成本波动、亏损菜识别"},
    "ingredient_supply": {"name": "食材网络与供应链", "min_level": "D2", "description": "复用率、独占食材、供应商集中、损耗"},
    "flavor_spice": {"name": "味型与辣度", "min_level": "D1", "description": "味型覆盖、辣度分布、味觉节奏"},
    "diet_nutrition": {"name": "荤素与饮食限制", "min_level": "D1", "description": "荤素占比、过敏原、饮食限制覆盖"},
    "speed_capacity": {"name": "上菜速度与厨房产能", "min_level": "D3", "description": "首菜时间、P90出餐、档口负荷"},
    "menu_reading": {"name": "菜牌阅读与点单决策", "min_level": "D0", "description": "OCR还原、视觉区、价格表达、组单效率"},
    "visual_appearance": {"name": "菜品颜值与图实一致", "min_level": "D4", "description": "食欲感、图实一致度、门店稳定度"},
    "repurchase_memory": {"name": "复购驱动力/菜品记忆度", "min_level": "D4", "description": "重复点选、吃完率、品牌独占性"},
    "customer_journey": {"name": "顾客完整旅程", "min_level": "D3", "description": "看见→选择→等待→第一口→复购全链路"},
    "dish_role_joint": {"name": "菜品角色与联合诊断", "min_level": "D2", "description": "跨维度矛盾识别、多角色联合判断"},
    "compliance_risk": {"name": "合规与风险", "min_level": "D1", "description": "价格、过敏原、食品安全、宣传合规"},
}


class ConfidenceCard(BaseModel):
    level: ConfidenceLevel = "medium"
    data_level: DataMaturityLevel = "D1"
    field_coverage: float = 0.5
    sample_size: int = 0
    timeliness: float = 0.5
    consistency: float = 0.7
    model_uncertainty: float = 0.3
    rule_hits: int = 1
    human_confirmed: bool = False
    reason: str = ""


class EvidenceItem(BaseModel):
    source: str = ""
    data_level: DataMaturityLevel = "D1"
    time_window: Optional[str] = None
    sample_size: Optional[int] = None
    value: str = ""


class DiagnosisFinding(BaseModel):
    id: str
    engine_id: DiagnosisEngineId
    severity: DiagnosisSeverity = "info"
    title: str
    description: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)
    impact: str = ""
    confidence: ConfidenceCard = Field(default_factory=ConfidenceCard)
    suggested_actions: list[str] = Field(default_factory=list)
    estimated_impact: Optional[dict[str, Any]] = None


class MenuItemInput(BaseModel):
    """菜品输入（对应主仓 MenuItemInput，适配外卖场景简化）。"""
    id: str
    name: str
    category: str = ""
    price: float = 0
    actual_price: Optional[float] = None
    description: Optional[str] = None
    is_signature: bool = False
    is_recommended: bool = False
    image_url: Optional[str] = None
    role: Optional[str] = None  # signature/profit/traffic/combo/basic/seasonal
    flavor_primary: Optional[str] = None
    spice_level: Optional[int] = None  # 0-4
    spice_adjustable: bool = False
    diet_type: Optional[str] = None  # pure_meat/meat_veg/pure_veg/vegan
    allergens: list[str] = Field(default_factory=list)
    # 外卖特有
    order_count: int = 0
    order_share_pct: Optional[float] = None
    ctr: Optional[float] = None
    cvr: Optional[float] = None
    standard_cost: Optional[float] = None  # 标准成本


class DiagnosisContext(BaseModel):
    """诊断上下文（引擎输入）。"""
    store_id: str
    store_name: Optional[str] = None
    menu_version: str = "v1"
    menu_items: list[MenuItemInput] = Field(default_factory=list)
    data_level: DataMaturityLevel = "D1"
    # 可选高级数据（D2+）
    feedbacks: list[dict[str, Any]] = Field(default_factory=list)
    serving_events: list[dict[str, Any]] = Field(default_factory=list)
    ocr_data: Optional[dict[str, Any]] = None


class DiagnosisRunResult(BaseModel):
    """一次诊断运行的输出。"""
    store_id: str
    data_level: DataMaturityLevel = "D1"
    findings: list[DiagnosisFinding] = Field(default_factory=list)
    finding_count_by_severity: dict[str, int] = Field(default_factory=dict)
    summary: str = ""
