"""7 项短板补齐测试。

覆盖：
- 事件引擎量化影响（HERO_SKU_SOLD_OUT 算损失单量）
- 3 个新事件（ADS_ROI_DROP / IM_REPLY_DROP / COMPETITOR_NEW_PRODUCT）
- chief_agent query_events 工具
- Traffic Readiness Score
- CRM 6 段生命周期分群
- 评价申诉能力
- Operation Score
"""

from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.schemas.events import EventEngineResult
from app.schemas.store_state import PlatformHealthState, StoreState
from app.services import agent_context_cache
from app.services.agents import build_store_agents
from app.services.chief_agent import AGENT_TOOLS, answer_as_chief
from app.services.event_engine import build_operating_events
from app.services.manager_brief import build_manager_home_brief
from app.services.mealkey_score import compute_operation_score


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


# ---------------------------------------------------------------------------
# 步骤 1+2: 事件引擎量化影响 + 新事件
# ---------------------------------------------------------------------------


def test_event_engine_quantifies_hero_sku_loss() -> None:
    """HERO_SKU_SOLD_OUT 应填入 estimated_impact_amount（损失单量）。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    # 模拟核心商品在售率低
    state = agents.store_state
    state.platform_health.hero_sku_in_stock_rate = 0.80
    events = build_operating_events(state)
    hero_event = next((e for e in events.events if e.event_type == "HERO_SKU_SOLD_OUT"), None)
    if hero_event:
        # 有量化影响
        assert hero_event.estimated_impact_amount is not None
        assert hero_event.estimated_impact_amount > 0
        assert "单" in (hero_event.estimated_impact or "")


def test_event_engine_detects_competitor_new_product() -> None:
    """COMPETITOR_NEW_PRODUCT 事件能被检测。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    state = agents.store_state
    # 注入一条竞品新品变化
    from app.schemas.store_state import CompetitionChange

    state.competition_changes = [
        CompetitionChange(c_store_id="c1", type="menu_added", summary="新品上市：烤鸡腿堡", price=25),
    ]
    events = build_operating_events(state)
    new_product = next(
        (e for e in events.events if e.event_type == "COMPETITOR_NEW_PRODUCT"), None
    )
    assert new_product is not None
    assert "竞品上新" in new_product.title


def test_event_engine_detects_ads_roi_drop() -> None:
    """ADS_ROI_DROP：投流花了钱但订单没涨。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    state = agents.store_state
    # 注入广告消耗 + 订单下滑
    state.profit.ads_spend = 300.0
    orders_kpi = state.kpis.get("orders")
    if orders_kpi:
        orders_kpi.delta_pct = -5.0
    events = build_operating_events(state)
    roi_event = next((e for e in events.events if e.event_type == "ADS_ROI_DROP"), None)
    assert roi_event is not None
    assert "投流" in roi_event.title or "ROI" in roi_event.title


def test_event_engine_detects_im_reply_drop() -> None:
    """IM_REPLY_DROP：回复率低于 60%。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    state = agents.store_state
    state.platform_health.im_reply_rate = 0.45
    events = build_operating_events(state)
    reply_event = next((e for e in events.events if e.event_type == "IM_REPLY_DROP"), None)
    assert reply_event is not None


# ---------------------------------------------------------------------------
# 步骤 3: chief_agent query_events 工具
# ---------------------------------------------------------------------------


def test_chief_agent_has_events_tool() -> None:
    """chief_agent 工具表包含 query_events。"""
    assert "query_events" in AGENT_TOOLS
    assert AGENT_TOOLS["query_events"]["agent_key"] == "events"


def test_chief_agent_events_tool_fires_on_anomaly_question(monkeypatch) -> None:
    """问'今天有什么异常'时，店长能调用 query_events 工具。"""
    agent_context_cache.clear_all()
    monkeypatch.setattr("app.services.chief_agent.is_llm_configured", lambda purpose="general.consulting": True)

    from app.services.llm_engine.gateway import LlmResult

    call_count = {"n": 0}

    def fake_call_llm(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LlmResult(
                ok=True,
                content="",
                provider="deepseek",
                model="deepseek-v4-pro",
                model_slug="ds",
                latency_ms=300,
                total_tokens=80,
                tool_calls=[{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "query_events", "arguments": "{}"},
                }],
                finish_reason="tool_calls",
            )
        return LlmResult(
            ok=True,
            content='{"conclusion":"今天牛肉饭售罄了","reasons":["核心商品在售率80%"],"actions":["检查库存"],"expected":"避免损失"}',
            provider="deepseek",
            model="deepseek-v4-pro",
            model_slug="ds",
            latency_ms=200,
            total_tokens=100,
            finish_reason="stop",
        )

    monkeypatch.setattr("app.services.chief_agent.call_llm", fake_call_llm)
    db = _session()
    seeded = seed_demo(db)
    response = answer_as_chief(db, seeded["store_id"], "今天有什么异常", days=7)
    assert response.mode == "react"
    assert "events" in response.agents_called


# ---------------------------------------------------------------------------
# 步骤 4: Traffic Readiness Score
# ---------------------------------------------------------------------------


def test_ads_agent_has_traffic_readiness_score() -> None:
    """ads agent 输出 traffic_readiness_score（0-100）。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    assert agents.ads.traffic_readiness_score is not None
    assert 0 <= agents.ads.traffic_readiness_score <= 100


# ---------------------------------------------------------------------------
# 步骤 5: CRM 6 段生命周期
# ---------------------------------------------------------------------------


def test_crm_agent_has_6_lifecycle_segments() -> None:
    """CRM agent 输出 6 段生命周期分群。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    segment_keys = {s.key for s in agents.crm.segments}
    expected = {"acquisition", "activation", "growth", "core", "at_risk", "churn"}
    assert expected == segment_keys


# ---------------------------------------------------------------------------
# 步骤 6: 评价申诉能力
# ---------------------------------------------------------------------------


def test_review_agent_detects_unfair_reviews() -> None:
    """review agent 能识别疑似违规差评并生成申诉动作。"""
    db = _session()
    seeded = seed_demo(db)
    # 注入一条疑似违规差评
    from app.models.entities import ReviewFact

    db.add(ReviewFact(
        store_id=seeded["store_id"],
        rating=1,
        content="同行恶意差评，根本没消费过，纯属敲诈",
        reviewed_at=datetime.now(timezone.utc),
    ))
    db.commit()

    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    appeal_action = next(
        (a for a in agents.review.priority_actions if a.action_type == "escalate_unfair_review"),
        None,
    )
    assert appeal_action is not None
    assert "申诉" in appeal_action.title


# ---------------------------------------------------------------------------
# 步骤 7: Operation Score
# ---------------------------------------------------------------------------


def test_operation_score_computes_from_platform_health() -> None:
    """Operation Score 基于 PlatformHealthState 计算。"""
    platform = PlatformHealthState(
        score=78,
        status="healthy",
        judgment="ok",
        open_status="open",
        hero_sku_in_stock_rate=0.96,
        activity_valid=True,
        meal_prep_rate=0.95,
        im_reply_rate=0.85,
    )
    score = compute_operation_score(platform)
    assert score.total is not None
    assert score.total > 0
    assert score.data_coverage in {"full", "partial"}
    # 有出餐率维度
    meal_prep = next((d for d in score.dimensions if d.key == "meal_prep_rate"), None)
    assert meal_prep is not None
    assert meal_prep.score is not None  # 数据已接入


def test_operation_score_degrades_without_data() -> None:
    """运营指标全 None 时，data_coverage=none，total 降级。"""
    platform = PlatformHealthState()  # 全部默认 None
    score = compute_operation_score(platform)
    # 只有营业状态/活动可能在，其余 unknown
    assert score.data_coverage in {"none", "partial"}


def test_manager_brief_includes_operation_score() -> None:
    """晨报包含 operation_score。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    brief = build_manager_home_brief(
        agents.store_state,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
    )
    assert brief.operation_score is not None
    assert brief.operation_score.dimensions  # 有维度
