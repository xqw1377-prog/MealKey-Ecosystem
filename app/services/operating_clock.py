"""Operating Clock — 无 Celery 也能在对的时间做事。

两层：
- light tick：首页 / workspace 加载时执行（自动落地低风险动作、钉住今日 NBA、该叫老板才通知）
- heavy tick：每相位每天一次完整分析（Celery beat 或进程内后台线程）

两者共用同一套相位与幂等标记，互不打架。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.entities import Store
from app.models.settings import AppSetting
from app.schemas.arbiter import OpsQueueBrief
from app.services.operating_rhythm import is_in_quiet_hours, local_now, resolve_store_rhythm

logger = logging.getLogger(__name__)

AI_ONLY_PHASES = {"night_learn", "deep_review", "quiet"}
NO_AUTO_EXECUTE_PHASES = {"lunch_protect", "quiet", "night_learn"}


def _today() -> str:
    return local_now().strftime("%Y-%m-%d")


def _hour() -> int:
    return local_now().hour


def clock_marker_key(store_id: str, phase: str, day: str | None = None) -> str:
    return f"clock_run:{store_id}:{day or _today()}:{phase}"


def nba_pin_key(store_id: str, phase: str, day: str | None = None) -> str:
    return f"nba:{store_id}:{day or _today()}:{phase}"


def clock_already_ran(db: Session, store_id: str, phase: str, day: str | None = None) -> bool:
    return (
        db.execute(
            select(AppSetting.id).where(AppSetting.key == clock_marker_key(store_id, phase, day)).limit(1)
        ).scalar_one_or_none()
        is not None
    )


def mark_clock_ran(db: Session, store_id: str, phase: str, day: str | None = None) -> None:
    from app.services.settings_store import upsert_setting

    upsert_setting(
        db,
        clock_marker_key(store_id, phase, day),
        datetime.now(timezone.utc).isoformat(),
        description="operating clock heavy tick marker",
    )
    db.commit()


def load_nba_pin(db: Session, store_id: str, phase: str, day: str | None = None) -> str | None:
    row = db.execute(
        select(AppSetting).where(AppSetting.key == nba_pin_key(store_id, phase, day)).limit(1)
    ).scalar_one_or_none()
    if row and row.value:
        return str(row.value).strip() or None
    return None


def save_nba_pin(db: Session, store_id: str, phase: str, now_id: str, day: str | None = None) -> None:
    from app.services.settings_store import upsert_setting

    upsert_setting(
        db,
        nba_pin_key(store_id, phase, day),
        now_id[:120],
        description="today NBA pin",
    )


def apply_nba_pin(queue: OpsQueueBrief, pin_id: str | None):
    """若今日钉住的卡还在队列里，把它提成 now 候选。"""
    if not pin_id:
        return None
    for bucket in (queue.need_you, queue.working):
        for card in bucket or []:
            if card.id == pin_id:
                return card
    return None


def apply_light_tick(
    db: Session,
    store_id: str,
    *,
    flow: dict[str, Any],
    queue: OpsQueueBrief | None = None,
) -> dict[str, Any]:
    """首页加载即可推进自动经营：执行、通知、钉住 NBA。幂等。"""
    phase = str(flow.get("phase") or "")
    result: dict[str, Any] = {
        "phase": phase,
        "auto_executed": [],
        "notified": False,
        "pinned": None,
    }
    if not phase or phase == "quiet":
        return result

    if phase not in NO_AUTO_EXECUTE_PHASES and not flow.get("protect_mode"):
        try:
            from app.services.execution_policy import auto_execute_recommendations

            executed = auto_execute_recommendations(db, store_id, max_actions=1)
            result["auto_executed"] = [row for row in executed if row.get("applied")]
        except Exception as exc:  # noqa: BLE001
            logger.warning("light tick auto_execute failed: %s", exc)
            result["auto_execute_error"] = str(exc)[:80]

    now = flow.get("now") or {}
    now_id = str(now.get("source_card_id") or "")
    if flow.get("interrupt_ok") and now.get("owner") == "boss" and now_id:
        try:
            from app.services.notification_service import notify_store_owner

            nid = notify_store_owner(
                db,
                store_id=store_id,
                notification_type="need_you",
                title=str(now.get("title") or "现在有一件事需要你")[:60],
                body=str(now.get("why_now") or flow.get("clock_why") or "")[:200],
                priority="high" if now.get("execution") == "ASK_INFORMATION" else "normal",
                clock_phase=phase,
                related_decision_id=now_id[:64],
            )
            result["notified"] = bool(nid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("light tick notify failed: %s", exc)

    if now_id and now.get("owner") == "boss":
        try:
            save_nba_pin(db, store_id, phase, now_id)
            db.commit()
            result["pinned"] = now_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("light tick pin failed: %s", exc)

    return result


def tick_one_store(
    db: Session,
    store_id: str,
    *,
    heavy: bool = True,
    hour: int | None = None,
) -> dict[str, Any]:
    """对单店做一次节律心跳。heavy=True 时跑完整相位分析（每天每相位一次）。"""
    from app.services.decision_flow import resolve_operating_phase

    h = hour if hour is not None else _hour()
    rhythm = resolve_store_rhythm(db, store_id)
    phase = resolve_operating_phase(rhythm, hour=h)
    quiet = is_in_quiet_hours(rhythm, h)
    day = _today()

    if phase == "quiet" or (quiet and phase not in {"night_learn", "deep_review"}):
        return {"store_id": store_id, "phase": phase, "status": "quiet_hours"}

    try:
        from app.services.notification_service import flush_queued_notifications

        flushed = flush_queued_notifications(db, store_id)
    except Exception:  # noqa: BLE001
        flushed = 0

    if not heavy:
        return {"store_id": store_id, "phase": phase, "status": "light_only", "notifications_flushed": flushed}

    if clock_already_ran(db, store_id, phase, day):
        return {"store_id": store_id, "phase": phase, "status": "already_ran", "notifications_flushed": flushed}

    from app.jobs.tasks import _run_clock_phase

    phase_result = _run_clock_phase(db, store_id, phase)
    if phase_result.get("status") in {"skipped", "error"}:
        return {
            "store_id": store_id,
            "phase": phase,
            "status": phase_result.get("status") or "skipped",
            "reason": phase_result.get("reason") or "",
            "notifications_flushed": flushed,
        }
    mark_clock_ran(db, store_id, phase, day)
    return {
        "store_id": store_id,
        "phase": phase,
        "status": phase_result.get("status") or "completed",
        "rhythm_source": rhythm.source,
        "notifications_flushed": flushed,
        **{k: v for k, v in phase_result.items() if k != "status"},
    }


def tick_all_stores(*, heavy: bool = True, hour: int | None = None) -> dict[str, Any]:
    """Celery 与进程内调度共用入口。"""
    now_local = local_now()

    db = SessionLocal()
    try:
        store_ids = list(db.execute(select(Store.id).where(Store.status == "active")).scalars())
        results = []
        for store_id in store_ids:
            try:
                results.append(tick_one_store(db, store_id, heavy=heavy, hour=hour))
            except Exception as exc:  # noqa: BLE001
                logger.warning("clock tick failed for %s: %s", store_id, exc)
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                results.append({"store_id": store_id, "error": str(exc)[:100]})
        return {
            "tick_at": now_local.isoformat(),
            "store_count": len(store_ids),
            "results": results,
        }
    finally:
        db.close()


def should_run_inprocess_clock(env: Mapping[str, str] | None = None, *, is_dev: bool | None = None) -> bool:
    """进程内时钟只给本地无 Celery 的开发用。生产交给 beat。"""
    environ = env if env is not None else os.environ
    if str(environ.get("MEALKEY_DISABLE_CLOCK") or "") == "1":
        return False
    if str(environ.get("MEALKEY_ENABLE_INPROCESS_CLOCK") or "") == "1":
        return True
    # Vercel 函数不能挂后台线程；节律只能另走 beat / 手动触发
    if str(environ.get("VERCEL") or "") == "1":
        return False
    if is_dev is None:
        from app.core.config import settings as _settings

        is_dev = _settings.is_dev
    return bool(is_dev)


def clock_disabled() -> bool:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return True
    return not should_run_inprocess_clock()


def start_inprocess_clock(interval_seconds: int = 900) -> Optional[object]:
    """uvicorn 进程内节律心跳。无 Redis/Celery 时自动经营仍会跑。"""
    if clock_disabled():
        return None
    import threading

    stop = threading.Event()

    def _loop() -> None:
        # 启动后稍等，避免和 lifespan backfill 抢连接
        if stop.wait(20):
            return
        while True:
            try:
                tick_all_stores(heavy=True)
                try:
                    from app.jobs.tasks import follow_up_decisions

                    follow_up_decisions()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("in-process follow-up failed: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("in-process rhythm tick failed: %s", exc)
            if stop.wait(interval_seconds):
                return

    thread = threading.Thread(target=_loop, name="mealkey-rhythm", daemon=True)
    thread.start()
    logger.info("in-process operating clock started (every %ss)", interval_seconds)
    return stop
