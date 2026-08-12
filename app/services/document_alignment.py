from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import MenuItem, Store
from app.models.intake import IntakeRawAsset, IntakeSubmission

_FIELD_LABELS = {
    "store_name": "门店名称",
    "category": "经营品类",
    "area": "商圈区域",
    "audience": "核心客群",
    "pain": "当前痛点",
    "business_hours": "营业时间",
}

_FIELD_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "store_name": [
        re.compile(r"(?:店名|门店|店铺)\s*[:：]\s*([^\n，。,；;]+)"),
    ],
    "category": [
        re.compile(r"(?:品类|类目|经营品类)\s*[:：]\s*([^\n，。,；;]+)"),
    ],
    "area": [
        re.compile(r"(?:商圈|区域|片区|位置)\s*[:：]\s*([^\n，。,；;]+)"),
    ],
    "audience": [
        re.compile(r"(?:客群|人群|受众|用户)\s*[:：]\s*([^\n。；;]+)"),
    ],
    "pain": [
        re.compile(r"(?:痛点|问题|核心问题|经营问题)\s*[:：]\s*([^\n。；;]+)"),
    ],
    "business_hours": [
        re.compile(r"(?:营业时间|营业时段)\s*[:：]\s*([^\n，。,；;]+)"),
    ],
}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[\s:：,，。.;；、/\-]+", "", str(value).strip().lower())


def _trim_excerpt(text: str, limit: int = 80) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}..."


def _split_segments(text: str) -> list[str]:
    parts = re.split(r"[\n\r]+|(?<=[。！？!?；;])", text)
    return [_trim_excerpt(part) for part in parts if part and part.strip()]


def _values_match(canonical_value: Any, candidate_value: Any) -> bool:
    canonical = _normalize_text(canonical_value)
    candidate = _normalize_text(candidate_value)
    if not canonical or not candidate:
        return False
    return canonical in candidate or candidate in canonical


def _load_store_with_menu(db: Session, store_id: str) -> Store | None:
    stmt = (
        select(Store)
        .options(
            selectinload(Store.merchant),
            selectinload(Store.items).selectinload(MenuItem.current_version),
        )
        .where(Store.id == store_id)
    )
    return db.execute(stmt).scalar_one_or_none()


def _submissions(db: Session, store_id: str) -> list[IntakeSubmission]:
    stmt = (
        select(IntakeSubmission)
        .where(IntakeSubmission.store_id == store_id)
        .order_by(IntakeSubmission.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _load_assets(db: Session, submission_ids: list[str]) -> list[IntakeRawAsset]:
    if not submission_ids:
        return []
    stmt = (
        select(IntakeRawAsset)
        .where(IntakeRawAsset.submission_id.in_(submission_ids))
        .order_by(IntakeRawAsset.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _canonical_profile(store: Store) -> dict[str, Any]:
    menu_names: list[str] = []
    price_values: list[float] = []
    for item in store.items:
        current = item.current_version
        if not current:
            continue
        menu_names.append(current.name)
        if current.price is not None:
            price_values.append(float(current.price))

    price_band = None
    if price_values:
        price_band = f"{int(min(price_values))}-{int(max(price_values))}"

    return {
        "store_name": store.name,
        "category": getattr(store.merchant, "category", None),
        "area": store.area,
        "audience": store.primary_audience,
        "pain": store.primary_pain,
        "business_hours": getattr(store.merchant, "business_hours", None),
        "city": store.city,
        "menu_count": len(menu_names),
        "menu_items": menu_names[:3],
        "price_band": price_band,
    }


def _pick_best_value(claims: list[dict[str, Any]]) -> tuple[Any, float, list[dict[str, Any]]]:
    if not claims:
        return None, 0.0, []
    buckets: dict[str, dict[str, Any]] = {}
    for claim in claims:
        normalized = _normalize_text(claim["value"])
        if not normalized:
            continue
        bucket = buckets.setdefault(
            normalized,
            {"value": claim["value"], "score": 0.0, "evidence": []},
        )
        bucket["score"] += 1.2 if claim.get("match_type") == "explicit" else 0.6
        bucket["evidence"].append(claim)
    if not buckets:
        return None, 0.0, []
    best = max(buckets.values(), key=lambda row: row["score"])
    confidence = min(0.95, 0.45 + best["score"] * 0.12)
    return best["value"], confidence, best["evidence"][:3]


def _extract_menu_candidates(assets: list[IntakeRawAsset]) -> list[dict[str, Any]]:
    pattern = re.compile(r"([^\d\n]{2,20}?)(\d{1,3}(?:\.\d{1,2})?)\s*元?")
    buckets: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not asset.raw_text:
            continue
        for match in pattern.finditer(asset.raw_text):
            name = match.group(1).strip("：: \t-")
            if len(name) < 2:
                continue
            normalized = _normalize_text(name)
            if not normalized:
                continue
            row = buckets.setdefault(
                normalized,
                {
                    "name": name,
                    "price": float(match.group(2)),
                    "evidence_count": 0,
                    "sources": [],
                },
            )
            row["evidence_count"] += 1
            if asset.label not in row["sources"]:
                row["sources"].append(asset.label)
    candidates = list(buckets.values())
    candidates.sort(key=lambda row: (row["evidence_count"], row["name"]), reverse=True)
    return candidates[:8]


def _extract_claims(assets: list[IntakeRawAsset], canonical_profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    claims: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    canonical_fields = ["store_name", "category", "area", "audience", "pain", "business_hours"]

    for asset in assets:
        if asset.raw_text:
            asset_segments = _split_segments(asset.raw_text)
            for segment in asset_segments:
                segment_record = {
                    "asset_type": asset.asset_type,
                    "label": asset.label,
                    "excerpt": segment,
                }
                segments.append(segment_record)
                for field in canonical_fields:
                    for pattern in _FIELD_PATTERNS[field]:
                        match = pattern.search(segment)
                        if match:
                            claims.append(
                                {
                                    "field": field,
                                    "value": match.group(1).strip(),
                                    "source": asset.label,
                                    "asset_type": asset.asset_type,
                                    "excerpt": segment,
                                    "match_type": "explicit",
                                }
                            )

        if asset.source_url:
            segments.append(
                {
                    "asset_type": asset.asset_type,
                    "label": asset.label,
                    "excerpt": str(asset.source_url),
                }
            )

    for field in canonical_fields:
        canonical_value = canonical_profile.get(field)
        if not canonical_value:
            continue
        for segment in segments:
            if _values_match(canonical_value, segment["excerpt"]):
                claims.append(
                    {
                        "field": field,
                        "value": canonical_value,
                        "source": segment["label"],
                        "asset_type": segment["asset_type"],
                        "excerpt": segment["excerpt"],
                        "match_type": "reference",
                    }
                )

    return claims, segments


def _build_document_profile(claims: list[dict[str, Any]], canonical_profile: dict[str, Any]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    extracted_profile: dict[str, Any] = {}
    suggested_updates: list[dict[str, Any]] = []
    for field, label in _FIELD_LABELS.items():
        field_claims = [claim for claim in claims if claim["field"] == field]
        extracted_value, confidence, evidence = _pick_best_value(field_claims)
        canonical_value = canonical_profile.get(field)
        status = "missing"
        if canonical_value and extracted_value:
            status = "aligned" if _values_match(canonical_value, extracted_value) else "conflict"
        elif canonical_value and not extracted_value:
            status = "system_only"
        elif extracted_value and not canonical_value:
            status = "document_only"

        evidence_payload = [
            {
                "source": row["source"],
                "asset_type": row["asset_type"],
                "excerpt": row["excerpt"],
                "value": row["value"],
            }
            for row in evidence
        ]
        fields.append(
            {
                "field": field,
                "label": label,
                "status": status,
                "canonical_value": canonical_value,
                "document_value": extracted_value,
                "confidence": round(confidence, 2) if confidence else 0,
                "evidence": evidence_payload,
            }
        )
        if extracted_value is not None:
            extracted_profile[field] = extracted_value
        if extracted_value and not canonical_value and confidence >= 0.69:
            suggested_updates.append(
                {
                    "field": field,
                    "label": label,
                    "current_value": canonical_value,
                    "suggested_value": extracted_value,
                    "reason": "文档中有较稳定证据，但系统主数据为空。",
                    "confidence": round(confidence, 2),
                }
            )
    return {
        "fields": fields,
        "extracted_profile": extracted_profile,
        "suggested_updates": suggested_updates,
    }


def build_document_alignment(db: Session, store_id: str) -> dict[str, Any]:
    store = _load_store_with_menu(db, store_id)
    if store is None:
        return {
            "status": "missing_store",
            "alignment_score": 0,
            "summary": "门店不存在，无法进行文档对齐。",
            "documents_count": 0,
            "submission_count": 0,
            "asset_types": [],
            "facts": [],
            "conflicts": [],
            "missing_fields": [],
            "recommendations": ["先创建门店资料。"],
            "canonical_profile": {},
            "document_profile": {},
            "field_statuses": [],
            "suggested_updates": [],
            "menu_candidates": [],
        }

    canonical_profile = _canonical_profile(store)
    submissions = _submissions(db, store_id)
    if not submissions:
        return {
            "status": "missing_documents",
            "alignment_score": 22,
            "summary": "当前还没有接入原始资料，系统只能基于结构化经营数据判断，无法做文档证据对齐。",
            "documents_count": 0,
            "submission_count": 0,
            "asset_types": [],
            "facts": [],
            "conflicts": [],
            "missing_fields": [field for field in _FIELD_LABELS if canonical_profile.get(field)],
            "recommendations": [
                "补充门店资料、菜单说明、截图备注或复盘笔记。",
                "让关键字段至少在 1 份原始资料里有明确证据。",
            ],
            "canonical_profile": canonical_profile,
            "document_profile": {},
            "field_statuses": [],
            "suggested_updates": [],
            "menu_candidates": [],
        }

    assets = _load_assets(db, [submission.id for submission in submissions])
    claims, segments = _extract_claims(assets, canonical_profile)
    document_profile_bundle = _build_document_profile(claims, canonical_profile)
    menu_candidates = _extract_menu_candidates(assets)

    facts: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    missing_fields: list[str] = []
    covered_fields = 0

    for field, label in _FIELD_LABELS.items():
        canonical_value = canonical_profile.get(field)
        if not canonical_value:
            continue

        field_claims = [claim for claim in claims if claim["field"] == field]
        supporting = []
        conflicting = []
        seen_support: set[tuple[str, str]] = set()
        seen_conflict: set[tuple[str, str]] = set()

        for claim in field_claims:
            record = {
                "source": claim["source"],
                "asset_type": claim["asset_type"],
                "excerpt": claim["excerpt"],
                "value": claim["value"],
                "match_type": claim["match_type"],
            }
            key = (record["source"], record["excerpt"])
            if _values_match(canonical_value, claim["value"]):
                if key not in seen_support:
                    supporting.append(record)
                    seen_support.add(key)
            elif claim["match_type"] == "explicit":
                if key not in seen_conflict:
                    conflicting.append(record)
                    seen_conflict.add(key)

        if supporting:
            covered_fields += 1
        else:
            missing_fields.append(field)

        facts.append(
            {
                "field": field,
                "label": label,
                "canonical_value": canonical_value,
                "evidence_count": len(supporting),
                "evidence": supporting[:3],
            }
        )

        for record in conflicting[:2]:
            conflicts.append(
                {
                    "field": field,
                    "label": label,
                    "canonical_value": canonical_value,
                    "document_value": record["value"],
                    "source": record["source"],
                    "excerpt": record["excerpt"],
                    "severity": "high" if field in {"store_name", "category", "area"} else "medium",
                }
            )

    score = 34
    score += min(42, covered_fields * 9)
    score += min(12, len(segments))
    score -= min(38, len(conflicts) * 14)
    score -= len(missing_fields) * 4
    alignment_score = max(18, min(98, score))

    if conflicts:
        status = "conflict"
        summary = "原始资料和系统事实存在口径冲突，先统一门店主数据，再继续做经营判断。"
    elif not assets:
        status = "missing_documents"
        summary = "当前 intake 记录存在，但没有有效原始资料文本，文档证据还没有进入系统。"
    elif covered_fields >= 4:
        status = "aligned"
        summary = "关键门店事实已经能在原始资料里找到证据，后续诊断可以围绕同一口径展开。"
    else:
        status = "partial"
        summary = "已有部分资料进入系统，但关键字段证据还不完整，建议补齐后再做更强判断。"

    recommendations: list[str] = []
    if conflicts:
        recommendations.append("先修正文档里与门店主数据冲突的字段。")
    if document_profile_bundle["suggested_updates"]:
        update_labels = "、".join(row["label"] for row in document_profile_bundle["suggested_updates"][:3])
        recommendations.append(f"把 {update_labels} 从文档事实同步进系统主数据。")
    if missing_fields:
        missing_labels = "、".join(_FIELD_LABELS[field] for field in missing_fields[:3])
        recommendations.append(f"优先补齐 {missing_labels} 的原始证据。")
    if not recommendations:
        recommendations.append("继续沉淀截图备注、复盘结论和菜单说明，增强后续问答依据。")

    asset_types = sorted({asset.asset_type for asset in assets})
    evidence_density = round(len(claims) / len(assets), 2) if assets else 0

    return {
        "status": status,
        "alignment_score": alignment_score,
        "summary": summary,
        "documents_count": len(assets),
        "submission_count": len(submissions),
        "asset_types": asset_types,
        "evidence_density": evidence_density,
        "facts": facts,
        "conflicts": conflicts,
        "missing_fields": missing_fields,
        "recommendations": recommendations[:3],
        "canonical_profile": canonical_profile,
        "document_profile": document_profile_bundle["extracted_profile"],
        "field_statuses": document_profile_bundle["fields"],
        "suggested_updates": document_profile_bundle["suggested_updates"][:5],
        "menu_candidates": menu_candidates,
        "corpus": {
            "submissions": [
                {
                    "submission_id": submission.id,
                    "created_at": submission.created_at.isoformat() if submission.created_at else None,
                    "readiness": submission.readiness,
                    "notes": submission.notes,
                }
                for submission in submissions[:5]
            ],
            "top_segments": [
                {
                    "source": row["label"],
                    "asset_type": row["asset_type"],
                    "excerpt": row["excerpt"],
                }
                for row in segments[:12]
            ],
        },
    }


def preview_document_alignment(payload: dict[str, Any]) -> dict[str, Any]:
    canonical_profile = {
        "store_name": payload.get("store_name"),
        "category": payload.get("category"),
        "area": payload.get("area"),
        "audience": payload.get("audience"),
        "pain": payload.get("pain"),
        "business_hours": payload.get("business_hours"),
        "city": payload.get("city"),
    }
    raw_assets = payload.get("raw_assets") or []
    pseudo_assets = []
    for index, asset in enumerate(raw_assets):
        pseudo_assets.append(
            IntakeRawAsset(
                submission_id=f"preview-{index}",
                asset_type=asset.get("asset_type") or "report_note",
                label=asset.get("label") or f"preview-{index}",
                source_url=str(asset.get("source_url")) if asset.get("source_url") else None,
                raw_text=asset.get("raw_text"),
                parsed_json=json.dumps(asset, ensure_ascii=False),
            )
        )
    claims, segments = _extract_claims(pseudo_assets, canonical_profile)
    bundle = _build_document_profile(claims, canonical_profile)
    conflicts = [row for row in bundle["fields"] if row["status"] == "conflict"]
    missing_fields = [row["field"] for row in bundle["fields"] if row["status"] in {"missing", "system_only"} and row["canonical_value"]]
    covered_fields = sum(1 for row in bundle["fields"] if row["status"] == "aligned")
    score = 36 + covered_fields * 10 + min(10, len(segments)) - len(conflicts) * 15 - len(missing_fields) * 4
    return {
        "alignment_score": max(18, min(98, score)),
        "document_profile": bundle["extracted_profile"],
        "field_statuses": bundle["fields"],
        "suggested_updates": bundle["suggested_updates"][:5],
        "menu_candidates": _extract_menu_candidates(pseudo_assets),
        "documents_count": len(pseudo_assets),
        "top_segments": [
            {
                "source": row["label"],
                "asset_type": row["asset_type"],
                "excerpt": row["excerpt"],
            }
            for row in segments[:10]
        ],
    }
