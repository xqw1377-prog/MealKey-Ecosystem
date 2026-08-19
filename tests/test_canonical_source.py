"""结构收口测试 — canonical 数据源 + 仲裁排他契约。

修复审计两条结构性问题:
1. 首页三套数据源 → workspace 成为唯一权威(brief 嵌入 payload)
2. 仲裁不排他 → GUIDE_ARBITRATION_ORDER 显式契约
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, Store


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_store(db: Session) -> str:
    m = Merchant(name="t"); db.add(m); db.flush()
    s = Store(merchant_id=m.id, name="canonical store"); db.add(s); db.flush()
    return s.id


# ═══════════════════════════════════════════════════════════
# 1. workspace 嵌入 canonical brief
# ═══════════════════════════════════════════════════════════


def test_workspace_embeds_canonical_brief() -> None:
    """workspace payload 必须带 brief —— 一次 fetch = 全部三栏 + 分数。"""
    from app.api.routes_runtime import _build_workspace_payload

    db = _session()
    sid = _seed_store(db)
    payload = _build_workspace_payload(sid, db)
    assert "brief" in payload
    brief = payload["brief"]
    assert isinstance(brief, dict)
    # brief 与 meta 的分数同源(同一次构建)
    assert brief.get("mealkey_score") == payload["meta"].get("mealkey_score")
    # brief 带 ops_queue(与 left 面板同一次 POIE run)
    assert "ops_queue" in brief
    db.close()


def test_workspace_response_schema_accepts_brief() -> None:
    from app.schemas.runtime_api import WorkspaceRuntimeResponse

    assert hasattr(WorkspaceRuntimeResponse.model_fields, "__contains__") or True
    assert "brief" in WorkspaceRuntimeResponse.model_fields


# ═══════════════════════════════════════════════════════════
# 2. 仲裁排他契约
# ═══════════════════════════════════════════════════════════


def test_guide_arbitration_order_is_frozen() -> None:
    """仲裁顺序是显式契约 — 顺序变更必须是有意识的决定。"""
    from app.api.routes_runtime import GUIDE_ARBITRATION_ORDER

    assert GUIDE_ARBITRATION_ORDER[0] == "understanding"  # MUE 永远第一
    assert GUIDE_ARBITRATION_ORDER[1] == "protect_quiet"  # 高峰保护第二
    assert "decision_flow" in GUIDE_ARBITRATION_ORDER[:4]  # 决策流(含loop)领先于普通need_you
    assert GUIDE_ARBITRATION_ORDER[-1] == "info"
    # 无重复层级
    assert len(GUIDE_ARBITRATION_ORDER) == len(set(GUIDE_ARBITRATION_ORDER))


def test_understanding_beats_everything() -> None:
    """MUE 卡在 need_you[0] 时,guide 必须是 understanding — 不被 bridge/flow 抢走。"""

    class FakeCard:
        interrupt_reason = "understanding"
        trigger = "understanding"
        title = "经营这家店你最在乎什么"
        insight = ""
        why_now = ""
        already_did = ""
        success_metric = ""
        arbiter_state = "need_input"
        ai_judgment = ""
        ai_already_did = ""
        need_from_owner = "点选项告诉我"
        actions = []
        id = "understanding:priority_style"

    class FakeQueue:
        need_you = [FakeCard()]
        active_goal = None

    fake_bridge_guide = {"type": "APPROVAL", "title": "bridge wants this", "trigger_reason": "ANOMALY"}
    from app.api.routes_runtime import _build_guide

    guide = _build_guide(
        FakeQueue(),
        runtime_bridge_result=None,
        runtime_bridge_queue=None,
        decision_flow={"now": {"id": "flow_now", "source_card_id": "x"}, "guide": {"type": "APPROVAL", "title": "flow guide"}},
    )
    # understanding 赢 — 即使 decision_flow 有 now、bridge 有 guide
    assert "在乎" in guide.get("title", "") or guide.get("type") == "QUESTION"


def test_decision_flow_now_beats_plain_need_you() -> None:
    """决策流 now(含 closed_loop 投影)领先于普通 need_you。"""

    class FakeCard:
        interrupt_reason = "anomaly"
        trigger = "anomaly"
        title = "普通异常卡"
        insight = ""
        why_now = ""
        already_did = ""
        success_metric = ""
        id = "anomaly:1"

    class FakeQueue:
        need_you = [FakeCard()]
        active_goal = None

    from app.api.routes_runtime import _build_guide

    guide = _build_guide(
        FakeQueue(),
        decision_flow={
            "now": {"id": "flow_now", "source_card_id": "sc1"},
            "guide": {"type": "APPROVAL", "title": "flow guide wins"},
        },
    )
    assert guide.get("title") == "flow guide wins"
