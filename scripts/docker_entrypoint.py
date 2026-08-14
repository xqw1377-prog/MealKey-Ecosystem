"""Container entrypoint: run Alembic, then exec the process.

API 默认带 uvicorn workers；SQLite 强制单进程。worker/beat 走原 command。
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    if os.environ.get("RUN_MIGRATIONS_ON_START", "0") == "1":
        from app.db.migration_runner import run_alembic_upgrade_head

        run_alembic_upgrade_head()
        print("ok: upgraded to head", flush=True)

    args = sys.argv[1:]
    if not args:
        args = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    if args[0] == "uvicorn" and "--workers" not in args:
        workers = os.environ.get("WEB_CONCURRENCY", "2")
        database_url = os.environ.get("DATABASE_URL", "")
        if "sqlite" in database_url.lower():
            workers = "1"
        args.extend(["--workers", str(workers)])
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()
