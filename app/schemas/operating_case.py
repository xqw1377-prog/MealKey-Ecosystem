"""Operating Case Library V1 contracts.

架构：`MealKey_Operating_Case_Library.md`
职责边界：案例库负责「我见过类似事情」；只有 MealKey 在真实门店
验证过 Result 的案例才允许晋升 Strategy Memory。

证据等级：L0 anecdotal（不入库）/ L1 documented_case（weak prior）
/ L2 repeated_pattern（stronger prior）/ L3 mealkey_verified（晋升）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

EvidenceLevel = Literal["L1", "L2", "L3"]
SourceType = Literal["document_case", "repeated_pattern", "mealkey_verified"]
SourceReliability = Literal["vendor_material", "platform_official", "industry_report", "academic", "book", "mealkey_experiment"]
AttributionQuality = Literal["LOW", "MEDIUM", "HIGH"]
CaseStatus = Literal[
    "case_prior_only",
    "seed_case_pending_experiment",
    "candidate_for_experiment",
    "verified_positive",
    "verified_neutral",
    "verified_negative",
    "graduated_to_strategy_memory",
    "dropped",
]

CaseDomain = Literal[
    "OPERATION_ABNORMAL",
    "ADS_EFFICIENCY",
    "RATING_AND_SERVICE",
    "MENU",
    "PRODUCT",
    "COMPETITION",
    "TRAFFIC",
    "PROFIT",
    "CUSTOMER",
    "REPURCHASE",
    "FULFILLMENT",
    "CAMPAIGN",
    "STORE_GROWTH",
]


class CaseSource(BaseModel):
    """来源与 Provenance。必须保留原文摘录，供复核。"""

    source_type: SourceType = "document_case"
    source_name: str
    source_url: Optional[str] = None
    source_file: Optional[str] = None
    source_date: Optional[str] = None
    source_excerpt: str = ""
    source_reliability: SourceReliability = "vendor_material"
    source_conflicts: list[str] = Field(default_factory=list)


class StoreContext(BaseModel):
    """案例发生时的门店背景（用于 Context Similarity）。"""

    platform: Optional[str] = None
    category: Optional[str] = None
    store_type: Optional[str] = None
    city_level: Optional[str] = None
    store_count: Optional[str] = None
    price_band: Optional[str] = None
    business_stage: Optional[str] = None


class Incident(BaseModel):
    """当时发生了什么。observations 只记事实，不含结论。"""

    problem_type: str = ""
    domain: CaseDomain = "PRODUCT"
    trigger: str = ""
    observations: list[str] = Field(default_factory=list)
    baseline_metrics: dict = Field(default_factory=dict)
    known_facts: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    reported_claims: list[str] = Field(default_factory=list)
    verified_facts: list[str] = Field(default_factory=list)


class CaseAnalysis(BaseModel):
    """为什么认为有问题。"""

    hypothesis: str = ""
    diagnosis: str = ""


class CaseAction(BaseModel):
    action_id: str = ""
    action: str
    detail: str = ""


class CaseActions(BaseModel):
    actions: list[CaseAction] = Field(default_factory=list)
    execution_mode: str = ""
    duration: Optional[str] = None
    constraints: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    result_metrics: list[str] = Field(default_factory=list)
    before: Optional[dict] = None
    after: Optional[dict] = None
    observation_window: Optional[str] = None
    positive_result: str = ""
    negative_result: str = ""
    forbidden_claim: str = ""


class CaseTrust(BaseModel):
    """可信度。缺对照组 / 来源冲突时如实记录，禁止替来源圆谎。"""

    attribution_quality: AttributionQuality = "LOW"
    attribution_quality_label: str = "LOW"
    confounders: list[str] = Field(default_factory=list)
    source_conflicts: list[dict] = Field(default_factory=list)
    confidence: float = 0.0


class Transferability(BaseModel):
    applicable_when: list[str] = Field(default_factory=list)
    not_applicable_when: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)


class Distillation(BaseModel):
    """蒸馏结果：什么条件下做了什么、结果如何、何时别照抄。"""

    strategy_principle: str = ""
    candidate_action_pattern: str = ""
    success_metric: str = ""
    evidence_level: EvidenceLevel = "L1"
    status: CaseStatus = "seed_case_pending_experiment"
    source_conflict_flag: bool = False


class OperatingCase(BaseModel):
    """统一案例对象。最值钱的不是故事正文，而是条件、结果与禁忌。"""

    case_id: str
    schema_version: str = "1.0"
    distilled_by: str = ""

    source: CaseSource = Field(default_factory=CaseSource)
    store_context: StoreContext = Field(default_factory=StoreContext)
    incident: Incident = Field(default_factory=Incident)
    analysis: CaseAnalysis = Field(default_factory=CaseAnalysis)
    actions: CaseActions = Field(default_factory=CaseActions)
    result: CaseResult = Field(default_factory=CaseResult)
    trust: CaseTrust = Field(default_factory=CaseTrust)
    transferability: Transferability = Field(default_factory=Transferability)
    distillation: Distillation = Field(default_factory=Distillation)

    demand_code: Optional[str] = None
    germinated_from: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CaseRetrievalQuery(BaseModel):
    """CaseScore 确定性排序的检索请求。"""

    store_context_tags: list[str] = Field(default_factory=list)
    problem_type: str = ""
    metric_relevance: list[str] = Field(default_factory=list)
    demand_code: Optional[str] = None
    max_results: int = 5
    min_evidence_level: EvidenceLevel = "L1"


class CaseScoreResult(BaseModel):
    case_id: str
    score: float = 0.0
    context_similarity: float = 0.0
    evidence_quality: float = 0.0
    metric_relevance: float = 0.0
    freshness: float = 0.0
    transferability: float = 0.0
    outcome_confidence: float = 0.0
    case: Optional[OperatingCase] = None
