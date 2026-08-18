"""pytest 全局配置。

测试环境强制关闭所有 LLM 调用，避免测试时发起真实网络请求导致超时。
- MEALKY_AGENT_LLM=0：关闭 narrator
- MEALKY_DIAGNOSIS_LLM=0：关闭 LLM 诊断推理器
生产环境通过 .env 开启。

PRE-PROD-GATE-01 P0-6: 测试 DB 隔离。
测试绝不触碰 ./mealky.db（dev/prod 持久库）。DATABASE_URL 在 app 模块 import 之前
指向独立临时文件；app/core/config.py 的 load_dotenv(override=False) 不会覆盖已设的 env。
"""

import atexit
import os
import tempfile
from pathlib import Path

# 必须在所有 app 模块 import 之前设置
os.environ["MEALKY_AGENT_LLM"] = "0"
os.environ["MEALKY_DIAGNOSIS_LLM"] = "0"
os.environ["MEALKEY_DISABLE_CLOCK"] = "1"

# ── 测试 DB 隔离：每个 test session 用独立临时 SQLite，永不写 dev/prod 库 ──
_TEST_DB_PATH = Path(tempfile.gettempdir()) / f"mealkey_test_{os.getpid()}.db"
# 启动前清掉可能残留的旧临时库，确保 schema 干净
if _TEST_DB_PATH.exists():
    _TEST_DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"


@atexit.register
def _cleanup_test_db() -> None:
    try:
        if _TEST_DB_PATH.exists():
            _TEST_DB_PATH.unlink()
    except OSError:
        pass

