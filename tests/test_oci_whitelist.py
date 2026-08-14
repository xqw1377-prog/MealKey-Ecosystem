"""Source Whitelist V1 + Case ingestion：外部资料不得进入 Strategy Memory。"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.operating_case import OperatingCaseRecord
from app.models.strategy_memory import StrategyMemoryRecord
from app.schemas.operating_case import OperatingCase
from app.services.oci.case_retrieval import retrieve_case_priors
from app.services.oci.distillation import (
    check_metric_consistency,
    detect_confounders,
    distill_snippet,
    separate_facts_and_claims,
)
from app.services.oci.fetchers import diff_enabled_rule_sources
from app.services.oci.germination import CaseGraduationError, assert_case_cannot_enter_strategy_memory
from app.services.oci.ingest import (
    IngestRejected,
    _guess_source_id,
    ingest_seed_corpus,
    iter_case_files,
    load_case_file,
    qa_operating_case,
    validate_corpus,
)
from app.services.oci.whitelist import P0_SOURCE_IDS, WHITELIST, by_id, enabled_sources, rule_sources


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_whitelist_has_50_numbered_sources_and_only_p0_enabled() -> None:
    numbered = [item for item in WHITELIST if item.whitelist_no]
    assert {item.whitelist_no for item in numbered} == set(range(1, 51))
    assert len(P0_SOURCE_IDS) == 12
    assert {item.source_id for item in enabled_sources()} == set(P0_SOURCE_IDS)
    yelp = by_id("SRC-YELP-OPEN")
    assert yelp.research_zone is True
    assert yelp.allowed_for_training is False
    assert yelp.allowed_for_case_prior is False
    assert yelp.copyright_mode == "education_only"
    book = by_id("SRC-BOOK-7STEPS")
    assert book.ingestion_mode == "MANUAL"
    assert book.allowed_for_training is False
    trd = by_id("SRC-TRD")
    assert trd.research_zone is True
    assert trd.enabled is True
    later_semi = by_id("SRC-DD-COYO")
    assert later_semi.enabled is False


def test_vendor_percent_is_claim_not_fact() -> None:
    split = separate_facts_and_claims("接入系统后运营效率提高80%，订单随之上涨。")
    assert split["reported_claims"]
    assert any("80" in item for item in split["reported_claims"])
    assert "运营效率提高80%" not in split["verified_facts"]


def test_metric_conflict_keeps_both_sides() -> None:
    text = "正文宣称推广效率提升80%；图表 ROI 3.4→5.7；另一处写 ROI 3.8→4.5。"
    result = check_metric_consistency(text)
    assert result["source_conflict"] is True
    assert result["confidence"] == "low"
    assert result["sides"]


def test_confounder_blocks_single_cause() -> None:
    text = "广告预算提高，同时新品上线，又赶上节假日，然后订单上涨。"
    flags = detect_confounders(text)
    assert flags
    assert any("单一因果" in item for item in flags)
    distilled = distill_snippet(
        "SRC-DD-STORIES",
        "demo",
        text,
        authority_level="C2",
        ingestion_mode="SEMI",
    )
    assert distilled["status"] == "case_prior_only"
    assert distilled["confidence"] <= 0.2


def test_external_case_cannot_enter_strategy_memory() -> None:
    case = OperatingCase.model_validate(
        {
            "case_id": "CASE-FAKE-001",
            "source": {
                "source_type": "document_case",
                "source_name": "厂商宣传",
                "source_excerpt": "效率提高80%",
                "source_reliability": "vendor_material",
            },
            "distillation": {"evidence_level": "L1", "status": "case_prior_only"},
        }
    )
    try:
        assert_case_cannot_enter_strategy_memory(case)
        assert False, "should raise"
    except CaseGraduationError as exc:
        assert "Strategy Memory" in str(exc)


def test_yelp_and_long_book_excerpt_rejected() -> None:
    yelp_case = OperatingCase.model_validate(
        {
            "case_id": "CASE-YELP-BAD",
            "source": {
                "source_type": "document_case",
                "source_name": "Yelp Open Dataset",
                "source_excerpt": "a" * 40,
                "source_reliability": "academic",
            },
        }
    )
    try:
        qa_operating_case(yelp_case, source_id="SRC-YELP-OPEN")
        assert False, "yelp should reject"
    except IngestRejected:
        pass
    book = OperatingCase.model_validate(
        {
            "case_id": "CASE-BOOK-LONG",
            "source": {
                "source_type": "document_case",
                "source_name": "外卖运营7步法",
                "source_excerpt": "版权正文" * 250,
                "source_reliability": "book",
            },
        }
    )
    try:
        qa_operating_case(book, source_id="SRC-BOOK-7STEPS")
        assert False, "long book excerpt should reject"
    except IngestRejected:
        pass


def test_ingest_seeds_keeps_conflict_and_does_not_write_memory() -> None:
    db = _session()
    result = ingest_seed_corpus(db)
    assert result["accepted_cases"] >= 3
    rows = list(db.execute(select(OperatingCaseRecord)).scalars())
    assert rows
    conflicted = [row for row in rows if row.source_conflict]
    assert conflicted
    payload = json.loads(next(row.payload_json for row in conflicted))
    assert payload["distillation"]["source_conflict_flag"] is True
    dist = payload.get("distillation") or {}
    incident = payload.get("incident") or {}
    source = payload.get("source") or {}
    claims = (
        list(incident.get("reported_claims") or [])
        + list(dist.get("reported_claims") or [])
        + list(source.get("source_conflicts") or [])
    )
    assert claims, (
        f"expected reported_claim somewhere, got dist={dist}, bm={incident.get('baseline_metrics')}"
    )
    assert db.execute(select(StrategyMemoryRecord)).scalar_one_or_none() is None
    assert all(row.status != "graduated_to_strategy_memory" for row in rows)


def test_retrieve_priors_are_case_prior_only_and_skip_research() -> None:
    hits = retrieve_case_priors(demand_code="ADS_ROI", family="ads", question="今天推广花的钱赚回来了吗？")
    assert hits
    assert all(item["status"] == "CASE_PRIOR_ONLY" for item in hits)
    assert all("yelp" not in item["case_id"].lower() for item in hits)
    from app.services.oci.case_retrieval import load_file_cases

    conflicted = [
        case
        for case in load_file_cases()
        if case.distillation.source_conflict_flag and "ADS" in (case.incident.problem_type or "")
    ]
    assert conflicted
    assert conflicted[0].trust.confidence <= 0.15


def test_auto_diff_only_touches_enabled_rule_sources() -> None:
    db = _session()
    fetched: list[str] = []

    def fake_fetch(url: str):
        fetched.append(url)
        return 200, "text/html", f"<html>{url}</html>", url

    result = diff_enabled_rule_sources(db, fetch=fake_fetch)
    enabled_rule_urls = {item.canonical_url for item in rule_sources(enabled_only=True) if item.canonical_url}
    assert set(fetched) == enabled_rule_urls
    assert result["checked"] >= 1
    later_rule = by_id("SRC-MT-RULE-FOODSAFE")
    assert later_rule.enabled is False
    assert later_rule.canonical_url not in fetched


_METHODOLOGY_ROUND = (
    "case_md_001_pinhaofan_bop",
    "case_md_002_18_skills",
    "case_md_003_natural_traffic",
    "case_md_004_data_metrics",
    "case_md_005_pricing_formula",
    "case_md_006_bidding_save",
    "case_dk_001_maoli_biaopin",
)

_FOLLOWON_METHODOLOGY = (
    "case_md_007_delivery_fee",
    "case_md_008_better",
    "case_dk_002_health_monitor",
    "case_dk_003_intelligent_cpc",
)


def test_methodology_cases_validate_and_stay_priors() -> None:
    from app.services.oci.case_retrieval import load_file_cases, reload_file_cases, retrieve_case_priors

    report = validate_corpus()
    assert not report["rejected"], report["rejected"]
    assert report["accepted"] == report["total_files"] == len(iter_case_files())
    assert report["total_files"] >= 33
    ids = set(report["case_ids"])
    for case_id in _METHODOLOGY_ROUND + _FOLLOWON_METHODOLOGY:
        assert case_id in ids

    pinhao = load_case_file(next(p for p in iter_case_files() if p.stem == "case_md_001_pinhaofan_bop"))
    assert pinhao.distillation.status == "candidate_for_experiment"
    assert "禁止" in pinhao.result.forbidden_claim
    assert "订单+30%" in pinhao.result.forbidden_claim
    assert pinhao.distillation.status != "graduated_to_strategy_memory"
    assert _guess_source_id(pinhao) == "SRC-MT-COURSE-HIT"
    qa_operating_case(pinhao, source_id="SRC-MT-COURSE-HIT")

    skills = load_case_file(next(p for p in iter_case_files() if p.stem == "case_md_002_18_skills"))
    assert skills.distillation.status == "seed_case_pending_experiment"
    assert _guess_source_id(skills) == "SRC-MT-COURSE-18TIPS"

    better = load_case_file(next(p for p in iter_case_files() if p.stem == "case_md_008_better"))
    assert _guess_source_id(better) == "SRC-MT-COURSE-OPS"
    assert _guess_source_id(better) != "SRC-MT-RESEARCH"
    qa_operating_case(better, source_id="SRC-MT-COURSE-OPS")

    for path in iter_case_files():
        case = load_case_file(path)
        assert case.distillation.status != "graduated_to_strategy_memory"
        if path.stem in _METHODOLOGY_ROUND or path.stem in _FOLLOWON_METHODOLOGY:
            assert "禁止" in (case.result.forbidden_claim or "")
            if path.stem != "case_md_001_pinhaofan_bop" and path.stem != "case_md_008_better":
                assert case.distillation.status == "seed_case_pending_experiment"

    dk = load_case_file(next(p for p in iter_case_files() if p.stem == "case_dk_001_maoli_biaopin"))
    assert _guess_source_id(dk) == "SRC-DKD-KB"

    reload_file_cases()
    menu_hits = retrieve_case_priors(demand_code="MENU", family="product", question="爆品怎么选？")
    assert menu_hits
    assert all(item["status"] == "CASE_PRIOR_ONLY" for item in menu_hits)
    pinhao_hit = next((item for item in menu_hits if item["case_id"] == "case_md_001_pinhaofan_bop"), None)
    if pinhao_hit:
        assert "禁止" in (pinhao_hit.get("forbidden_claim") or "")
        assert "确定性" not in (pinhao_hit.get("status") or "")
    assert all(case.distillation.status != "graduated_to_strategy_memory" for case in load_file_cases())


def test_manifest_matches_disk_after_rebuild() -> None:
    from app.services.oci.ingest import corpus_dir, rebuild_manifest

    payload = rebuild_manifest()
    files = iter_case_files()
    stats = payload["statistics"]
    assert stats["total_cases"] == len(files)
    assert payload["cases"]
    assert {item["file"] for item in payload["cases"]} == {path.name for path in files}
    assert all(item["case_id"] for item in payload["cases"])
    assert stats["by_pool"]
    assert stats["by_status"]["seed_case_pending_experiment"] + stats["by_status"].get(
        "candidate_for_experiment", 0
    ) == len(files)
    on_disk = json.loads((corpus_dir() / "corpus_manifest.json").read_text(encoding="utf-8"))
    assert on_disk["statistics"]["total_cases"] == len(files)
    assert "Strategy Memory" in payload["governance_rule"]
