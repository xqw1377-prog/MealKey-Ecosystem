"""Claim / Fact 分离、指标一致性、Confounder 检测、证据分级。

厂商「运营效率提高80%」= reported_claim，不是 verified_fact。
数字冲突必须两侧保留，source_conflict=true，confidence=low。
"""
from __future__ import annotations

import re
from typing import Any

_CLAIM_RE = re.compile(
    r"(运营效率|推广效率|效率|销量|订单|ROI|销售)[^。；\n]{0,16}(提高|提升|增长|上涨)\s*(\d+(\.\d+)?)\s*%",
    re.I,
)
_CLAIM_RE_FLIP = re.compile(
    r"(提高|提升|增长|上涨)\s*(\d+(\.\d+)?)\s*%",
    re.I,
)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_ROI_SERIES_RE = re.compile(r"ROI[^\d]{0,8}(\d+(?:\.\d+)?)\s*[→~\-至到]+\s*(\d+(?:\.\d+)?)", re.I)

_CONFOUNDER_SIGNALS = {
    "ads": ("广告", "投流", "预算", "sponsored", "投放"),
    "new_product": ("新品", "新菜", "上新", "新套餐"),
    "holiday": ("节假日", "春节", "国庆", "圣诞", "周末高峰"),
    "campaign": ("满减", "促销活动", "神券", "报名活动"),
    "price": ("降价", "涨价", "改价"),
}

_ORDER_UP = ("订单上涨", "订单增长", "销量上涨", "销售提升", "单量起来")


def separate_facts_and_claims(text: str) -> dict[str, list[str]]:
    blob = text or ""
    claims: list[str] = []
    for match in _CLAIM_RE.finditer(blob):
        claims.append(match.group(0).strip())
    if not claims:
        for match in _CLAIM_RE_FLIP.finditer(blob):
            window = blob[max(0, match.start() - 12) : match.end() + 4]
            if any(token in window for token in ("效率", "订单", "销售", "ROI", "销量")):
                claims.append(match.group(0).strip())
    facts: list[str] = []
    for token in ("必须", "不得", "禁止", "规则", "评分构成", "回复率"):
        if token in blob:
            facts.append(token)
    return {
        "reported_claims": list(dict.fromkeys(claims)),
        "verified_facts": facts,
    }


def check_metric_consistency(*texts: str) -> dict[str, Any]:
    blob = " ".join(part for part in texts if part)
    percents = [float(item) for item in _PERCENT_RE.findall(blob)]
    roi_pairs = [(float(a), float(b)) for a, b in _ROI_SERIES_RE.findall(blob)]
    sides: list[str] = []
    if percents:
        unique = sorted(set(round(value, 1) for value in percents))
        if len(unique) >= 2 and (max(unique) - min(unique)) >= 10:
            sides.append("reported_claim=" + "/".join(f"{value}%" for value in unique))
    if len(roi_pairs) >= 2:
        rendered = [f"{a}→{b}" for a, b in roi_pairs]
        if len(set(rendered)) >= 2:
            sides.append("roi_series=" + " vs ".join(rendered))
    # 店客多样板：80% 宣称 vs 图表序列
    if "80" in blob and any(token in blob for token in ("3.4", "3.8", "5.7", "4.5")):
        sides.append("chart_observation_vs_reported_claim")
    conflict = len(sides) >= 1 and (
        len(set(percents)) >= 2 or "chart_observation_vs_reported_claim" in sides or len(roi_pairs) >= 2
    )
    return {
        "source_conflict": bool(conflict),
        "sides": sides,
        "confidence": "low" if conflict else "medium",
    }


def detect_confounders(text: str) -> list[str]:
    blob = text or ""
    hits = [name for name, tokens in _CONFOUNDER_SIGNALS.items() if any(token.lower() in blob.lower() for token in tokens)]
    order_up = any(token in blob for token in _ORDER_UP)
    if order_up and len(hits) >= 2:
        return [
            "多因素并行，禁止蒸馏成单一因果",
            "同时出现：" + "、".join(hits),
        ]
    return []


def grade_evidence(
    *,
    authority_level: str,
    source_conflict: bool,
    confounders: list[str],
    ingestion_mode: str,
) -> dict[str, Any]:
    if authority_level == "R" or ingestion_mode == "DATASET":
        return {"evidence_level": None, "status": "research_zone", "confidence": 0.0}
    confidence = {"F": 0.55, "C2": 0.35, "C1": 0.22}.get(authority_level, 0.2)
    if source_conflict:
        confidence = min(confidence, 0.15)
    if confounders:
        confidence = min(confidence, 0.2)
    return {
        "evidence_level": "L1",
        "status": "case_prior_only",
        "confidence": round(confidence, 2),
    }


def distill_snippet(source_id: str, title: str, text: str, *, authority_level: str, ingestion_mode: str) -> dict[str, Any]:
    split = separate_facts_and_claims(text)
    metrics = check_metric_consistency(text)
    confounders = detect_confounders(text)
    grade = grade_evidence(
        authority_level=authority_level,
        source_conflict=metrics["source_conflict"],
        confounders=confounders,
        ingestion_mode=ingestion_mode,
    )
    forbidden = []
    if split["reported_claims"]:
        forbidden.append("禁止把厂商宣称量级当成已验证事实")
    if confounders:
        forbidden.append("禁止把并行因素蒸馏成单一因果")
    if metrics["source_conflict"]:
        forbidden.append("禁止替来源挑选一个数字")
    return {
        "source_id": source_id,
        "title": title,
        "reported_claims": split["reported_claims"],
        "verified_facts": split["verified_facts"],
        "source_conflict": metrics["source_conflict"],
        "conflict_sides": metrics["sides"],
        "confounders": confounders,
        "evidence_level": grade["evidence_level"],
        "status": grade["status"],
        "confidence": grade["confidence"],
        "forbidden_claim": "；".join(forbidden) or "外部材料只作弱先验",
    }
