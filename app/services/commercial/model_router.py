"""Model Router：按经营价值分配模型，而不是平均撒。"""

from __future__ import annotations

from typing import Literal

ModelTier = Literal["code", "luna", "terra", "sol"]

# 完全不该用 LLM
CODE_PURPOSES = {
    "profit_formula",
    "yoy_mom",
    "promo_stack",
    "threshold",
    "experiment_expiry",
    "permission",
    "risk_gate",
    "workthread_state",
    "pricing_quote",
    "commission_split",
}

LUNA_PURPOSES = {
    "classify",
    "summarize",
    "ordinary_reply",
    "extract",
    "light_judgment",
    "free_audit_extract",
}

TERRA_PURPOSES = {
    "operating_diagnosis",
    "action_generate",
    "campaign_judge",
    "product_optimize",
    "free_audit_diagnose",
}

SOL_PURPOSES = {
    "complex_attribution",
    "cross_domain_decision",
    "high_value_anomaly",
    "owner_critical_question",
    "enterprise_audit",
}

PURPOSE_ALIASES = {
    "general.consulting": "terra",
    "general.polish": "luna",
    "brand.structured_output": "luna",
    "menu.simulation_explain": "terra",
    "diagnosis": "terra",
    "review_reply": "luna",
    "change_title": "luna",
}


def route_model(purpose: str, *, budget_state: str = "normal", lane: str = "operating") -> ModelTier:
    key = str(purpose or "").strip()
    if key in CODE_PURPOSES:
        return "code"
    if key in SOL_PURPOSES:
        tier: ModelTier = "sol"
    elif key in TERRA_PURPOSES:
        tier = "terra"
    elif key in LUNA_PURPOSES:
        tier = "luna"
    elif key in PURPOSE_ALIASES:
        mapped = PURPOSE_ALIASES[key]
        tier = mapped if mapped in {"code", "luna", "terra", "sol"} else "terra"
    else:
        tier = "terra"

    if lane == "acquisition" and tier == "sol" and purpose != "enterprise_audit":
        return "terra"
    if budget_state == "throttle" and tier == "sol":
        return "terra"
    if budget_state == "cap_noncritical" and tier in {"terra", "sol"} and purpose not in SOL_PURPOSES:
        return "luna"
    return tier


def high_value_continues(purpose: str, budget_state: str) -> bool:
    """预算打满时，高价值异常 / 风险 / 已有 WorkThread 继续跑。"""
    if budget_state != "cap_noncritical":
        return True
    return purpose in SOL_PURPOSES or purpose in {"risk_gate", "workthread_state", "permission", "experiment_expiry"}
