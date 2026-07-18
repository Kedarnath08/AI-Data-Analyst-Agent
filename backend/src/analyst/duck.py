"""DuckDB connection + schema helpers.

Each dataset is one DuckDB database file at data/datasets/<id>.duckdb.
Connections are opened and closed per call — we never hold a long-lived
write handle — which sidesteps DuckDB's single-writer / cross-process
file-locking constraints for a simple portfolio-scale workload.
"""
from pathlib import Path

import duckdb

DATASETS_DIR = Path("data/datasets")
DATASETS_DIR.mkdir(parents=True, exist_ok=True)


def db_path(dataset_id: str) -> Path:
    return DATASETS_DIR / f"{dataset_id}.duckdb"


def meta_path(dataset_id: str) -> Path:
    return DATASETS_DIR / f"{dataset_id}.meta.json"


def exists(dataset_id: str) -> bool:
    return db_path(dataset_id).exists()


def connect(dataset_id: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path(dataset_id)), read_only=read_only)


def get_schema(dataset_id: str) -> dict[str, list[dict]]:
    """Returns {table_name: [{"name": col, "type": dtype}, ...]}."""
    con = connect(dataset_id, read_only=True)
    try:
        rows = con.execute(
            "SELECT table_name, column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = 'main' "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
    finally:
        con.close()
    schema: dict[str, list[dict]] = {}
    for table, col, dtype in rows:
        schema.setdefault(table, []).append({"name": col, "type": dtype})
    return schema


def list_tables(dataset_id: str) -> list[str]:
    return list(get_schema(dataset_id).keys())
