"""入库 QA：L1+ 才进 Case Library；R/Yelp/整本书不得进检索。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.operating_case import CaseIngestionRun, OperatingCaseRecord, SourceRegistryRecord
from app.schemas.operating_case import OperatingCase
from app.services.oci.distillation import distill_snippet
from app.services.oci.germination import CaseGraduationError, assert_case_cannot_enter_strategy_memory
from app.services.oci.whitelist import WHITELIST, by_id

MAX_BOOK_EXCERPT = 800

_POOL_BY_PREFIX = (
    ("case_seed_", "Pool C · 店客多 seed"),
    ("case_bk_", "Pool B · 专业书籍"),
    ("case_dd_", "Pool B · DoorDash"),
    ("case_ub_", "Pool B · Uber Eats"),
    ("case_mz_", "Pool B · 美团智能掌柜"),
    ("case_md_", "Pool B · 美团外卖方法论"),
    ("case_dv_", "Pool C · Deliverect"),
    ("case_sqb_", "Pool C · 收钱吧"),
    ("case_yz_", "Pool C · 有赞"),
    ("case_dk_", "Pool C · 店客多知识库"),
)


def corpus_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "cases"
        if candidate.exists():
            return candidate
    return here.parents[4] / "data" / "cases"


def iter_case_files() -> list[Path]:
    folder = corpus_dir()
    if not folder.exists():
        return []
    return sorted(path for path in folder.glob("case_*.json") if path.is_file())


def load_case_file(path: Path) -> OperatingCase:
    return OperatingCase.model_validate(json.loads(path.read_text(encoding="utf-8")))


def validate_corpus() -> dict[str, Any]:
    files = iter_case_files()
    accepted: list[str] = []
    rejected: list[str] = []
    for path in files:
        try:
            case = load_case_file(path)
            qa_operating_case(case, source_id=_guess_source_id(case))
            accepted.append(case.case_id)
        except Exception as exc:  # noqa: BLE001
            rejected.append(f"{path.name}: {exc}")
    return {
        "total_files": len(files),
        "accepted": len(accepted),
        "rejected": rejected,
        "case_ids": accepted,
    }


def _pool_for(filename: str) -> str:
    for prefix, pool in _POOL_BY_PREFIX:
        if filename.startswith(prefix):
            return pool
    return "Pool · 未分类"


def rebuild_manifest() -> dict[str, Any]:
    files = iter_case_files()
    cases: list[OperatingCase] = []
    index: list[dict[str, Any]] = []
    for path in files:
        case = load_case_file(path)
        qa_operating_case(case, source_id=_guess_source_id(case))
        cases.append(case)
        index.append(
            {
                "case_id": case.case_id,
                "source_reliability": case.source.source_reliability,
                "attribution_quality": case.trust.attribution_quality,
                "confidence": case.trust.confidence,
                "file": path.name,
                **(
                    {"source_conflict_flag": True}
                    if case.distillation.source_conflict_flag
                    else {}
                ),
            }
        )
    by_pool: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_level: dict[str, int] = {}
    by_demand: dict[str, int] = {}
    for path, case in zip(files, cases, strict=True):
        pool = _pool_for(path.name)
        by_pool[pool] = by_pool.get(pool, 0) + 1
        status = case.distillation.status
        by_status[status] = by_status.get(status, 0) + 1
        by_level[case.distillation.evidence_level] = by_level.get(case.distillation.evidence_level, 0) + 1
        demand = case.demand_code or "未标注"
        by_demand[demand] = by_demand.get(demand, 0) + 1
    payload = {
        "corpus": "MealKey Food Delivery Operating Case Corpus",
        "version": "0.2.0",
        "generated_at": utc_now().isoformat(),
        "schema_ref": "app/schemas/operating_case.py :: OperatingCase",
        "design_ref": "MealKey_Operating_Case_Library.md",
        "whitelist_ref": "MealKey_Case_Corpus_Source_Whitelist_V1.md",
        "governance_rule": "只有 MealKey 真实门店验证过 Result 的案例才能晋升 Strategy Memory；外部案例永远停在 L1/L2 weak prior。",
        "statistics": {
            "total_cases": len(cases),
            "by_pool": by_pool,
            "by_evidence_level": by_level,
            "by_status": by_status,
            "by_demand_code": by_demand,
        },
        "cases": index,
        "next_steps": [
            "外部案例保持 CASE_PRIOR_ONLY，接入真实门店实验后才允许 L3 / Strategy Memory",
            "P0 SEMI 来源按白名单逐篇质检，不一次抓 50 个源",
            "方法论案例的官方聚合口径（如拼好饭 +30%/-20%）禁止蒸馏为单店确定性提升",
        ],
    }
    out = corpus_dir() / "corpus_manifest.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


class IngestRejected(ValueError):
    pass


def sync_source_registry(db: Session) -> int:
    written = 0
    for item in WHITELIST:
        row = db.execute(
            select(SourceRegistryRecord).where(SourceRegistryRecord.source_id == item.source_id)
        ).scalar_one_or_none()
        payload = dict(
            publisher=item.publisher,
            title=item.title,
            canonical_url=item.canonical_url,
            authority_level=item.authority_level,
            ingestion_mode=item.ingestion_mode,
            copyright_mode=item.copyright_mode,
            phase=item.phase,
            enabled=item.enabled,
            research_zone=item.research_zone,
            allowed_for_rules=item.allowed_for_rules,
            allowed_for_case_prior=item.allowed_for_case_prior,
        )
        if row is None:
            db.add(SourceRegistryRecord(source_id=item.source_id, **payload))
            written += 1
        else:
            for key, value in payload.items():
                setattr(row, key, value)
    db.commit()
    return written


def qa_operating_case(case: OperatingCase, *, source_id: str | None = None) -> None:
    excerpt = (case.source.source_excerpt or "").strip()
    if not excerpt:
        raise IngestRejected("缺少 source_excerpt，不能入库")
    if case.distillation.evidence_level not in {"L1", "L2", "L3"}:
        raise IngestRejected("L0 不入库")
    if case.distillation.evidence_level == "L3" and case.source.source_reliability != "mealkey_experiment":
        raise IngestRejected("L3 只能来自 MealKey 自己的实验")
    if case.distillation.status == "graduated_to_strategy_memory":
        raise IngestRejected("入库时不得标记已晋升 Strategy Memory")
    if case.source.source_reliability != "mealkey_experiment":
        try:
            assert_case_cannot_enter_strategy_memory(case)
        except CaseGraduationError:
            pass
        else:
            raise IngestRejected("外部案例不能处于可晋升状态")
    registry = None
    if source_id:
        try:
            registry = by_id(source_id)
        except KeyError:
            registry = None
    if registry:
        if registry.research_zone or registry.ingestion_mode == "DATASET":
            raise IngestRejected("Research Zone / DATASET 不进 Case 检索")
        if registry.copyright_mode == "education_only":
            raise IngestRejected("education_only 来源禁止进入生产 Case Library")
        if registry.source_type == "book" and len(excerpt) > MAX_BOOK_EXCERPT:
            raise IngestRejected("书籍只允许摘要，禁止大段版权正文")
        if not registry.allowed_for_case_prior:
            raise IngestRejected("该来源不允许作为 case prior")


def _enrich_conflict_fields(case: OperatingCase) -> OperatingCase:
    """冲突数字与厂商宣称必须落在案例对象上，禁止只留一个旗标。"""
    excerpt = (case.source.source_excerpt or "").strip()
    if not excerpt:
        return case
    distilled = distill_snippet(
        case.case_id,
        case.source.source_name or "",
        excerpt,
        authority_level="C1",
        ingestion_mode="SEMI",
    )
    claims = list(distilled.get("reported_claims") or [])
    sides = list(distilled.get("conflict_sides") or [])
    if claims and not case.incident.reported_claims:
        case.incident.reported_claims = claims
    if (distilled.get("source_conflict") or sides) and not case.distillation.source_conflict_flag:
        case.distillation.source_conflict_flag = True
    if sides and not case.source.source_conflicts:
        case.source.source_conflicts = sides
    return case


def _upsert_case(db: Session, case: OperatingCase, source_id: str | None) -> str:
    qa_operating_case(case, source_id=source_id)
    case = _enrich_conflict_fields(case)
    payload = case.model_dump(mode="json")
    existing = db.execute(
        select(OperatingCaseRecord).where(OperatingCaseRecord.case_id == case.case_id)
    ).scalar_one_or_none()
    status = case.distillation.status
    if status == "candidate_for_experiment":
        status = "case_prior_only"
    fields = dict(
        source_id=source_id,
        demand_code=case.demand_code,
        domain=case.incident.domain,
        evidence_level=case.distillation.evidence_level,
        status=status,
        authority_level="C2" if case.source.source_reliability == "platform_official" else "C1",
        source_conflict=bool(case.distillation.source_conflict_flag),
        confidence=float(case.trust.confidence or 0.2),
        research_zone=False,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    if existing is None:
        db.add(OperatingCaseRecord(case_id=case.case_id, **fields))
        return "new"
    for key, value in fields.items():
        setattr(existing, key, value)
    return "updated"


def ingest_case_file(db: Session, path: Path, *, source_id: str | None = None) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    case = OperatingCase.model_validate(raw)
    guessed = source_id or _guess_source_id(case)
    return _upsert_case(db, case, guessed)


def ingest_seed_corpus(db: Session) -> dict[str, Any]:
    sync_source_registry(db)
    folder = corpus_dir()
    run = CaseIngestionRun(source_id="SRC-DKD-SEED", status="running")
    db.add(run)
    db.flush()
    accepted = 0
    rejected = 0
    conflicts = 0
    errors: list[str] = []
    for path in iter_case_files():
        try:
            change = ingest_case_file(db, path)
            accepted += 1
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (raw.get("distillation") or {}).get("source_conflict_flag"):
                conflicts += 1
            _ = change
        except Exception as exc:  # noqa: BLE001
            rejected += 1
            errors.append(f"{path.name}: {exc}")
    run.status = "completed" if accepted else "failed"
    run.finished_at = utc_now()
    run.accepted_cases = accepted
    run.rejected_cases = rejected
    run.conflict_count = conflicts
    run.error = "；".join(errors[:6]) if errors else None
    db.commit()
    return {
        "status": run.status,
        "accepted_cases": accepted,
        "rejected_cases": rejected,
        "conflict_count": conflicts,
        "error": run.error,
        "corpus_dir": str(folder),
    }


def _guess_source_id(case: OperatingCase) -> str | None:
    name = case.source.source_name or ""
    url = (case.source.source_url or "").lower()
    case_id = (case.case_id or "").lower()
    blob = f"{name} {url} {case_id}".lower()
    if "pinhaofan" in case_id or "拼好饭" in name:
        return "SRC-MT-COURSE-HIT"
    if "18_skills" in case_id or "18个技巧" in name or "lesson/detail/155" in url:
        return "SRC-MT-COURSE-18TIPS"
    if "better" in case_id or "贝恩" in name:
        return "SRC-MT-COURSE-OPS"
    if "data_metrics" in case_id or "商家版" in name:
        return "SRC-MT-COURSE-DATA"
    if case_id.startswith("case_md_"):
        return "SRC-MT-COURSE-OPS"
    if case_id.startswith("case_dk_") or "admin.diankeduo" in url:
        return "SRC-DKD-KB"
    if case_id.startswith("case_mz_") or "智能掌柜" in name:
        return "SRC-MT-AI-MANAGER"
    mapping = (
        ("doordash", "SRC-DD-STORIES"),
        ("uber", "SRC-UE-OISHII" if "oishii" in blob else "SRC-UE-STORIES"),
        ("deliverect", "SRC-DV-LITTLE-CAESARS"),
        ("有赞", "SRC-YZ-PRIVATE"),
        ("收钱吧", "SRC-SQB-CAILINJI"),
        ("diankeduo", "SRC-DKD-KB"),
        ("店客多", "SRC-DKD-SEED"),
    )
    for needle, source_id in mapping:
        if needle in blob:
            return source_id
    return "SRC-DKD-SEED"
