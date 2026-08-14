"""Operating Benchmark + AI Governance + Memory Lifecycle 测试。

验证需求 #181-200 的核心能力。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, Store
from app.models.strategy_memory import StrategyMemoryRecord


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_store(db: Session) -> str:
    m = Merchant(name="测试")
    db.add(m)
    db.flush()
    s = Store(merchant_id=m.id, name="测试店")
    db.add(s)
    db.flush()
    return s.id


# ═══════════════════════════════════════════════════════════
# Benchmark
# ═══════════════════════════════════════════════════════════


def test_benchmark_has_200_demands() -> None:
    from app.services.operating_benchmark import DEMANDS
    assert len(DEMANDS) == 200
    ids = [d["id"] for d in DEMANDS]
    assert min(ids) == 1
    assert max(ids) == 200
    assert len(set(ids)) == 200  # 无重复


def test_benchmark_seed_and_report() -> None:
    from app.services.operating_benchmark import benchmark_report, seed_demands

    db = _session()
    inserted = seed_demands(db)
    assert inserted == 200

    # 幂等
    inserted2 = seed_demands(db)
    assert inserted2 == 0

    report = benchmark_report(db)
    assert report["total_demands"] == 200
    assert report["covered"] > 0
    assert report["p0_total"] > 0
    assert "by_category" in report
    db.close()


def test_benchmark_questions_readable_and_mapped() -> None:
    from app.services.operating_benchmark import DEMANDS, _garbled
    from app.services.operating_demands.catalog import by_id

    assert len(DEMANDS) == 200
    assert all(d["id"] for d in DEMANDS)
    for d in DEMANDS:
        assert not _garbled(str(d["q"])), d["id"]
        assert not _garbled(str(d["cat"])), d["id"]
        assert d["loop"] in {"A", "B", "C"}, d["id"]
        assert d["cov"] in {"covered", "partial"}, d["id"]
        assert str(d.get("svc") or "").strip(), d["id"]
        if d["id"] <= 100:
            assert d["q"] == by_id(d["id"]).question
    assert all(d["cov"] != "not_covered" for d in DEMANDS)
    p0 = [d for d in DEMANDS if d["pri"] == "P0"]
    assert p0
    assert all(d["cov"] in {"covered", "partial"} for d in p0)


# ═══════════════════════════════════════════════════════════
# Memory Lifecycle (#199)
# ═══════════════════════════════════════════════════════════


def test_memory_lifecycle_expires_old() -> None:
    from app.services.memory_lifecycle import run_memory_lifecycle

    db = _session()
    sid = _seed_store(db)

    # 插入一条 400 天前的 Memory
    old = StrategyMemoryRecord(
        store_id=sid,
        action_type="change_main_image",
        result="positive",
        lift_pct=10.0,
        lesson="换图成功",
        reuse_when="复用",
        confidence=0.8,
    )
    old.created_at = datetime.now(timezone.utc) - timedelta(days=400)
    db.add(old)
    db.commit()

    stats = run_memory_lifecycle(db)
    assert stats["expired"] >= 1

    # 确认被标记过期
    record = db.query(StrategyMemoryRecord).first()
    assert record.result == "expired"
    assert record.confidence == 0.0
    db.close()


def test_memory_lifecycle_downgrades_aging() -> None:
    from app.services.memory_lifecycle import run_memory_lifecycle

    db = _session()
    sid = _seed_store(db)

    # 200天前的 Memory,高 confidence
    aging = StrategyMemoryRecord(
        store_id=sid,
        action_type="adjust_price",
        result="positive",
        lift_pct=5.0,
        lesson="涨价成功",
        reuse_when="复用",
        confidence=0.85,
    )
    aging.created_at = datetime.now(timezone.utc) - timedelta(days=200)
    db.add(aging)
    db.commit()

    run_memory_lifecycle(db)
    record = db.query(StrategyMemoryRecord).first()
    assert record.confidence <= 0.3  # 降权了
    db.close()


def test_get_active_memories_excludes_expired() -> None:
    from app.services.memory_lifecycle import get_active_memories

    db = _session()
    sid = _seed_store(db)

    # 一条有效,一条过期
    active = StrategyMemoryRecord(
        store_id=sid, action_type="change_title", result="positive",
        lift_pct=8.0, lesson="成功", reuse_when="复用", confidence=0.8,
    )
    expired = StrategyMemoryRecord(
        store_id=sid, action_type="change_image", result="expired",
        lift_pct=0, lesson="过期", reuse_when="", confidence=0.0,
    )
    db.add_all([active, expired])
    db.commit()

    result = get_active_memories(db, sid)
    assert len(result) == 1
    assert result[0].action_type == "change_title"
    db.close()


# ═══════════════════════════════════════════════════════════
# AI Governance (#181-185)
# ═══════════════════════════════════════════════════════════


def test_confidence_display_high() -> None:
    from app.services.ai_governance import confidence_display
    result = confidence_display(0.9)
    assert result["level"] == "high"
    assert result["pct"] == 90


def test_confidence_display_low() -> None:
    from app.services.ai_governance import confidence_display
    result = confidence_display(0.3)
    assert result["level"] == "very_low"


def test_confidence_display_none() -> None:
    from app.services.ai_governance import confidence_display
    result = confidence_display(None)
    assert result["level"] == "unknown"


def test_explain_data_provenance() -> None:
    from app.services.ai_governance import explain_data_provenance

    db = _session()
    sid = _seed_store(db)
    result = explain_data_provenance(db, sid)
    assert "data_used" in result
    assert "data_missing" in result
    # 新门店应该什么都缺
    assert len(result["data_missing"]) > 0
    db.close()


def test_explain_judgment_no_rec() -> None:
    from app.services.ai_governance import explain_judgment

    db = _session()
    sid = _seed_store(db)
    result = explain_judgment(db, sid, question="为什么订单掉了")
    assert result["primary_reason"]  # 应该有规则解释
    db.close()
