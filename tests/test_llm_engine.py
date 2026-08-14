from app.services.llm_engine.bindings import is_purpose_chain_configured, resolve_purpose_model_chain
from app.services.llm_engine.client import ChatResult
from app.services.llm_engine.gateway import call_llm


def test_purpose_chain_uses_env_keys(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    monkeypatch.setenv("DEEPSEEK_FLAGSHIP_MODEL", "deepseek-v4-pro")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    assert is_purpose_chain_configured("general.consulting")
    chain = resolve_purpose_model_chain("general.consulting")
    assert chain[0].provider == "deepseek"


def test_call_llm_failover(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-bad")
    monkeypatch.setenv("QWEN_API_KEY", "sk-good")
    monkeypatch.setenv("QWEN_UTILITY_MODEL", "qwen3.6-flash")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    calls: list[str] = []

    def fake_chat_completion(**kwargs):
        calls.append(kwargs["model"])
        if "deepseek" in kwargs["base_url"]:
            raise RuntimeError("llm_http_503: unavailable")
        return ChatResult(content="先稳住转化，再谈扩曝光。", prompt_tokens=10, completion_tokens=8, total_tokens=18)

    monkeypatch.setattr("app.services.llm_engine.gateway.chat_completion", fake_chat_completion)
    result = call_llm(
        purpose="general.consulting",
        messages=[{"role": "user", "content": "订单下降怎么办"}],
    )
    assert result.ok is True
    assert result.failover_used is True
    assert result.provider == "qianwen"
    assert len(calls) == 2


def test_call_llm_supports_function_calling(monkeypatch) -> None:
    """call_llm 传入 tools 后，应透传给 chat_completion 并返回 tool_calls。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_FLAGSHIP_MODEL", "deepseek-v4-pro")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)

    captured: dict = {}

    def fake_chat_completion(**kwargs):
        captured["tools"] = kwargs.get("tools")
        captured["tool_choice"] = kwargs.get("tool_choice")
        captured["messages"] = kwargs.get("messages")
        # 模拟 provider 返回 tool_calls（店长要调用 diagnosis 工具）
        return ChatResult(
            content="",
            prompt_tokens=50,
            completion_tokens=20,
            total_tokens=70,
            tool_calls=[
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": "query_diagnosis", "arguments": "{}"},
                }
            ],
            finish_reason="tool_calls",
        )

    monkeypatch.setattr("app.services.llm_engine.gateway.chat_completion", fake_chat_completion)

    tools_schema = [
        {
            "type": "function",
            "function": {
                "name": "query_diagnosis",
                "description": "查询经营诊断",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    result = call_llm(
        purpose="general.consulting",
        messages=[{"role": "user", "content": "最近订单为什么下降？"}],
        tools=tools_schema,
        tool_choice="auto",
    )

    # 验证 tools 被透传
    assert captured["tools"] == tools_schema
    assert captured["tool_choice"] == "auto"
    # 验证 tool_calls 被解析出来
    assert result.ok is True
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["function"]["name"] == "query_diagnosis"
    assert result.finish_reason == "tool_calls"


def test_call_llm_without_tools_unchanged(monkeypatch) -> None:
    """不传 tools 时行为完全不变（纯文本对话，tool_calls=None）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)

    captured: dict = {}

    def fake_chat_completion(**kwargs):
        captured["tools"] = kwargs.get("tools")
        return ChatResult(content="先优化主图", prompt_tokens=10, completion_tokens=8, total_tokens=18)

    monkeypatch.setattr("app.services.llm_engine.gateway.chat_completion", fake_chat_completion)
    result = call_llm(
        purpose="general.consulting",
        messages=[{"role": "user", "content": "怎么做"}],
    )
    assert captured["tools"] is None  # 没透传 tools
    assert result.ok is True
    assert result.tool_calls is None  # 纯文本模式
    assert result.content == "先优化主图"


def test_homepage_read_skips_llm(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    called = {"n": 0}

    def fake_chat_completion(**kwargs):
        called["n"] += 1
        return ChatResult(content="should not run", prompt_tokens=1, completion_tokens=1, total_tokens=2)

    monkeypatch.setattr("app.services.llm_engine.gateway.chat_completion", fake_chat_completion)
    from app.services.llm_engine.request_budget import homepage_read_scope

    with homepage_read_scope():
        result = call_llm(
            purpose="general.consulting",
            messages=[{"role": "user", "content": "订单下降怎么办"}],
        )
    assert result.ok is False
    assert result.fallback_to_heuristic is True
    assert result.reason == "homepage_read_skip_llm"
    assert called["n"] == 0


def test_homepage_read_diagnosis_uses_rules(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    monkeypatch.setenv("MEALKY_DIAGNOSIS_LLM", "1")
    from app.services.diagnosis_reasoner import llm_diagnose_root_cause
    from app.services.llm_engine.request_budget import homepage_read_scope

    with homepage_read_scope():
        result = llm_diagnose_root_cause(metric="ctr", delta_pct=-12.0)
    assert result["source"] == "rule_fallback"
