from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base

logger = logging.getLogger(__name__)


def apply_schema_backfill(engine: Engine) -> None:
    """Backfill newly added columns for local SQLite and Postgres databases.

    The app currently auto-creates tables for local development, but `create_all`
    does not alter existing tables. This helper keeps old databases usable
    after model fields are added.
    """

    dialect = engine.dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        return

    inspector = inspect(engine)
    missing_tables = [
        table
        for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name)
        if not inspector.has_table(table.name)
    ]
    if missing_tables:
        Base.metadata.create_all(bind=engine, tables=missing_tables)
        inspector = inspect(engine)

    with engine.begin() as conn:
        tables = sorted(Base.metadata.tables.values(), key=lambda item: item.name)
        for table in tables:
            if not inspector.has_table(table.name):
                continue

            existing_columns = {item["name"] for item in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue

                if dialect == "postgresql":
                    type_sql = column.type.compile(dialect=engine.dialect)
                    conn.execute(
                        text(
                            f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{column.name}" {type_sql}'
                        )
                    )
                else:
                    ddl = _build_sqlite_add_column_ddl(table.name, column, engine)
                    conn.execute(text(ddl))
                existing_columns.add(column.name)
                logger.info("schema backfill added %s.%s", table.name, column.name)


def _build_sqlite_add_column_ddl(table_name: str, column: Any, engine: Engine) -> str:
    type_sql = column.type.compile(dialect=engine.dialect)
    parts = [f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {type_sql}']

    default_sql = _column_default_sql(column.default.arg) if column.default is not None else None
    if default_sql is not None:
        parts.append(f"DEFAULT {default_sql}")

    # For SQLite backfill we only add NOT NULL when a concrete default exists.
    if not column.nullable and default_sql is not None:
        parts.append("NOT NULL")

    return " ".join(parts)


def _column_default_sql(value: Any) -> str | None:
    if callable(value):
        return None
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    text_value = str(value).replace("'", "''")
    return f"'{text_value}'"


apply_sqlite_schema_backfill = apply_schema_backfill
