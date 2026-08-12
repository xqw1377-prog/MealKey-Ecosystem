from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.services.agents import build_single_agent
from app.services.diagnosis_analysis import build_diagnosis_comparisons


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_diagnosis_agent_builds_multi_period_root_cause_report() -> None:
    db = _session()
    seeded = seed_demo(db)

    result = build_single_agent(db, seeded["store_id"], "diagnosis")

    assert result is not None
    assert 28 <= result["diagnosis_score"] <= 96
    assert result["executive_summary"]
    assert {row["key"] for row in result["comparisons"]} == {
        "same_weekday",
        "week_over_week",
        "month_over_month",
    }
    assert result["comparisons"][0]["status"] == "down"
    assert result["comparisons"][1]["orders_delta_pct"] < 0
    assert result["comparisons"][2]["status"] == "unavailable"
    assert {row["metric"] for row in result["metric_signals"]} == {
        "gmv",
        "orders",
        "impressions",
        "ctr",
        "cvr",
        "aov",
        "repurchase_rate",
        "rating",
        "refund_rate",
    }
    assert result["root_causes"][0]["code"] == "first_impression"
    assert result["root_causes"][0]["evidence"]
    assert result["action_priorities"]
    assert any("退款" in gap for gap in result["data_gaps"])


def test_market_comparison_does_not_invent_market_orders() -> None:
    db = _session()
    seeded = seed_demo(db)

    result = build_single_agent(db, seeded["store_id"], "diagnosis")

    assert result is not None
    market = result["market_comparison"]
    assert market["data_type"] == "proxy"
    assert market["market_orders_delta_pct"] is None
    assert "不能宣称市场份额变化" in market["note"]


def test_comparison_marks_missing_history_unavailable() -> None:
    db = _session()
    seeded = seed_demo(db)
    comparisons = build_diagnosis_comparisons(db, seeded["store_id"])

    month = next(row for row in comparisons if row.key == "month_over_month")
    assert month.status == "unavailable"
    assert month.orders_delta_pct is None
