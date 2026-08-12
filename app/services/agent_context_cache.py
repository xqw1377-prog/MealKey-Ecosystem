"""AgentContext 进程内 TTL 缓存。

目的：让 chief_agent 按需调用单个专业 agent 时，不必每次重建 context
（build_store_state + DB 查询 + item_snapshots 是重操作）。

策略：
- 按 (store_id, days) 缓存 _AgentContext，TTL 默认 5 分钟；
- 动作执行（apply_menu_* / create_*_action）后应调 invalidate(store_id) 主动失效，
  避免读到过期数据；
- 缓存只存进程内，不跨 worker（多 worker 各自缓存，可接受）。
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# 避免循环 import：只在类型检查时引用，运行时用延迟 import
if TYPE_CHECKING:
    from app.services.agents import _AgentContext

_CACHE: dict[tuple[str, int], tuple[float, "_AgentContext"]] = {}
_LOCK = threading.Lock()
_DEFAULT_TTL_SECONDS = 300  # 5 分钟


def get_context(
    db: "Session",
    store_id: str,
    days: int = 7,
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    force_refresh: bool = False,
) -> "_AgentContext | None":
    """获取 agent context，命中缓存则直接返回，否则构建并缓存。"""
    # 延迟 import 避免循环依赖
    from app.services.agents import build_agent_context

    key = (store_id, days)
    now = time.monotonic()

    if not force_refresh:
        with _LOCK:
            cached = _CACHE.get(key)
            if cached is not None:
                expires_at, ctx = cached
                if now < expires_at:
                    return ctx
                # 过期，移除
                _CACHE.pop(key, None)

    ctx = build_agent_context(db=db, store_id=store_id, days=days)
    if ctx is None:
        return None

    with _LOCK:
        _CACHE[key] = (now + ttl_seconds, ctx)
    return ctx


def invalidate(store_id: str) -> None:
    """主动失效某门店的所有 context 缓存（动作执行后调用）。"""
    with _LOCK:
        keys_to_remove = [k for k in _CACHE if k[0] == store_id]
        for k in keys_to_remove:
            _CACHE.pop(k, None)


def clear_all() -> None:
    """清空全部缓存（测试用）。"""
    with _LOCK:
        _CACHE.clear()


def cache_size() -> int:
    """当前缓存条目数（观测/测试用）。"""
    with _LOCK:
        return len(_CACHE)
