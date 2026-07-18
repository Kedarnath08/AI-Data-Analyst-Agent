"""DuckDB connection + schema helpers, for both file-backed and live-DB datasets.

A dataset is either:
  - a **file** dataset: one DuckDB database file at data/datasets/<id>.duckdb, or
  - a **database** dataset: a live external DB (Postgres/MySQL/SQLite) that we
    ATTACH into a fresh in-memory DuckDB per call (see db_connect.py).

All callers use the same helpers (connect / get_schema / list_tables / sql_ref)
regardless of kind, so the agent tools work identically over files and live DBs.
Connections are opened and closed per call.
"""
import json
from pathlib import Path

import duckdb

DATASETS_DIR = Path("data/datasets")
DATASETS_DIR.mkdir(parents=True, exist_ok=True)


def db_path(dataset_id: str) -> Path:
    return DATASETS_DIR / f"{dataset_id}.duckdb"


def meta_path(dataset_id: str) -> Path:
    return DATASETS_DIR / f"{dataset_id}.meta.json"


def load_meta(dataset_id: str) -> dict | None:
    p = meta_path(dataset_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_database(dataset_id: str) -> bool:
    m = load_meta(dataset_id)
    return bool(m and m.get("kind") == "database")


def exists(dataset_id: str) -> bool:
    return db_path(dataset_id).exists() or is_database(dataset_id)


def connect(dataset_id: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if is_database(dataset_id):
        from src.analyst.db_connect import open_attached
        return open_attached(load_meta(dataset_id)["connection"])
    return duckdb.connect(str(db_path(dataset_id)), read_only=read_only)


def get_schema(dataset_id: str) -> dict[str, list[dict]]:
    """{table (or schema.table for DBs): [{"name": col, "type": dtype}, ...]}."""
    con = connect(dataset_id, read_only=True)
    try:
        if is_database(dataset_id):
            from src.analyst.db_connect import schema_from_attached
            return schema_from_attached(con)
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


def sql_ref(display_name: str) -> str:
    """Quote a table display name into a SQL identifier.

    "data" -> "data"; "public.users" -> "public"."users" (works because a
    database connection has already `USE`d the attached catalog).
    """
    return ".".join(f'"{part}"' for part in display_name.split("."))
