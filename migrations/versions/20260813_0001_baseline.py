"""baseline schema

Revision ID: 20260813_0001
Revises:
Create Date: 2026-08-13 00:00:00
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401
from app.db.base import Base

revision = "20260813_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
