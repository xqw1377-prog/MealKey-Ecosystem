from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import MenuItem, Store
from app.models.settings import PlatformConnection
from app.services.platform_connectors import list_platforms
from app.services.settings_store import get_setting


def _configured(key: str, env_value: str | None = None) -> bool:
    return bool((get_setting(key) or env_value or "").strip())


def build_setup_checklist(db: Session, store: Store | None) -> dict[str, Any]:
    has_store = store is not None
    has_profile = bool(
        store
        and store.name
        and store.city
        and store.area
        and getattr(store.merchant, "category", None)
    )
    menu_count = 0
    if store:
        menu_count = db.execute(
            select(MenuItem).where(MenuItem.store_id == store.id, MenuItem.is_active.is_(True))
        ).scalars().all()
        menu_count = len(menu_count)
    platform_connected = False
    if store:
        platform_connected = (
            db.execute(
                select(PlatformConnection).where(
                    PlatformConnection.store_id == store.id,
                    PlatformConnection.status == "connected",
                )
            ).scalars().first()
            is not None
        ) or bool(store.platform and store.platform_store_key)

    amap_ready = _configured("amap_web_service_key", settings.amap_web_service_key)
    connector_ready = _configured("platform_connector_url", settings.platform_connector_url)
    store_ops_ready = False
    if store:
        from app.services.store_ops import load_roster

        store_ops_ready = bool(load_roster(db, store.id).get("ready"))

    steps = [
        {
            "key": "deploy",
            "title": "完成部署启动",
            "done": True,
            "hint": "服务已在运行。本地可用 start 脚本或 docker compose up。",
            "action": "assist_deploy",
        },
        {
            "key": "store_profile",
            "title": "填写门店基础资料",
            "done": bool(has_store and has_profile),
            "hint": "店名、城市、商圈、品类、客群是诊断前提。",
            "action": "open_settings_store",
        },
        {
            "key": "menu",
            "title": "导入菜单（≥3 道）",
            "done": menu_count >= 3,
            "hint": f"当前菜单 {menu_count} 道。可在设置里手工维护，或一键演示同步平台。",
            "action": "open_settings_menu",
        },
        {
            "key": "platform",
            "title": "对接外卖平台",
            "done": platform_connected,
            "hint": "演示模式可立即同步；正式环境填平台对接 URL 后用 HTTP 模式。",
            "action": "assist_platform",
        },
        {
            "key": "store_ops",
            "title": "设置门店执行人（店长）",
            "done": store_ops_ready,
            "hint": "线下整改要派给具体的人。写下店长姓名后，系统会生成门店任务页；没有证据不能算做完。",
            "action": "open_settings_ops",
        },
        {
            "key": "maps",
            "title": "配置商圈地图（可选）",
            "done": amap_ready,
            "hint": "配置高德 Key 后可自动扫周边竞品；不配也能先用演示门店。",
            "action": "open_settings_system",
        },
    ]
    done_count = sum(1 for step in steps if step["done"])
    return {
        "completed": done_count,
        "total": len(steps),
        "progress_pct": round(100 * done_count / len(steps)),
        "ready_for_diagnosis": done_count >= 3,
        "connector_ready": connector_ready,
        "steps": steps,
    }


def assist_deploy() -> dict[str, Any]:
    return {
        "topic": "deploy",
        "title": "AI 协助部署",
        "summary": "MealKey 默认 SQLite，不强制 Redis/Celery。先把 API 跑起来，再填设置。",
        "steps": [
            {
                "title": "Windows 一键启动",
                "command": ".\\scripts\\start.ps1",
                "detail": "自动创建虚拟环境、安装依赖并启动 http://127.0.0.1:8000",
            },
            {
                "title": "Docker 一键启动",
                "command": "docker compose up -d",
                "detail": "打开 http://127.0.0.1:8000 ，数据落在 mealky-data 卷",
            },
            {
                "title": "手动启动",
                "command": "pip install -r requirements.txt && uvicorn app.main:app --host 127.0.0.1 --port 8000",
                "detail": "复制 .env.example 为 .env 后启动；浏览器打开 / 即可",
            },
        ],
        "checklist": [
            "能打开首页看板",
            "能打开 /docs",
            "设置页可保存门店资料",
        ],
        "next_questions": [
            "部署成功后下一步做什么？",
            "怎么对接美团/饿了么？",
            "没有高德 Key 能用吗？",
        ],
    }


def assist_platform(db: Session, store: Store | None) -> dict[str, Any]:
    checklist = build_setup_checklist(db, store)
    platforms = list_platforms()
    return {
        "topic": "platform",
        "title": "AI 协助对接外卖平台",
        "summary": "官方经营数据用「统一对接契约」接入；演示模式不需真实 Key，可立刻同步菜单与近 14 天指标。",
        "modes": [
            {
                "key": "mock",
                "label": "演示对接（推荐先用）",
                "detail": "一键写入示例菜单+经营数据，验证五 Agent 闭环。",
            },
            {
                "key": "http",
                "label": "HTTP 适配器（正式）",
                "detail": "在设置中填写 platform_connector_url，由你的中间层把美团/饿了么数据转成统一 JSON。",
            },
            {
                "key": "mobile",
                "label": "手机连接码（竞品采集）",
                "detail": "用于商家手机只读采集公开页，不上传账号密码。",
            },
        ],
        "contract": {
            "method": "POST",
            "body": {
                "platform": "meituan",
                "store_id": "门店ID",
                "external_store_id": "平台侧门店ID",
            },
            "response": {
                "external_store_id": "mt_123",
                "store_name": "门店名",
                "menu_items": [{"name": "招牌盖饭", "price": 28, "category": "主食"}],
                "daily_metrics": [
                    {
                        "day": "2026-08-01",
                        "impressions": 4000,
                        "visits": 900,
                        "orders": 120,
                        "gmv": 4600,
                    }
                ],
            },
        },
        "platforms": platforms,
        "setup": checklist,
        "recommended_action": (
            "先点「一键演示对接」验证看板；正式环境再填对接 URL 切到 HTTP。"
            if not checklist["steps"][3]["done"]
            else "平台已连接，可在设置里重新同步或切换 HTTP 模式。"
        ),
        "next_questions": [
            "帮我一键演示对接美团",
            "HTTP 对接要准备什么字段？",
            "对接后如何刷新诊断？",
        ],
    }


def answer_assist_question(question: str, *, db: Session, store: Store | None) -> dict[str, Any] | None:
    text = (question or "").strip().lower()
    if not text:
        return None
    deploy_tokens = ("部署", "安装", "docker", "启动", "怎么跑", "uvicorn", "compose")
    platform_tokens = ("对接", "美团", "饿了么", "平台", "api", "连接码", "同步")
    settings_tokens = ("设置", "基础数据", "门店资料", "高德", "配置")
    storefront_tokens = ("装修", "店页", "主图", "头图", "图片优化", "视觉", "拍照")
    poster_tokens = ("海报", "促销海报", "活动海报", "宣传图", "朋友圈图")

    if any(token in text for token in poster_tokens) and "主图" not in text and "头图" not in text:
        if store is None:
            return {
                "intent": "promo_poster",
                "conclusion": "先选门店，再做促销海报。",
                "actions": ["选择门店后打开促销海报插件"],
            }
        from app.services.promo_poster import build_promo_poster

        pack = build_promo_poster(db, store, prompt=question)
        return {
            **pack,
            "actions": ["在首页预览海报", "下载图片发朋友圈或平台活动"],
            "guide": {"topic": "promo_poster", "plugin": "promo_poster"},
        }

    if any(token in text for token in deploy_tokens):
        guide = assist_deploy()
        return {
            "intent": "deploy",
            "conclusion": guide["summary"],
            "actions": [step["title"] + "：" + step["command"] for step in guide["steps"]],
            "guide": guide,
        }
    if any(token in text for token in platform_tokens):
        guide = assist_platform(db, store)
        return {
            "intent": "platform",
            "conclusion": guide["summary"],
            "actions": [guide["recommended_action"]],
            "guide": guide,
        }
    if any(token in text for token in settings_tokens):
        checklist = build_setup_checklist(db, store)
        pending = [step["title"] for step in checklist["steps"] if not step["done"]]
        return {
            "intent": "settings",
            "conclusion": "打开左侧「设置」，按清单补齐基础数据即可。",
            "actions": pending or ["基础设置已完成，可去刷新诊断"],
            "guide": {"topic": "settings", "setup": checklist},
        }
    if any(token in text for token in storefront_tokens):
        return {
            "intent": "storefront",
            "conclusion": "打开「线上装修」工作台：可让 AI 协助装修方案，或一键优化主图拍摄提示词。",
            "actions": [
                "点「AI协助装修」生成分步改造方案",
                "点「AI优化主图」生成拍摄清单与提示词",
                "对优先动作点「生成装修动作」落库执行",
            ],
            "guide": {"topic": "storefront", "scroll": "section-storefront"},
        }
    return None
