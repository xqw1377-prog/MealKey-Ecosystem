"""Source Registry V1 contracts.

白名单：`MealKey_Case_Corpus_Source_Whitelist_V1.md`
每个来源（含子来源/条款版本）登记一个 SourceRegistryItem，
配合 ingestion pipeline 记录采集、蒸馏与 QA 统计。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

AuthorityLevel = Literal["F", "C2", "C1", "R"]
IngestionMode = Literal["AUTO_DIFF", "SEMI", "MANUAL", "DATASET"]
SourceType = Literal[
    "course",
    "case_story",
    "rule",
    "report",
    "dataset",
    "paper",
    "book",
    "knowledge_base",
    "api_doc",
]
CommercialBias = Literal["none", "low", "medium", "high"]
CopyrightMode = Literal[
    "open_license",
    "platform_terms",
    "purchased",
    "proprietary",
    "education_only",
]
UpdateFrequency = Literal[
    "continuous",
    "weekly",
    "monthly",
    "quarterly",
    "yearly",
    "on_change",
    "unknown",
]


class SourceRegistryItem(BaseModel):
    """白名单中的一个来源对象。"""

    source_id: str
    publisher: str
    source_type: SourceType = "case_story"

    canonical_url: Optional[str] = None
    title: str
    published_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None

    authority_level: AuthorityLevel = "C1"
    commercial_bias: CommercialBias = "medium"
    copyright_mode: CopyrightMode = "proprietary"
    ingestion_mode: IngestionMode = "SEMI"

    allowed_for_rules: bool = False
    allowed_for_case_prior: bool = True
    allowed_for_training: bool = False
    allowed_for_commercial_use: bool = False

    update_frequency: UpdateFrequency = "unknown"
    raw_content_hash: Optional[str] = None
    source_version: str = "1"

    case_count: int = 0
    accepted_case_count: int = 0
    rejected_case_count: int = 0

    whitelist_no: int = 0
    phase: Literal["p0", "later"] = "later"
    enabled: bool = False
    research_zone: bool = False
    distill_focus: str = ""
    notes: list[str] = Field(default_factory=list)


class SourceRegistryUpdate(BaseModel):
    """AUTO-DIFF 差异检测的请求：发现条款/版本变更时提交。"""

    source_id: str
    previous_version: str
    new_version: str
    detected_at: datetime
    diff_summary: str = ""
    impacted_rules: list[str] = Field(default_factory=list)


class IngestionRunResult(BaseModel):
    """一次蒸馏运行的结果统计（供 QA gate 与 Source Registry 回写）。"""

    run_id: str
    source_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None

    raw_evidence_count: int = 0
    claim_count: int = 0
    fact_count: int = 0
    conflict_count: int = 0
    case_candidates: int = 0
    accepted_cases: int = 0
    rejected_cases: int = 0
    qa_blocked: bool = False
