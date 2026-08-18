"""DATA-AS-01 Day-7 path: reconciled facts → StoreState → POIE → Candidate Action."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.services.action_registry import build_action_spec
from app.services.data_acquisition_ingest import ingest_reconciliation
from app.services.event_engine import build_operating_events
from app.services.store_state import build_store_state

DiscoveryMode = Literal["REAL", "SANDBOX", "FIXTURE"]


def declining_series(*, days: int = 14, baseline_orders: int = 40, observe_orders: int = 22) -> tuple[list[dict], list[dict]]:
    """Construct official=collector matched series: strong baseline, weak observe window.

    仅 FIXTURE / 显式测试注入使用。REAL 模式不得调用本函数补数据。
    """
    today = date.today()
    rows: list[dict[str, Any]] = []
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        in_observe = offset <= 7
        orders = observe_orders if in_observe else baseline_orders
        gmv = orders * 38.0
        rows.append({"day": day.isoformat(), "orders": orders, "gmv": gmv})
    return rows, list(rows)


def run_connected_discovery(
    db: Session,
    *,
    store_id: str,
    platform: str = "meituan",
    official_rows: list[dict[str, Any]] | None = None,
    collector_rows: list[dict[str, Any]] | None = None,
    mode: DiscoveryMode = "REAL",
) -> dict[str, Any]:
    discovery_mode = str(mode or "REAL").strip().upper()
    if discovery_mode not in {"REAL", "SANDBOX", "FIXTURE"}:
        discovery_mode = "REAL"

    has_rows = official_rows is not None and collector_rows is not None
    if discovery_mode == "REAL" and not has_rows:
        return {
            "status": "NO_SIGNAL",
            "mode": "REAL",
            "ingest": None,
            "orders_delta_pct": None,
            "events": [],
            "candidate_action": None,
            "poie_queue": None,
            "reached_candidate_action": False,
            "executed": False,
            "production_truth": False,
            "note": "REAL 模式无对账事实时不得合成下降序列。",
        }

    synthetic = discovery_mode in {"SANDBOX", "FIXTURE"}
    if not has_rows:
        official_rows, collector_rows = declining_series()

    ingest = ingest_reconciliation(
        db,
        store_id=store_id,
        platform=platform,
        official_rows=official_rows or [],
        collector_rows=collector_rows or [],
        acquisition_mode="AUTHORIZED_SESSION",
        auth_status="authorized" if discovery_mode == "REAL" else "missing",
        data_source="synthetic" if synthetic else "authorized_session",
    )
    state = build_store_state(db, store_id, days=7)
    events = build_operating_events(state) if state else None
    order_events = [e.model_dump(mode="json") for e in (events.events if events else []) if e.event_type == "ORDER_DROP"]
    candidate = None
    if order_events:
        candidate = build_action_spec(
            "change_title",
            object_name="招牌盖饭",
            reason=order_events[0]["detail"],
            pack={"current_problem": order_events[0]["estimated_impact"], "suggested_title": "招牌盖饭·午餐份"},
        )
    poie_queue = None
    try:
        from app.api.routes_store import _build_manager_brief

        brief = _build_manager_brief(store_id, days=7, db=db)
        poie_queue = brief.ops_queue.model_dump(mode="json") if brief.ops_queue else None
        if candidate is None and brief.ops_queue and brief.ops_queue.need_you:
            top = brief.ops_queue.need_you[0]
            candidate = build_action_spec("ops_hint", title=top.title, reason=top.why_now or top.ai_judgment or "")
    except Exception:  # noqa: BLE001 — 发现链不因首页组装失败而中断
        poie_queue = None
    return {
        "status": "DISCOVERED" if candidate else "NO_SIGNAL",
        "mode": discovery_mode,
        "ingest": ingest,
        "orders_delta_pct": getattr(state.kpis.get("orders"), "delta_pct", None) if state else None,
        "events": [e.model_dump(mode="json") for e in (events.events if events else [])],
        "candidate_action": candidate,
        "poie_queue": poie_queue,
        "reached_candidate_action": candidate is not None,
        "executed": False,
        "production_truth": discovery_mode == "REAL" and not synthetic,
        "source": "synthetic" if synthetic else "authorized_session",
    }
