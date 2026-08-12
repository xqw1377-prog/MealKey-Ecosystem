"""Store Operating Rhythm — 个性化经营节律（WP1：对的时间）。

三级取值：
1. 老板在设置页手动设的 > 2. 从数据学的 > 3. 品类默认表
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session


@dataclass
class StoreRhythm:
    lunch_peak_start: str = "11:00"
    lunch_peak_end: str = "13:30"
    dinner_peak_start: str = "17:00"
    dinner_peak_end: str = "20:00"
    quiet_hours: tuple[str, str] = ("22:30", "08:00")
    source: str = "category_default"


# 品类默认节律表
_CATEGORY_DEFAULTS: dict[str, StoreRhythm] = {
    "快餐": StoreRhythm("11:00", "13:30", "17:00", "20:00", ("22:30", "08:00"), "category_default"),
    "盖饭": StoreRhythm("11:00", "13:30", "17:00", "20:00", ("22:30", "08:00"), "category_default"),
    "夜宵": StoreRhythm("21:00", "02:00", "17:00", "20:00", ("05:00", "16:00"), "category_default"),
    "烧烤": StoreRhythm("18:00", "23:00", "18:00", "23:00", ("04:00", "16:00"), "category_default"),
    "饮品": StoreRhythm("10:00", "14:00", "15:00", "21:00", ("22:30", "09:00"), "category_default"),
    "甜品": StoreRhythm("13:00", "17:00", "18:00", "21:00", ("22:30", "10:00"), "category_default"),
    "正餐": StoreRhythm("11:00", "14:00", "17:00", "21:00", ("22:30", "08:00"), "category_default"),
}

DEFAULT_RHYTHM = StoreRhythm()


def resolve_store_rhythm(db: Session, store_id: str) -> StoreRhythm:
    """解析门店经营节律。"""
    # 1. 老板手动设置（settings_store）
    try:
        from app.services.settings_store import get_setting

        rhythm_json = get_setting(f"rhythm:{store_id}")
        if rhythm_json:
            import json

            data = json.loads(rhythm_json)
            return StoreRhythm(
                lunch_peak_start=data.get("lunch_peak_start", DEFAULT_RHYTHM.lunch_peak_start),
                lunch_peak_end=data.get("lunch_peak_end", DEFAULT_RHYTHM.lunch_peak_end),
                dinner_peak_start=data.get("dinner_peak_start", DEFAULT_RHYTHM.dinner_peak_start),
                dinner_peak_end=data.get("dinner_peak_end", DEFAULT_RHYTHM.dinner_peak_end),
                quiet_hours=tuple(data.get("quiet_hours", list(DEFAULT_RHYTHM.quiet_hours))),
                source="owner_set",
            )
    except Exception:  # noqa: BLE001
        pass

    # 2. 从品类推断
    try:
        from app.models.entities import Store

        store = db.get(Store, store_id)
        if store and store.merchant:
            category = (store.merchant.category or "").strip()
            for cat_key, rhythm in _CATEGORY_DEFAULTS.items():
                if cat_key in category:
                    return rhythm
    except Exception:  # noqa: BLE001
        pass

    # 3. 默认（快餐）
    return DEFAULT_RHYTHM


def is_in_quiet_hours(rhythm: StoreRhythm, hour: int) -> bool:
    """判断当前小时是否在静默时段。"""
    start_str, end_str = rhythm.quiet_hours
    start_h = int(start_str.split(":")[0])
    end_h = int(end_str.split(":")[0])
    if start_h <= end_h:
        return start_h <= hour < end_h
    else:
        # 跨午夜（如 22:30-08:00）
        return hour >= start_h or hour < end_h


def match_phase(hour: int, rhythm: StoreRhythm) -> Optional[str]:
    """根据当前小时 + 门店节律，判断应该执行哪个 phase。"""
    lunch_start = int(rhythm.lunch_peak_start.split(":")[0])
    lunch_end = int(rhythm.lunch_peak_end.split(":")[0])
    dinner_start = int(rhythm.dinner_peak_start.split(":")[0])
    dinner_end = int(rhythm.dinner_peak_end.split(":")[0])

    # 凌晨：Night Learn
    if 2 <= hour < 6:
        return "night_learn"
    # 早晨：Deep Review
    if 6 <= hour < min(lunch_start - 2, 9):
        return "deep_review"
    # 开店前：Pre-Open Check
    if lunch_start - 2 <= hour < lunch_start - 1:
        return "morning_readiness"
    # 午高峰前 1h：Pre-Peak Decision
    if lunch_start - 1 <= hour < lunch_start:
        return "lunch_nba"
    # 午高峰：Protect
    if lunch_start <= hour < lunch_end:
        return "lunch_protect"
    # 午后：Review + Inter-peak Strategy
    if lunch_end <= hour < dinner_start - 1:
        if hour < lunch_end + 1:
            return "lunch_review"
        if hour >= 16:
            return "dinner_strategy"
    # 晚高峰前 1h
    if dinner_start - 1 <= hour < dinner_start:
        return "lunch_nba"  # 复用 pre-peak
    # 晚高峰：Protect
    if dinner_start <= hour < dinner_end:
        return "lunch_protect"  # 复用 protect
    # 日终
    if hour >= dinner_end:
        return "evening_review"

    return None
