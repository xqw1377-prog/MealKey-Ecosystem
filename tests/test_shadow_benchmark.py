"""Shadow Benchmark V1 测试 — 30 cases × Local Runtime。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, Store


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)

def _seed(db):
    m = Merchant(name="t"); db.add(m); db.flush()
    s = Store(merchant_id=m.id, name="benchmark store"); db.add(s); db.flush()
    return s.id


def test_benchmark_has_30_cases() -> None:
    from app.services.shadow_benchmark import BENCHMARK_CASES
    assert len(BENCHMARK_CASES) == 30
    ids = [c["id"] for c in BENCHMARK_CASES]
    assert len(set(ids)) == 30  # 无重复
    # 每个case有必要字段
    for c in BENCHMARK_CASES:
        assert c["question"]
        assert c["expected_direction"]
        assert c["category"]


def test_benchmark_local_runtime() -> None:
    from app.services.shadow_benchmark import run_shadow_benchmark
    db = _session()
    sid = _seed(db)
    reports = run_shadow_benchmark(db, sid, runtimes=["local"])
    assert "local" in reports
    report = reports["local"]
    assert report.total_cases == 30
    summary = report.summary()
    print(f"\n=== Shadow Benchmark Report (local) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    # Local runtime 应该至少能完成一些 case
    assert summary["total_cases"] == 30
    db.close()


def test_case_score_evaluation() -> None:
    from app.services.shadow_benchmark import _evaluate_case
    case = {
        "id": "TEST",
        "category": "profit",
        "question": "test",
        "expected_direction": "买流水",
        "forbidden_actions": ["加大投放"],
        "expected_tools": ["profit_check"],
        "has_unknown": True,
    }
    # runtime 正确识别 UNKNOWN
    good_result = {
        "candidate_odos": [{"type": "profit_unknown"}],
        "unknown_facts": ["food_cost"],
        "errors": [],
        "runtime": "local",
    }
    score = _evaluate_case(case, good_result)
    assert score.unknown_violated is False
    assert score.direction_correct is True

    # runtime 没识别 UNKNOWN → 违规
    bad_result = {
        "candidate_odos": [{"type": "suggest_action"}],
        "unknown_facts": [],
        "errors": [],
        "runtime": "local",
    }
    score2 = _evaluate_case(case, bad_result)
    assert score2.unknown_violated is True
