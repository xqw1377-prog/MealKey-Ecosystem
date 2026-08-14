"""促销海报插件：有需要时从首页打开，不进侧栏技能。

先出可落地的海报稿（文案 + 版式），不另开经营入口。
算力不足时仍给模板稿，并带上充值入口。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import MenuItem, Store
from app.services.commercial.board import _wallet_payload

THEMES: dict[str, dict[str, Any]] = {
    "lunch": {
        "label": "午市",
        "kicker": "午市限定",
        "headline": "这一口，赶得上上班点",
        "subhead": "热气足 · 出餐快 · 分量够",
        "bg": "#C23A2B",
        "accent": "#F4C430",
        "ink": "#FFF8EE",
    },
    "new": {
        "label": "新品",
        "kicker": "新品开吃",
        "headline": "今天上新，先吃为敬",
        "subhead": "新鲜出锅 · 限时尝鲜",
        "bg": "#1F6B4A",
        "accent": "#E8C547",
        "ink": "#F7FFF6",
    },
    "festival": {
        "label": "节日",
        "kicker": "节日特惠",
        "headline": "过节就该多点好吃的",
        "subhead": "家人朋友一起点，桌上更热闹",
        "bg": "#8B1E3F",
        "accent": "#F2C14E",
        "ink": "#FFF6EA",
    },
    "weekend": {
        "label": "周末",
        "kicker": "周末加量",
        "headline": "在家点一份，桌上就热闹",
        "subhead": "多一个人也够分",
        "bg": "#2C4A7C",
        "accent": "#F0B429",
        "ink": "#F4F7FF",
    },
    "value": {
        "label": "超值",
        "kicker": "超值套餐",
        "headline": "一份到位，不多花冤枉钱",
        "subhead": "主食 + 配菜，点完就能吃",
        "bg": "#D35400",
        "accent": "#FFE08A",
        "ink": "#FFF8F0",
    },
}


def looks_like_poster_request(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if "主图" in raw or "头图" in raw:
        return False
    return any(token in raw for token in ("海报", "促销海报", "活动海报", "宣传图", "朋友圈图"))


def detect_occasion(text: str) -> str:
    raw = text or ""
    if any(token in raw for token in ("午", "午餐", "上班", "工作餐")):
        return "lunch"
    if any(token in raw for token in ("新品", "上新", "新菜")):
        return "new"
    if any(token in raw for token in ("节", "端午", "中秋", "国庆", "年夜", "春节")):
        return "festival"
    if any(token in raw for token in ("周末", "周六", "周日")):
        return "weekend"
    return "value"


def _extract_offer(text: str) -> str | None:
    raw = text or ""
    match = re.search(r"满\s*(\d+)\s*(?:减|抵)\s*(\d+)", raw)
    if match:
        return f"满{match.group(1)}减{match.group(2)}"
    match = re.search(r"(\d+)\s*元?\s*套餐", raw)
    if match:
        return f"{match.group(1)}元套餐"
    match = re.search(r"(\d+)\s*折", raw)
    if match:
        return f"{match.group(1)}折优惠"
    return None


def _extract_dish(text: str) -> str | None:
    match = re.search(r"([\u4e00-\u9fff]{2,12}(?:饭|面|套餐|餐|粉|粥|鸡|鱼|锅))", text or "")
    if not match:
        return None
    name = match.group(1)
    for prefix in ("主推", "招牌", "热卖", "爆款", "推荐"):
        if name.startswith(prefix) and len(name) > len(prefix) + 1:
            name = name[len(prefix) :]
            break
    return name


def _hero_dish(db: Session, store_id: str) -> tuple[str, float | None]:
    items = db.execute(
        select(MenuItem).where(MenuItem.store_id == store_id, MenuItem.is_active.is_(True))
    ).scalars().all()
    for item in items:
        version = item.current_version
        if version and version.name:
            return version.name, version.price
    return "招牌套餐", None


def build_promo_poster(
    db: Session,
    store: Store,
    *,
    prompt: str = "",
    occasion: str | None = None,
    offer: str | None = None,
    dish: str | None = None,
) -> dict[str, Any]:
    theme_key = occasion if occasion in THEMES else detect_occasion(prompt)
    theme = THEMES[theme_key]
    hero, price = _hero_dish(db, store.id)
    dish_name = (dish or _extract_dish(prompt) or hero).strip()
    offer_text = (offer or _extract_offer(prompt) or "门店活动价").strip()
    if offer_text == "门店活动价" and price:
        offer_text = f"活动价 ¥{int(price)}" if float(price).is_integer() else f"活动价 ¥{price:.1f}"
    end = date.today() + timedelta(days=6)
    period = f"{date.today().month}/{date.today().day}–{end.month}/{end.day}"
    wallet = _wallet_payload(db, store.merchant_id)
    alert = wallet.get("alert") or {}
    llm_ready = alert.get("status") == "ok"
    poster = {
        "plugin": "promo_poster",
        "theme": theme_key,
        "theme_label": theme["label"],
        "store_name": store.name,
        "kicker": theme["kicker"],
        "headline": theme["headline"],
        "subhead": theme["subhead"],
        "dish": dish_name,
        "offer": offer_text,
        "period": period,
        "footnote": "仅限外卖 · 以门店实际活动为准",
        "colors": {
            "bg": theme["bg"],
            "accent": theme["accent"],
            "ink": theme["ink"],
        },
        "copy_pack": {
            "wechat": f"{store.name}｜{theme['kicker']} {dish_name} {offer_text}，{period} 可用。",
            "platform": f"{theme['kicker']}·{dish_name} {offer_text}",
        },
        "mode": "template",
        "llm_ready": llm_ready,
    }
    return {
        "intent": "promo_poster",
        "plugin": "promo_poster",
        "conclusion": f"已按{theme['label']}场景做好一张促销海报，需要时改文案或换主题即可。",
        "poster": poster,
        "wallet": wallet,
        "wallet_alert": alert if alert.get("status") != "ok" else None,
    }
