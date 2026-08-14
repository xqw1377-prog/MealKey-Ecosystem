"""schema backfill as versioned migration

Revision ID: 20260813_0002
Revises: 20260813_0001
Create Date: 2026-08-13 16:00:00

线上已有库：baseline 只 create_all，不会 ALTER 新列。
本 revision 把列级补齐纳入 Alembic，后续模型变更继续加新 revision，不要再靠启动 create_all。
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401
from app.db.schema_backfill import apply_schema_backfill

revision = "20260813_0002"
down_revision = "20260813_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    apply_schema_backfill(op.get_bind().engine)


def downgrade() -> None:
    return
