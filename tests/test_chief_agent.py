"""Chief Agent (AI 店长) ReAct 调度器测试（步骤 3）。

覆盖：
- ReAct 多轮调度（mock LLM 返回 tool_calls → 调 agent → 收尾）；
- 规则降级（LLM 未配置时走意图分类 + agent 调用）；
- 意图分类正确性；
- 兜底链。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.services import agent_context_cache
from app.services.chief_agent import (
    AGENT_TOOLS,
    _build_tools_schema,
    _classify_intent,
    _compact_agent_result,
    _parse_final_answer,
    answer_as_chief,
)
from app.services.llm_engine.gateway import LlmResult


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


# ---------------------------------------------------------------------------
# 工具 schema 构建
# ---------------------------------------------------------------------------


def test_tools_schema_has_all_agents_plus_write_tools() -> None:
    """tools schema 应包含全部 query 工具 + 3 个写入工具。"""
    from app.services.chief_agent import AGENT_TOOLS, WRITE_TOOLS, _build_tools_schema

    tools = _build_tools_schema()
    names = {t["function"]["name"] for t in tools}
    # query 工具
    assert "query_diagnosis" in names
    assert "query_growth" in names
    assert "query_review" in names
    # 写入工具
    assert "create_goal" in names
    assert "prepare_action" in names
    assert "start_thread" in names
    assert len(tools) == len(AGENT_TOOLS) + len(WRITE_TOOLS)
    # 每个 tool 都有 description
    for tool in tools:
        assert tool["function"]["description"]
        assert tool["type"] == "function"


# ---------------------------------------------------------------------------
# 意图分类（降级路径用）
# ---------------------------------------------------------------------------


def test_classify_intent_routes_correctly() -> None:
    assert _classify_intent("最近订单下降怎么办") == "diagnosis"
    assert _classify_intent("附近谁在抢我的生意") == "competition"
    assert _classify_intent("菜单要不要加什么菜") == "menu"
    assert _classify_intent("主图要不要换") == "product"
    assert _classify_intent("评分为什么下降") == "review"
    assert _classify_intent("怎么提升销量") == "growth"
    assert _classify_intent("要不要投广告") == "ads"
    assert _classify_intent("怎么提高复购") == "crm"
    assert _classify_intent("差评怎么回复") == "service"
    assert _classify_intent("随便看看") == "growth"  # 默认


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def test_parse_final_answer_from_json() -> None:
    content = '{"conclusion":"先换主图","reasons":["CTR下降","主图旧"],"actions":["今天换主图"],"expected":"CTR +8%"}'
    parsed = _parse_final_answer(content)
    assert parsed["conclusion"] == "先换主图"
    assert len(parsed["reasons"]) == 2
    assert parsed["actions"] == ["今天换主图"]


def test_parse_final_answer_from_plain_text() -> None:
    content = "你的问题是主图弱。\n建议先换主图\n再看 CTR"
    parsed = _parse_final_answer(content)
    assert "主图" in parsed["conclusion"]
    assert parsed["actions"]  # 提取到了动作


def test_compact_agent_result_keeps_key_fields() -> None:
    result = {
        "meta": {"key": "diagnosis", "ai_narrative": "LLM总结"},
        "diagnosis_score": 65,
        "conclusion": "CTR下降",
        "reasons": ["主图弱", "标题旧"],
        "root_causes": [{"title": "第一眼弱", "explanation": "主图竞争力不足"}],
    }
    compact = _compact_agent_result(result)
    assert "diagnosis" in compact
    assert "LLM总结" in compact or "CTR下降" in compact


# ---------------------------------------------------------------------------
# 规则降级（LLM 未配置）
# ---------------------------------------------------------------------------


def test_chief_agent_rule_fallback_when_llm_disabled(monkeypatch) -> None:
    """LLM 未配置时，走规则降级：意图分类 + 调对应 agent + 模板。"""
    agent_context_cache.clear_all()
    monkeypatch.setattr("app.services.chief_agent.is_llm_configured", lambda purpose="general.consulting": False)

    db = _session()
    seeded = seed_demo(db)

    response = answer_as_chief(db, seeded["store_id"], "最近订单下降怎么办", days=7)
    assert response.mode == "rule_fallback"
    assert response.question_type == "diagnosis"
    assert "diagnosis" in response.agents_called
    assert response.conclusion  # 有结论
    assert response.answer  # 有完整回答
    assert response.llm is None  # 规则模式无 LLM


def test_chief_agent_rule_fallback_unknown_question() -> None:
    """未知意图默认走 growth。"""
    agent_context_cache.clear_all()
    db = _session()
    seeded = seed_demo(db)

    # 不配置 LLM
    import app.services.chief_agent as chief

    original = chief.is_llm_configured
    chief.is_llm_configured = lambda purpose="general.consulting": False
    try:
        response = answer_as_chief(db, seeded["store_id"], "随便问问", days=7)
        assert response.mode == "rule_fallback"
        assert response.question_type == "growth"
    finally:
        chief.is_llm_configured = original


# ---------------------------------------------------------------------------
# ReAct 多轮调度（mock LLM）
# ---------------------------------------------------------------------------


def test_chief_agent_react_calls_tools_then_answers(monkeypatch) -> None:
    """LLM 第一轮返回 tool_calls → 调 agent → 第二轮返回最终回答。"""
    agent_context_cache.clear_all()
    monkeypatch.setattr("app.services.chief_agent.is_llm_configured", lambda purpose="general.consulting": True)

    call_count = {"n": 0}

    def fake_call_llm(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 第一轮：要求调 diagnosis 工具
            return LlmResult(
                ok=True,
                content="",
                provider="deepseek",
                model="deepseek-v4-pro",
                model_slug="deepseek:flagship",
                latency_ms=500,
                total_tokens=100,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "query_diagnosis", "arguments": "{}"},
                    }
                ],
                finish_reason="tool_calls",
            )
        # 第二轮：最终 JSON 回答
        return LlmResult(
            ok=True,
            content='{"conclusion":"你的问题是CTR下降","reasons":["主图竞争力不足"],"actions":["今天先换主图"],"expected":"CTR +8%~12%"}',
            provider="deepseek",
            model="deepseek-v4-pro",
            model_slug="deepseek:flagship",
            latency_ms=400,
            total_tokens=200,
            tool_calls=None,
            finish_reason="stop",
        )

    monkeypatch.setattr("app.services.chief_agent.call_llm", fake_call_llm)

    db = _session()
    seeded = seed_demo(db)
    response = answer_as_chief(db, seeded["store_id"], "订单下降怎么办", days=7)

    assert response.mode == "react"
    assert "diagnosis" in response.agents_called
    assert "CTR下降" in response.conclusion or "CTR" in response.answer
    assert response.llm is not None
    assert response.llm["rounds"] == 2
    assert call_count["n"] == 2  # 确实调了 2 轮


def test_chief_agent_react_llm_failure_falls_back_to_rule(monkeypatch) -> None:
    """LLM ReAct 失败时，降级到规则路径。"""
    agent_context_cache.clear_all()
    monkeypatch.setattr("app.services.chief_agent.is_llm_configured", lambda purpose="general.consulting": True)

    def fake_call_llm(**kwargs):
        return LlmResult(ok=False, reason="timeout", fallback_to_heuristic=True)

    monkeypatch.setattr("app.services.chief_agent.call_llm", fake_call_llm)

    db = _session()
    seeded = seed_demo(db)
    response = answer_as_chief(db, seeded["store_id"], "订单下降", days=7)

    assert response.mode == "rule_fallback"
    assert response.error is not None
    assert "timeout" in response.error or "failed" in response.error


def test_chief_agent_store_not_found_returns_graceful() -> None:
    """门店不存在时返回优雅降级，不抛异常。"""
    agent_context_cache.clear_all()
    db = _session()
    response = answer_as_chief(db, "nonexistent_store", "怎么提升销量", days=7)
    assert response.mode == "heuristic"
    assert response.confidence == "low"
