"""首页只读请求不得同步等待大模型。

对话、日更、诊断任务可以走智能引擎；GET dashboard / workspace / manager_brief
必须先用规则引擎返回，否则 Key 配得越全，首页越容易被 failover 拖死。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

_homepage_read: ContextVar[bool] = ContextVar("mealky_homepage_read", default=False)


def is_homepage_read() -> bool:
    return bool(_homepage_read.get())


@contextmanager
def homepage_read_scope() -> Iterator[None]:
    token = _homepage_read.set(True)
    try:
        yield
    finally:
        _homepage_read.reset(token)
