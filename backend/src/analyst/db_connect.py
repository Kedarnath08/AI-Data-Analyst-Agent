"""Live external-database support via DuckDB's ATTACH (Postgres / MySQL / SQLite).

A "database dataset" points at a live external DB instead of an uploaded file.
We open a fresh in-memory DuckDB, INSTALL/LOAD the right extension, ATTACH the
external DB READ_ONLY (so the agent can never mutate it), and `USE` it so the
agent can reference tables by their `schema.table` name. All the existing agent
tools (get_schema / run_sql / run_python) then work unchanged over the live DB.

SECURITY: connection details (including password) are persisted in the dataset's
gitignored meta.json in plaintext — fine for a local/portfolio setup, NOT for
production. READ_ONLY ATTACH limits blast radius.
"""
import duckdb

ATTACH_ALIAS = "db"
SUPPORTED_ENGINES = {"postgres", "mysql", "sqlite"}

# Schemas that are the DB engine's own system catalogs — hidden from the agent.
_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "sys", "mysql",
                   "performance_schema", "duckdb_catalog"}


def _dsn_escape(v: str) -> str:
    return str(v).replace("'", "''")


def _attach_sql(conn: dict) -> tuple[str, str]:
    """Returns (extension_name, ATTACH SQL) for the given connection config."""
    engine = (conn.get("engine") or "").lower()
    if engine == "sqlite":
        path = _dsn_escape(conn.get("path") or conn.get("database") or "")
        return "sqlite", (
            f"ATTACH '{path}' AS {ATTACH_ALIAS} (TYPE sqlite, READ_ONLY)"
        )
    if engine == "postgres":
        parts = [
            f"dbname={conn.get('database', '')}",
            f"user={conn.get('user', '')}",
            f"password={conn.get('password', '')}",
            f"host={conn.get('host', 'localhost')}",
            f"port={conn.get('port', 5432)}",
        ]
        dsn = _dsn_escape(" ".join(parts))
        return "postgres", (
            f"ATTACH '{dsn}' AS {ATTACH_ALIAS} (TYPE postgres, READ_ONLY)"
        )
    if engine == "mysql":
        parts = [
            f"host={conn.get('host', 'localhost')}",
            f"port={conn.get('port', 3306)}",
            f"user={conn.get('user', '')}",
            f"password={conn.get('password', '')}",
            f"database={conn.get('database', '')}",
        ]
        dsn = _dsn_escape(" ".join(parts))
        return "mysql", (
            f"ATTACH '{dsn}' AS {ATTACH_ALIAS} (TYPE mysql, READ_ONLY)"
        )
    raise ValueError(f"Unsupported engine '{engine}'. Supported: {sorted(SUPPORTED_ENGINES)}")


def open_attached(conn: dict) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with the external DB attached READ_ONLY and selected."""
    extension, attach = _attach_sql(conn)
    con = duckdb.connect()
    con.execute(f"INSTALL {extension}")
    con.execute(f"LOAD {extension}")
    con.execute(attach)
    con.execute(f"USE {ATTACH_ALIAS}")
    return con


def schema_from_attached(con: duckdb.DuckDBPyConnection) -> dict[str, list[dict]]:
    """Introspect user tables in the attached DB as {"schema.table": [cols]}.

    Uses duckdb_columns() rather than information_schema: after `USE db` the
    unqualified information_schema resolves against the attached catalog (which
    doesn't have one), whereas duckdb_columns() spans all attached catalogs.
    """
    rows = con.execute(
        "SELECT schema_name, table_name, column_name, data_type "
        "FROM duckdb_columns() WHERE database_name = ? "
        "ORDER BY schema_name, table_name, column_index",
        [ATTACH_ALIAS],
    ).fetchall()
    schema: dict[str, list[dict]] = {}
    for tschema, tname, col, dtype in rows:
        if (tschema or "").lower() in _SYSTEM_SCHEMAS:
            continue
        key = f"{tschema}.{tname}"
        schema.setdefault(key, []).append({"name": col, "type": dtype})
    return schema


def test_and_introspect(conn: dict) -> dict[str, list[dict]]:
    """Open the connection, verify it works, and return the schema. Raises on failure."""
    con = open_attached(conn)
    try:
        return schema_from_attached(con)
    finally:
        con.close()
