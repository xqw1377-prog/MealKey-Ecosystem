"""Agent Infrastructure 测试 — Event Log / Action Pipeline / Continuation / External Runtime。"""
from datetime import date, timedelta

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
    s = Store(merchant_id=m.id, name="测试店"); db.add(s); db.flush()
    return s.id


# ═══════════════════════════════════════════════════════════
# Agent Event Log
# ═══════════════════════════════════════════════════════════


def test_event_log_basic() -> None:
    from app.services.agent_event_log import AgentEventLog
    db = _session(); sid = _seed(db)
    log = AgentEventLog(db, store_id=sid, runtime="local")
    log.turn_start(question="为什么订单掉了")
    log.llm_call(model="deepseek-chat", messages=[{"role": "user"}], token_input=500)
    log.tool_call(tool_name="query_product", arguments={"item_id": "xxx"})
    log.tool_result(tool_name="query_product", result={"ctr": 0.035}, duration_ms=120)
    log.llm_response(content="CTR下降了", token_output=300, cost_cny=0.01)
    log.turn_end(conclusion="建议换主图", actions=["change_main_image"])
    db.commit()

    events = log.replay()
    assert len(events) == 6
    assert events[0]["type"] == "turn_start"
    assert events[-1]["type"] == "turn_end"

    summary = log.cost_summary()
    assert summary["total_events"] == 6
    assert summary["tool_calls"] == 1
    assert summary["tokens_in"] == 500
    assert summary["tokens_out"] == 300
    assert summary["cost_cny"] == 0.01
    db.close()


def test_event_log_error() -> None:
    from app.services.agent_event_log import AgentEventLog
    db = _session(); sid = _seed(db)
    log = AgentEventLog(db, store_id=sid)
    log.error(message="LLM timeout")
    db.commit()
    summary = log.cost_summary()
    assert summary["errors"] == 1
    db.close()


# ═══════════════════════════════════════════════════════════
# Action Pipeline
# ═══════════════════════════════════════════════════════════


def test_action_pipeline_stages() -> None:
    from app.services.action_pipeline import ActionPipeline, PipelineStage, PipelineStatus
    db = _session(); sid = _seed(db)
    pipeline = ActionPipeline(db, sid)
    result = pipeline.execute(
        action_type="change_title",
        expected_metric="ctr",
        expected_lift_pct=5,
    )
    assert result.status in (PipelineStatus.OBSERVING, PipelineStatus.FAILED)
    assert len(result.stages_log) >= 6  # 至少6个阶段记录了
    stage_names = [s["stage"] for s in result.stages_log]
    assert "PREPARE" in stage_names
    assert "AUTHORIZE" in stage_names
    db.close()


# ═══════════════════════════════════════════════════════════
# Continuation Packet
# ═══════════════════════════════════════════════════════════


def test_continuation_save_load() -> None:
    from app.services.continuation import ContinuationPacket, resume_from
    db = _session(); sid = _seed(db)

    # 保存
    packet = ContinuationPacket.save(
        db,
        work_thread_id="wt_001",
        session_id="sess_001",
        store_id=sid,
        objective="诊断CTR下降",
        context_summary="曝光稳定CTR跌18%",
        last_conclusion="可能是主图竞争力问题",
        pending_tools=["query_competition"],
    )

    # 加载
    loaded = ContinuationPacket.load(db, "wt_001")
    assert loaded is not None
    assert loaded.objective == "诊断CTR下降"
    assert loaded.can_resume is True

    # 续传指令
    resume = resume_from(loaded)
    assert resume["action"] == "resume"
    assert "诊断CTR下降" in resume["instruction"]
    db.close()


def test_continuation_not_found() -> None:
    from app.services.continuation import ContinuationPacket
    db = _session()
    assert ContinuationPacket.load(db, "nonexistent") is None
    db.close()


# ═══════════════════════════════════════════════════════════
# External Runtime
# ═══════════════════════════════════════════════════════════


def test_local_runtime() -> None:
    from app.services.external_runtime import LocalRuntime, RuntimeRequest
    db = _session(); sid = _seed(db)
    rt = LocalRuntime()
    req = RuntimeRequest(store_id=sid, question="为什么订单掉了", objective="诊断订单")
    result = rt.execute_candidate(db, req)
    assert result.runtime == "local"
    assert result.status in ("completed", "failed")
    assert result.trace_ref  # 有 session_id
    db.close()


def test_dsh_runtime_not_implemented() -> None:
    from app.services.external_runtime import DeepSeekHarnessRuntime, RuntimeRequest
    db = _session(); sid = _seed(db)
    rt = DeepSeekHarnessRuntime()
    req = RuntimeRequest(store_id=sid, question="test")
    result = rt.execute_candidate(db, req)
    # SDK 未安装 → not_implemented
    assert result.status in ("not_implemented", "pending_integration")
    assert result.runtime == "dsh"
    db.close()


def test_shadow_comparison() -> None:
    from app.services.external_runtime import execute_shadow_comparison, RuntimeRequest
    db = _session(); sid = _seed(db)
    req = RuntimeRequest(store_id=sid, question="为什么订单掉了")
    results = execute_shadow_comparison(db, req, runtimes=["local", "dsh"])
    assert "local" in results
    assert "dsh" in results
    assert results["local"].status in ("completed", "failed")
    db.close()
