"""Agent 增强功能测试（P0-2 / P1-1 / P1-2 / P1-3）。

覆盖：
- P0-2：agent_narrator 在 LLM 启用时返回 narrative，关闭时返回 None；
- P1-1：thresholds 集中配置可被读取；
- P1-2：CRM 无真实数据时降级（estimated_count=0、blocker 提示）；
- P1-3：矩阵 agent 的 execution_phase 读 experiment.result（observe vs review）。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.ohre import Experiment, Recommendation
from app.services.agent_narrator import narrate_diagnosis, narrate_review
from app.services.agents import build_single_agent, build_store_agents
from app.services.matrix_agents.thresholds import DEFAULT_THRESHOLDS, get_thresholds


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


# ---------------------------------------------------------------------------
# P0-2: agent_narrator
# ---------------------------------------------------------------------------


def test_narrator_returns_none_when_llm_disabled(monkeypatch) -> None:
    # MEALKY_AGENT_LLM 默认未设置 → 视为关闭
    monkeypatch.delenv("MEALKY_AGENT_LLM", raising=False)
    result = narrate_diagnosis(
        store_name="测试店",
        diagnosis_score=60,
        primary_problem="store_ctr_down",
        daily_summary="CTR 下降",
        root_causes=[{"title": "主图弱", "explanation": "...", "confidence": 0.8}],
        metric_signals=[{"metric": "ctr", "delta_pct": -8.0, "label": "点击率"}],
        next_actions=["换主图"],
        fallback_summary="规则引擎总结",
    )
    assert result is None


def test_narrator_returns_text_when_llm_enabled(monkeypatch) -> None:
    monkeypatch.setenv("MEALKY_AGENT_LLM", "1")

    # mock LLM 调用，避免真实网络
    from app.services import agent_narrator

    def fake_call(*, system, context, purpose="general.consulting", temperature=0.5):
        return "LLM 生成的自然语言总结"

    monkeypatch.setattr(agent_narrator, "_call_for_narrative", fake_call)

    result = narrate_review(
        store_name="测试店",
        avg_rating=4.2,
        top_themes=[{"label": "份量", "share_pct": 45.0, "sample": "份量少"}],
        pending_replies=3,
        fallback_conclusion="规则引擎总结",
    )
    assert result == "LLM 生成的自然语言总结"


def test_meta_ai_narrative_none_when_llm_disabled() -> None:
    """LLM 关闭时，agent meta 的 ai_narrative 应为 None（回退到 conclusion）。"""
    db = _session()
    seeded = seed_demo(db)
    result = build_single_agent(db, seeded["store_id"], "diagnosis")
    assert result is not None
    assert result["meta"]["ai_narrative"] is None
    assert result["meta"]["ai_mode"] is None


def test_narrator_returns_none_on_llm_failure(monkeypatch) -> None:
    """LLM 启用但调用失败时，narrator 返回 None（回退到规则引擎结论）。"""
    monkeypatch.setenv("MEALKY_AGENT_LLM", "1")
    from app.services import agent_narrator
    from app.services.llm_engine.gateway import LlmResult

    # 模拟 LLM 调用返回失败
    def fake_call_llm(**kwargs):
        return LlmResult(ok=False, reason="connection_timeout", fallback_to_heuristic=True)

    monkeypatch.setattr(agent_narrator, "call_llm", fake_call_llm)

    result = narrate_diagnosis(
        store_name="测试店",
        diagnosis_score=55,
        primary_problem="store_cvr_down",
        daily_summary="CVR 下降",
        root_causes=[{"title": "套餐不足", "explanation": "...", "confidence": 0.7}],
        metric_signals=[],
        next_actions=["补套餐"],
        fallback_summary="规则引擎总结",
    )
    assert result is None  # 失败时回退，不返回错误内容


def test_narrator_returns_none_on_exception(monkeypatch) -> None:
    """LLM 调用抛异常时，narrator 捕获并返回 None（不影响主流程）。"""
    monkeypatch.setenv("MEALKY_AGENT_LLM", "1")
    from app.services import agent_narrator

    def fake_call_llm(**kwargs):
        raise RuntimeError("network error")

    monkeypatch.setattr(agent_narrator, "call_llm", fake_call_llm)

    result = narrate_review(
        store_name="测试店",
        avg_rating=4.0,
        top_themes=[{"label": "份量", "share_pct": 50.0}],
        pending_replies=2,
        fallback_conclusion="规则结论",
    )
    assert result is None


# ---------------------------------------------------------------------------
# P1-1: thresholds
# ---------------------------------------------------------------------------


def test_thresholds_module_loads_defaults() -> None:
    t = get_thresholds()
    assert t is DEFAULT_THRESHOLDS
    # 关键阈值可读
    assert t.crm.low_repurchase_base == 0.22
    assert t.review.theme_dominant_share_pct == 30.0
    assert t.service.pending_signal_threshold == 3
    assert t.clamp.low == 20
    assert t.clamp.high == 98


def test_thresholds_category_override_returns_default_when_not_configured() -> None:
    t = get_thresholds(category="快餐")
    # 当前没有配置品类覆盖，返回默认实例
    assert t is DEFAULT_THRESHOLDS


# ---------------------------------------------------------------------------
# P1-2: CRM 降级
# ---------------------------------------------------------------------------


def test_crm_agent_degrades_without_real_data() -> None:
    """无真实 CRM 数据时，segment 的 estimated_count 应为 0，且 blocker 提示代理。"""
    db = _session()
    seeded = seed_demo(db)
    result = build_single_agent(db, seeded["store_id"], "crm")
    assert result is not None

    # 所有 segment 的 estimated_count 都是 0（不再伪造精确数字）
    for segment in result["segments"]:
        assert segment["estimated_count"] == 0
        assert "代理" in segment["note"]

    # 至少一个 blocker 说明数据来源
    assert any("代理" in b or "置信度" in b for b in result["blockers"])


def test_crm_agent_outputs_real_counts_when_flagged() -> None:
    """has_real_crm_data=True 时输出真实估算数字。"""
    from app.services.matrix_agents.builders import build_crm_agent
    from app.services.matrix_agents.common import MatrixAgentInput
    from app.models.entities import Store
    from app.services.store_state import build_store_state

    db = _session()
    seeded = seed_demo(db)
    store = db.get(Store, seeded["store_id"])
    state = build_store_state(db=db, store_id=seeded["store_id"], days=7)

    data = MatrixAgentInput(
        store=store,
        menu_items=[],
        item_snapshots=[],
        competition_changes=[],
        kpis=state.kpis,
        document_alignment={},
        primary_problem_type=None,
        hypothesis_id=None,
        generated_at=datetime.now(timezone.utc),
        has_real_crm_data=True,
    )
    result = build_crm_agent(db, data, [])
    # 至少一个 segment 有非零 count
    assert any(s.estimated_count > 0 for s in result.segments)


# ---------------------------------------------------------------------------
# P1-3: execution_phase 对齐 growth 状态机
# ---------------------------------------------------------------------------


def _seed_executed_recommendation_with_result(
    db: Session, store_id: str, action_type: str, result: str
) -> str:
    rec = Recommendation(
        store_id=store_id,
        scope="store",
        object_ref=f"store:{store_id}",
        action_type=action_type,
        expected_metric="orders",
        window_hours=24,
        confidence=0.7,
        status="executed",
        content_json=f'{{"source": "service_agent", "title": "测试动作"}}',
        executed_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    db.add(rec)
    db.flush()
    db.add(Experiment(
        recommendation_id=rec.id,
        store_id=store_id,
        result=result,
        lift_pct=5.0 if result == "positive" else -3.0,
    ))
    db.commit()
    return rec.id


def test_matrix_execution_phase_reflects_experiment_result() -> None:
    """executed + experiment.result=positive → review（不是 observe）。"""
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    rec_id = _seed_executed_recommendation_with_result(
        db, store_id, "batch_reply_negative_reviews", "positive"
    )

    result = build_single_agent(db, store_id, "service")
    assert result is not None
    queue = result["action_queue"]
    matched = next((item for item in queue if item["recommendation_id"] == rec_id), None)
    assert matched is not None
    assert matched["execution_phase"] == "review"
    assert matched["experiment_result"] == "positive"


def test_matrix_execution_phase_observe_when_pending() -> None:
    """executed + experiment.result=pending → observe。"""
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    rec_id = _seed_executed_recommendation_with_result(
        db, store_id, "publish_service_reply_scripts", "pending"
    )

    result = build_single_agent(db, store_id, "service")
    assert result is not None
    queue = result["action_queue"]
    matched = next((item for item in queue if item["recommendation_id"] == rec_id), None)
    assert matched is not None
    assert matched["execution_phase"] == "observe"


def test_matrix_execution_phase_execute_now_for_proposed() -> None:
    """proposed → execute_now。"""
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    db.add(Recommendation(
        store_id=store_id,
        scope="store",
        object_ref=f"store:{store_id}",
        action_type="batch_reply_negative_reviews",
        expected_metric="rating",
        window_hours=24,
        confidence=0.7,
        status="proposed",
        content_json='{"source": "service_agent", "title": "测试"}',
    ))
    db.commit()

    result = build_single_agent(db, store_id, "service")
    assert result is not None
    proposed_items = [
        item for item in result["action_queue"] if item["execution_phase"] == "execute_now"
    ]
    assert proposed_items  # 至少有一个 execute_now


# ---------------------------------------------------------------------------
# 整体冒烟：build_store_agents 全链路不报错
# ---------------------------------------------------------------------------


def test_build_store_agents_smoke_after_enhancements() -> None:
    db = _session()
    seeded = seed_demo(db)
    payload = build_store_agents(db, seeded["store_id"])
    assert payload is not None
    # 所有 12 个 agent 都有 meta
    for key in (
        "competition", "menu", "product", "storefront", "diagnosis", "growth",
        "promo", "ads", "crm", "service", "review", "store_matrix",
    ):
        agent = getattr(payload, key)
        assert agent.meta.key == key
        assert agent.meta.label
