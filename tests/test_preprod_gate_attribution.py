"""PRE-PROD-GATE-01 P0-8 回归：归因/校验失败不得静默吞掉。

Invariant #5：Verification failure 永远不能静默。

覆盖两处漏网：
1. closed_loop._close_observation：evaluate_experiment 未预期异常 →
   experiment.result=unknown + FAILED_VERIFICATION marker + AgentEventLog error，
   loop item 的 summary 必须反映「归因失败」而非正常「待确认」。
2. experiment_attribution 护栏检查 except 不再 pass：
   - 利润护栏故障 → positive 降级 neutral + warning
   - CPC 护栏故障 → warning（不静默）
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
import app.models.business_facts as bf
import app.services.experiment_attribution as ea
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.agent_event import AgentEvent
from app.models.entities import Merchant, Store
from app.models.ohre import Experiment, Recommendation
from app.services.closed_loop import (
    ensure_now_loop,
    mark_loop_executed,
    tick_observing_loops,
)
from app.services.execution_pack import build_execution_pack


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session) -> Store:
    merchant = Merchant(name="测试商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="老王牛肉饭")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def _now_flow() -> dict:
    pack = build_execution_pack("change_main_image", object_name="黑椒牛肉饭", title="先换主图")
    return {
        "now": {
            "id": "nba-1",
            "source_card_id": "nba-1",
            "title": "先换黑椒牛肉饭主图",
            "why_now": "点击率连续下滑，份量感弱",
            "ai_already_did": "主图主体太小，份量看不清",
            "business_impact": "预计今天少几单",
            "execution_pack": pack,
        }
    }


def _executed_orders_experiment(db: Session, store_id: str, item_id: str) -> Experiment:
    """构造一条已过观察窗、item 级、metric=orders、baseline=10 的 pending 实验。

    seed_demo 在 observe 窗（最近 7 天）每天 orders=8 → observed≈56 → lift≈+460%（positive）。
    """
    rec = Recommendation(
        store_id=store_id,
        scope="item",
        object_ref=f"item:{item_id}",
        action_type="change_main_image",
        expected_metric="orders",
        expected_lift_pct_low=6,
        expected_lift_pct_high=12,
        window_hours=24,
        confidence=0.7,
        status="executed",
        executed_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    db.add(rec)
    db.flush()
    exp = Experiment(
        recommendation_id=rec.id,
        store_id=store_id,
        item_id=item_id,
        baseline_value=10.0,
        result="pending",
        attribution_quality="medium",
        control_desc="测试",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def _calc_window_dates():
    """与 store_state._calc_window(days=7) 同口径，避免依赖内部实现。"""
    today = date.today()
    observe_to = today - timedelta(days=1)
    observe_from = observe_to - timedelta(days=6)
    baseline_to = observe_from - timedelta(days=1)
    baseline_from = baseline_to - timedelta(days=6)
    return observe_from, observe_to, baseline_from, baseline_to


class _CorruptProfit:
    """模拟利润护栏数据损坏：take_home_rate 访问抛异常。"""

    def __bool__(self) -> bool:
        return True

    @property
    def take_home_rate(self):
        raise RuntimeError("profit take_home_rate corrupt")


def _mock_state(*, profit):
    observe_from, observe_to, baseline_from, baseline_to = _calc_window_dates()
    return SimpleNamespace(
        window=SimpleNamespace(
            from_day=observe_from,
            to_day=observe_to,
            compare_from_day=baseline_from,
            compare_to_day=baseline_to,
        ),
        kpis={},
        profit=profit,
    )


# ── Test A: closed_loop evaluate_experiment 未预期异常 → FAILED_VERIFICATION ──

def test_p0_8_evaluate_failure_marks_failed_verification(monkeypatch) -> None:
    db = _session()
    store = _store(db)
    item = ensure_now_loop(db, store.id, decision_flow=_now_flow(), events=None)
    marked = mark_loop_executed(db, store.id, item.id)
    marked.observe_until = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    exp = db.get(Experiment, marked.experiment_id)
    assert exp is not None
    assert exp.result in {None, "pending"}

    # 注入未预期异常：evaluate_experiment 抛错
    monkeypatch.setattr(
        ea, "evaluate_experiment", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("synthetic boom"))
    )

    result = tick_observing_loops(db)
    assert marked.id in result["ready"]

    db.refresh(marked)
    db.refresh(exp)

    # loop item 不得停在 pending；必须进入 result_ready 并标记归因失败（不是「待确认」）。
    # item.notes 经过 humanize_operator_text，下划线被替换为空格 → "FAILED VERIFICATION"。
    assert marked.status == "result_ready"
    assert marked.result == "unknown"
    assert "归因失败" in (marked.notes or "")
    assert "FAILED VERIFICATION" in (marked.notes or "")

    # experiment.notes 未经 humanize，保留原始 marker "FAILED_VERIFICATION"
    assert exp.result == "unknown"
    assert "FAILED_VERIFICATION" in (exp.notes or "")

    # AgentEventLog 必须留下一条 error 事件，session_id 指向该实验
    events = list(
        db.execute(
            select(AgentEvent).where(AgentEvent.session_id == f"verify:{exp.id}")
        ).scalars()
    )
    assert events, "FAILED_VERIFICATION 未写 AgentEventLog"
    assert any(e.error_message == "FAILED_VERIFICATION" for e in events)


# ── Test B1: 利润护栏故障 → positive 降级 neutral + warning ──

def test_p0_8_profit_guardrail_failure_downgrades_positive(monkeypatch, caplog) -> None:
    db = _session()
    seeded = seed_demo(db)
    exp = _executed_orders_experiment(db, seeded["store_id"], seeded["item_id"])

    monkeypatch.setattr(
        ea, "build_store_state", lambda db, store_id, days=7: _mock_state(profit=_CorruptProfit())
    )
    caplog.set_level("WARNING", logger=ea.logger.name)

    outcome = ea.evaluate_experiment(db, exp, days=7)
    db.commit()
    db.refresh(exp)

    # 本应是 positive（lift≈+460%），但利润护栏自身故障 → 降级 neutral，不得静默保留 positive
    assert outcome.result != "positive", "利润护栏故障时 positive 不得漏网保留"
    assert outcome.result == "neutral"
    assert exp.result == "neutral"
    assert "利润护栏检查失败" in (exp.notes or "")
    assert any("profit guardrail check failed" in r.message for r in caplog.records)


# ── Test B2: CPC 护栏故障 → warning（不静默） ──

def test_p0_8_cpc_guardrail_failure_emits_warning(monkeypatch, caplog) -> None:
    db = _session()
    seeded = seed_demo(db)
    exp = _executed_orders_experiment(db, seeded["store_id"], seeded["item_id"])

    # profit=None：利润护栏不触发异常；让 CPC 护栏的 AdSpendDaily 查询抛错
    monkeypatch.setattr(ea, "build_store_state", lambda db, store_id, days=7: _mock_state(profit=None))

    class _AdSpendBoom:
        # 非 SQLAlchemy mapped class → select() 抛 InvalidRequestError，被 CPC 护栏 except 捕获
        pass

    monkeypatch.setattr(bf, "AdSpendDaily", _AdSpendBoom, raising=False)

    caplog.set_level("WARNING", logger=ea.logger.name)
    outcome = ea.evaluate_experiment(db, exp, days=7)
    db.commit()
    db.refresh(exp)

    # CPC 护栏故障不得静默：必须有 warning 日志
    assert any("cpc guardrail check failed" in r.message for r in caplog.records), \
        "CPC 护栏故障被静默吞掉"
    # 主结果仍按真实 lift 判定（positive），但护栏告警已记录；若降级也接受
    assert outcome.result in {"positive", "neutral", "unknown"}
