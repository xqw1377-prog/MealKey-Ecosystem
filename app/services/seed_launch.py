"""种子客户上线前 6 块能力：开店数据通道、人工闭环、每日 SLA、利润诚实、生产底座、手工收款。

老板只面对一个 AI 店长。这里不增加 6 个入口，只给店长/导入/闭环/账单用的事实。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.closed_loop import ClosedLoopItem
from app.models.entities import Store
from app.services.business_import import get_data_coverage

COST_READY_PCT = 50.0
COST_READY_MIN_ITEMS = 3

ONBOARD_STEPS: tuple[dict[str, Any], ...] = (
    {
        "key": "orders",
        "label": "订单明细",
        "how": "美团商家版 → 订单管理 → 导出订单 → 在店长对话点「导入经营数据」选 5",
        "endpoint": "import/orders",
        "ready_key": "order_rows",
    },
    {
        "key": "funnel",
        "label": "经营漏斗",
        "how": "美团商家版 → 数据 → 经营分析 → 导出曝光/访问/下单 → 导入选 1",
        "endpoint": "import/funnel",
        "ready_key": "funnel_days",
    },
    {
        "key": "reviews",
        "label": "评价",
        "how": "美团商家版 → 评价管理 → 导出评价 → 导入选 3",
        "endpoint": "import/reviews",
        "ready_key": "reviews",
    },
    {
        "key": "ads",
        "label": "推广花费",
        "how": "美团商家版 → 推广 → 数据报表 → 导出 → 导入选 2",
        "endpoint": "import/ads",
        "ready_key": "ads_days",
    },
    {
        "key": "cost",
        "label": "食材成本",
        "how": "Excel 三列：商品名,食材成本,包装成本。点「上传成本表」。没有这份，店长不会说今天亏多少。",
        "endpoint": "cost/import",
        "ready_key": "cost_ready",
    },
)


def profit_honesty(db: Session, store_id: str, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    cov = coverage if coverage is not None else get_data_coverage(db, store_id)
    items_with_cost = int(cov.get("items_with_cost") or 0)
    cost_coverage_pct = float(cov.get("cost_coverage_pct") or 0)
    cost_ready = items_with_cost >= COST_READY_MIN_ITEMS and cost_coverage_pct >= COST_READY_PCT
    return {
        "cost_ready": cost_ready,
        "precise_profit": cost_ready,
        "items_with_cost": items_with_cost,
        "menu_items": int(cov.get("menu_items") or 0),
        "cost_coverage_pct": cost_coverage_pct,
        "join_campaign_allowed": cost_ready,
        "budget_up_allowed": cost_ready,
        "why_not": (
            []
            if cost_ready
            else [
                "没有食材成本，不能报精确利润，也不能说今天亏多少",
                "没有成本表，不建议报名平台活动或加广告预算",
            ]
        ),
        "boss_line": (
            "成本已够，可以按真实利润判断。"
            if cost_ready
            else "还没有食材成本表。先上传成本，我才不会瞎说今天亏多少。"
        ),
    }


def onboarding_playbook(db: Session, store_id: str) -> dict[str, Any]:
    coverage = get_data_coverage(db, store_id)
    honesty = profit_honesty(db, store_id, coverage)
    steps = []
    for spec in ONBOARD_STEPS:
        if spec["key"] == "cost":
            ready = honesty["cost_ready"]
        else:
            ready = int(coverage.get(spec["ready_key"]) or 0) > 0
        steps.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "how": spec["how"],
                "endpoint": spec["endpoint"],
                "ready": ready,
            }
        )
    missing = [step for step in steps if not step["ready"]]
    next_step = missing[0] if missing else None
    return {
        "minutes": 30,
        "steps": steps,
        "ready_count": sum(1 for step in steps if step["ready"]),
        "total": len(steps),
        "complete": not missing,
        "next": next_step,
        "coach": (
            "五份数据都齐了，店长可以按这家店的账说话。"
            if not missing
            else f"开店先传这 {len(missing)} 份。下一步：{next_step['label']}。{next_step['how']}"
        ),
        "coverage": coverage,
        "profit": honesty,
    }


def live_http_writeback_enabled() -> bool:
    return bool(str(settings.platform_connector_url or "").strip())


def writeback_delivery_mode(db: Session | None = None, store_id: str | None = None) -> dict[str, Any]:
    from app.services.platform_write import resolve_connector

    if db is not None and store_id:
        mode = resolve_connector(db, store_id).mode
    elif live_http_writeback_enabled():
        mode = "http"
    else:
        mode = "mock" if settings.is_dev else "human_paste"
    human_paste = mode == "human_paste"
    return {
        "mode": mode,
        "human_paste": human_paste,
        "platform_writeable": mode == "http" or (mode == "mock" and settings.is_dev),
        "boss_line": (
            "确认后我会改到平台并读回。"
            if mode == "http"
            else "请把执行包复制到美团商家端。改完点「已修改」。没有连接器时，我不会假装已经写上平台。"
        ),
    }


def daily_sla_digest(db: Session, store_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    pending = list(
        db.execute(
            select(ClosedLoopItem)
            .where(ClosedLoopItem.store_id == store_id, ClosedLoopItem.status == "now")
            .order_by(ClosedLoopItem.created_at.desc())
        ).scalars()
    )
    observing = list(
        db.execute(
            select(ClosedLoopItem).where(
                ClosedLoopItem.store_id == store_id,
                ClosedLoopItem.status.in_(("observing", "executed")),
            )
        ).scalars()
    )
    due = []
    for item in observing:
        until = item.observe_until
        if until is None:
            continue
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until <= now:
            due.append(item)
    honesty = profit_honesty(db, store_id)
    if not honesty["precise_profit"]:
        morning = "还没有食材成本，今天不能报亏多少。先传成本表。"
    elif pending:
        morning = f"今天先拍板：{pending[0].title}"
    elif due:
        morning = f"今天该回看：{due[0].title}"
    else:
        morning = "今天没有必须你拍板的事，店长继续盯观察窗。"
    pending_rows = [{"id": item.id, "title": item.title} for item in pending[:5]]
    due_rows = [{"id": item.id, "title": item.title} for item in due[:5]]
    push_text = (
        f"今天三件事：1）{morning} "
        f"2）待你确认 {len(pending)} 件 "
        f"3）该回看 {len(due)} 件"
    )
    return {
        "morning_judgment": morning,
        "pending_confirm": pending_rows,
        "pending_count": len(pending),
        "due_observe": due_rows,
        "due_count": len(due),
        "push_text": push_text,
        "channel": "in_app",
        "wechat_configured": bool(
            getattr(settings, "wechat_app_id", None) and getattr(settings, "wechat_app_secret", None)
        ),
    }


def push_daily_sla(db: Session, store_id: str, digest: dict[str, Any] | None = None) -> str | None:
    from app.services.notification_service import notify_store_owner

    payload = digest or daily_sla_digest(db, store_id)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return notify_store_owner(
        db,
        store_id=store_id,
        notification_type="need_you",
        title="今日店长早报",
        body=str(payload.get("push_text") or ""),
        priority="normal",
        clock_phase="morning_readiness",
        related_decision_id=f"daily-sla-{store_id}-{day}",
    )


def transfer_instructions() -> dict[str, Any]:
    payee = str(getattr(settings, "seed_bank_payee", "") or "").strip()
    account = str(getattr(settings, "seed_bank_account", "") or "").strip()
    bank = str(getattr(settings, "seed_bank_name", "") or "").strip()
    if payee and account:
        where = f"{bank + ' ' if bank else ''}{payee} {account}".strip()
        text = (
            f"月费 ¥300。对公转到 {where}，备注写店名。"
            "运营核对凭证后手工开通订阅和算力钱包。种子客户不走微信自动扣费。"
        )
    else:
        where = ""
        text = "月费 ¥300。对公转账后把凭证发给运营，由运营手工开通订阅和算力钱包。种子客户不走微信自动扣费。"
    return {
        "mode": "demo_direct" if settings.is_dev else "bank_transfer",
        "amount_monthly_cny": 300,
        "payee": payee,
        "account": account,
        "bank": bank,
        "where": where,
        "note_hint": "转账备注请写店名",
        "instructions_text": text,
    }


def production_readiness() -> dict[str, Any]:
    url = str(settings.database_url or "")
    postgres = url.startswith("postgresql")
    sqlite = "sqlite" in url.lower()
    root = Path(__file__).resolve().parents[2]
    backup_sh = root / "scripts" / "backup-postgres.sh"
    backup_py = root / "scripts" / "backup_postgres.py"
    alembic_ini = root / "alembic.ini"
    migration_script = root / "scripts" / "run_migrations.py"
    gitignore = root / ".gitignore"
    env_example = root / ".env.example"
    jwt_ok = bool(str(settings.jwt_secret or "").strip()) and str(settings.jwt_secret) not in {
        "change-me",
        "secret",
        "jwt-secret",
    }
    api_ok = bool(str(settings.api_token or "").strip())
    from app.services.operating_clock import should_run_inprocess_clock

    writeback = writeback_delivery_mode()
    connector = bool(str(settings.platform_connector_url or "").strip())
    human_paste_ok = connector or writeback["mode"] == "human_paste" or (
        settings.is_dev and writeback["mode"] == "mock"
    )
    gitignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    example_text = env_example.read_text(encoding="utf-8") if env_example.exists() else ""
    secrets_ok = (
        gitignore.exists()
        and ".env" in gitignore_text
        and not bool(re.search(r"sk-[A-Za-z0-9]{20,}", example_text))
        and not _git_tracks_env(root)
    )
    cors_ok = settings.is_dev or (
        "*" not in settings.cors_origin_list and bool(settings.cors_origin_list)
    )
    clock_ok = settings.is_dev or not should_run_inprocess_clock(is_dev=False)
    schema_ok = settings.is_dev or not bool(settings.run_schema_sync_on_startup)
    checks = [
        {
            "id": "postgres",
            "ok": postgres or settings.is_dev,
            "detail": "生产用 Postgres，不要多进程共用 SQLite",
        },
        {
            "id": "not_sqlite_in_prod",
            "ok": (not sqlite) or settings.is_dev,
            "detail": "APP_ENV=production 时 DATABASE_URL 必须是 postgresql",
        },
        {
            "id": "api_token",
            "ok": api_ok or settings.is_dev,
            "detail": "生产必须配置 API_TOKEN",
        },
        {
            "id": "jwt_secret",
            "ok": jwt_ok or settings.is_dev,
            "detail": "生产必须单独配置 JWT_SECRET，不要用默认值",
        },
        {
            "id": "tenant_scope",
            "ok": bool(settings.jwt_enforce_store_scope),
            "detail": "商户隔离：JWT 不得跨店访问",
        },
        {
            "id": "backup_script",
            "ok": backup_sh.exists() or backup_py.exists(),
            "detail": "Postgres 备份脚本必须存在",
        },
        {
            "id": "migration_runner",
            "ok": alembic_ini.exists() and migration_script.exists(),
            "detail": "生产发布必须走版本化 migration，不要靠启动时自动建表",
        },
        {
            "id": "no_create_all_in_prod",
            "ok": schema_ok,
            "detail": "生产禁止 RUN_SCHEMA_SYNC_ON_STARTUP / create_all",
        },
        {
            "id": "cors_allowlist",
            "ok": cors_ok,
            "detail": "生产 CORS_ORIGINS 必须是显式域名白名单，禁止 *",
        },
        {
            "id": "inprocess_clock_off",
            "ok": clock_ok,
            "detail": "生产节律只跑 Celery beat，不在 api 进程内再跑一遍",
        },
        {
            "id": "human_paste_without_connector",
            "ok": human_paste_ok,
            "detail": "没有 PLATFORM_CONNECTOR_URL 时走复制到美团，不宣称写回成功",
        },
        {
            "id": "prod_never_mock",
            "ok": settings.is_dev or writeback["mode"] != "mock",
            "detail": "生产禁止 Mock，且绝不能 fallback 到 Mock",
        },
        {
            "id": "secrets_not_in_repo",
            "ok": secrets_ok,
            "detail": "密钥只放 .env，不入库、不进 git",
        },
    ]
    ready = all(bool(item["ok"]) for item in checks)
    return {
        "ready": ready,
        "app_env": settings.app_env,
        "database": "postgres" if postgres else ("sqlite" if sqlite else "other"),
        "https_note": "HTTPS 由前置反向代理终止，本服务只监听内网。",
        "checks": checks,
    }


def _git_tracks_env(root: Path) -> bool:
    try:
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", ".env"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return bool((result.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return False
    url = str(settings.database_url or "")
    postgres = url.startswith("postgresql")
    sqlite = "sqlite" in url.lower()
    root = Path(__file__).resolve().parents[2]
    backup_sh = root / "scripts" / "backup-postgres.sh"
    backup_py = root / "scripts" / "backup_postgres.py"
    alembic_ini = root / "alembic.ini"
    migration_script = root / "scripts" / "run_migrations.py"
    jwt_ok = bool(str(settings.jwt_secret or "").strip()) and str(settings.jwt_secret) not in {
        "change-me",
        "secret",
        "jwt-secret",
    }
    api_ok = bool(str(settings.api_token or "").strip())
    checks = [
        {
            "id": "postgres",
            "ok": postgres or settings.is_dev,
            "detail": "生产用 Postgres，不要多进程共用 SQLite",
        },
        {
            "id": "not_sqlite_in_prod",
            "ok": (not sqlite) or settings.is_dev,
            "detail": "APP_ENV=production 时 DATABASE_URL 必须是 postgresql",
        },
        {
            "id": "api_token",
            "ok": api_ok or settings.is_dev,
            "detail": "生产必须配置 API_TOKEN",
        },
        {
            "id": "jwt_secret",
            "ok": jwt_ok or settings.is_dev,
            "detail": "生产必须单独配置 JWT_SECRET，不要用默认值",
        },
        {
            "id": "tenant_scope",
            "ok": bool(settings.jwt_enforce_store_scope),
            "detail": "商户隔离：JWT 不得跨店访问",
        },
        {
            "id": "backup_script",
            "ok": backup_sh.exists() or backup_py.exists(),
            "detail": "Postgres 备份脚本必须存在",
        },
        {
            "id": "migration_runner",
            "ok": alembic_ini.exists() and migration_script.exists(),
            "detail": "生产发布必须走版本化 migration，不要靠启动时自动建表",
        },
    ]
    ready = all(bool(item["ok"]) for item in checks)
    return {
        "ready": ready,
        "app_env": settings.app_env,
        "database": "postgres" if postgres else ("sqlite" if sqlite else "other"),
        "https_note": "HTTPS 由前置反向代理终止，本服务只监听内网。",
        "checks": checks,
    }


def seed_launch_status(db: Session, store_id: str) -> dict[str, Any]:
    onboard = onboarding_playbook(db, store_id)
    return {
        "onboarding": onboard,
        "profit": onboard["profit"],
        "writeback": writeback_delivery_mode(db, store_id),
        "daily_sla": daily_sla_digest(db, store_id),
        "billing": transfer_instructions(),
        "production": production_readiness() if settings.is_dev else None,
    }


def load_store(db: Session, store_id: str) -> Store | None:
    return db.execute(select(Store).where(Store.id == store_id)).scalar_one_or_none()
