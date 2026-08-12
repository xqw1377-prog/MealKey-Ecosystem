from sqlalchemy import create_engine, inspect, text

from app.db.schema_backfill import apply_sqlite_schema_backfill


def test_sqlite_schema_backfill_adds_missing_experiment_columns(tmp_path) -> None:
    db_path = tmp_path / "backfill.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE experiment (
                    id VARCHAR(36) PRIMARY KEY,
                    created_at DATETIME,
                    recommendation_id VARCHAR(36),
                    store_id VARCHAR(36),
                    item_id VARCHAR(36),
                    baseline_value FLOAT,
                    observed_value FLOAT,
                    lift_pct FLOAT,
                    baseline_from DATE,
                    baseline_to DATE,
                    observe_from DATE,
                    observe_to DATE,
                    control_desc VARCHAR(200),
                    attribution_quality VARCHAR(16),
                    result VARCHAR(16),
                    notes TEXT
                )
                """
            )
        )

    apply_sqlite_schema_backfill(engine)

    columns = {item["name"] for item in inspect(engine).get_columns("experiment")}
    assert {
        "guardrails_json",
        "success_metric_json",
        "primary_variable",
        "executor",
        "permission_basis_json",
    }.issubset(columns)
