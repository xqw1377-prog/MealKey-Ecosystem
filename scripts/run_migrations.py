from __future__ import annotations

from app.db.migration_runner import run_alembic_upgrade_head


if __name__ == "__main__":
    run_alembic_upgrade_head()
    print("ok: upgraded to head")
