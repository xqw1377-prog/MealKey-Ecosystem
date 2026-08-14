"""Dump Postgres using DATABASE_URL. Secrets stay in env, never in the database."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1
    if "sqlite" in url.lower():
        print("SQLite is not a production backup target. Use Postgres.", file=sys.stderr)
        return 1
    out_dir = Path(os.environ.get("BACKUP_DIR", "backups"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = out_dir / f"mealky-{stamp}.dump"
    subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--file", str(dest), url],
        check=True,
    )
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
