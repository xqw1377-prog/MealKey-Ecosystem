from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from app.services.llm_engine.bindings import (
    PurposeModelCandidate,
    resolve_candidate_api_key,
    resolve_purpose_model_chain,
)

T = TypeVar("T")


@dataclass
class FailoverAttempt:
    candidate_id: str
    provider: str
    model: str
    ok: bool
    detail: str = ""
    elapsed_ms: int = 0


@dataclass
class FailoverResult:
    ok: bool
    value: Any = None
    candidate: PurposeModelCandidate | None = None
    attempts: list[FailoverAttempt] = field(default_factory=list)
    reason: str = ""
    failover_used: bool = False


def is_retryable_failure(error: Exception | str) -> bool:
    text = str(error).lower()
    markers = (
        "llm_http_408",
        "llm_http_409",
        "llm_http_429",
        "llm_http_500",
        "llm_http_502",
        "llm_http_503",
        "llm_http_504",
        "llm_unreachable",
        "timeout",
        "temporarily",
        "rate limit",
        "overloaded",
        "connection reset",
    )
    return any(marker in text for marker in markers)


def execute_with_failover(
    *,
    purpose: str,
    run: Callable[[PurposeModelCandidate, str], T],
    prefer_model: str | None = None,
) -> FailoverResult:
    """
    同能力静默兜底：按 Purpose 链依次尝试；
    单节点失败继续；整链耗尽才返回失败。
    """
    chain = resolve_purpose_model_chain(purpose)
    if prefer_model:
        want = prefer_model.strip()
        chain = sorted(chain, key=lambda c: 0 if c.model == want else 1)

    if not chain:
        return FailoverResult(ok=False, reason="empty_chain")

    attempts: list[FailoverAttempt] = []
    for index, candidate in enumerate(chain):
        api_key = resolve_candidate_api_key(candidate)
        if not api_key:
            attempts.append(
                FailoverAttempt(
                    candidate_id=candidate.id,
                    provider=candidate.provider,
                    model=candidate.model,
                    ok=False,
                    detail="missing_api_key",
                )
            )
            continue
        try:
            value = run(candidate, api_key)
            attempts.append(
                FailoverAttempt(
                    candidate_id=candidate.id,
                    provider=candidate.provider,
                    model=candidate.model,
                    ok=True,
                    detail="ok",
                )
            )
            return FailoverResult(
                ok=True,
                value=value,
                candidate=candidate,
                attempts=attempts,
                failover_used=index > 0,
                reason="ok",
            )
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                FailoverAttempt(
                    candidate_id=candidate.id,
                    provider=candidate.provider,
                    model=candidate.model,
                    ok=False,
                    detail=str(exc)[:240],
                )
            )
            # 无论是否 retryable，都继续同能力链（独立部署简化策略）
            continue

    return FailoverResult(
        ok=False,
        attempts=attempts,
        failover_used=len(attempts) > 1,
        reason="all_failed",
    )
