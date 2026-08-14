"""Source Registry / Case Library：内部能力，不是老板页面。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.oci.case_retrieval import retrieve_case_priors
from app.services.oci.fetchers import diff_enabled_rule_sources
from app.services.oci.ingest import ingest_seed_corpus, sync_source_registry
from app.services.oci.whitelist import WHITELIST, enabled_sources, p0_sources

router = APIRouter()


@router.get("/source-registry")
def get_source_registry():
    items = [item.model_dump(mode="json") for item in WHITELIST]
    return {
        "principle": "外部资料只能进入 Case Library，不能直接进入 Strategy Memory",
        "total": len(WHITELIST),
        "p0": len(p0_sources()),
        "enabled": len(enabled_sources()),
        "items": items,
    }


@router.post("/source-registry/sync")
def post_sync_source_registry(db: Session = Depends(get_db)):
    written = sync_source_registry(db)
    return {"written": written, "enabled": len(enabled_sources())}


@router.post("/operating-cases/ingest-seeds")
def post_ingest_seed_cases(db: Session = Depends(get_db)):
    return ingest_seed_corpus(db)


@router.post("/source-registry/diff-rules")
def post_diff_rule_sources(db: Session = Depends(get_db)):
    return diff_enabled_rule_sources(db)


@router.post("/operating-cases/retrieve")
def post_retrieve_cases(payload: dict):
    demand_code = str(payload.get("demand_code") or "")
    if not demand_code:
        raise HTTPException(status_code=400, detail="demand_code required")
    return {
        "priors": retrieve_case_priors(
            demand_code=demand_code,
            family=str(payload.get("family") or ""),
            question=str(payload.get("question") or ""),
            limit=int(payload.get("limit") or 5),
        )
    }
