"""Live external-database dataset tests.

These use SQLite, which exercises the *same* DuckDB ATTACH code path as
Postgres/MySQL (install/load extension -> ATTACH READ_ONLY -> USE -> introspect)
without needing a running database server. Postgres/MySQL differ only in the
DSN string built by db_connect._attach_sql (covered separately below).
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import api
from src.analyst import duck
from src.analyst.db_connect import _attach_sql
from src.analyst.tools import python_tool, schema_tools, sql_tool

client = TestClient(api.apps)


@pytest.fixture
def sqlite_db(tmp_path):
    """A small SQLite database to attach as a live DB dataset."""
    p = tmp_path / "shop.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE orders (id INTEGER, region TEXT, revenue REAL)")
    con.executemany(
        "INSERT INTO orders VALUES (?, ?, ?)",
        [(1, "North", 100.0), (2, "South", 250.0), (3, "North", 150.0)],
    )
    con.commit()
    con.close()
    return p


def _connect(db_path, name="shop"):
    res = client.post(
        "/datasets/connect_db",
        json={"engine": "sqlite", "name": name, "database": str(db_path)},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_connect_db_registers_dataset_with_schema(sqlite_db):
    body = _connect(sqlite_db)
    ds_id = body["dataset_id"]
    assert body["engine"] == "sqlite"
    table_names = {t["name"] for t in body["tables"]}
    assert "main.orders" in table_names

    got = client.get(f"/datasets/{ds_id}")
    assert got.status_code == 200
    schema = got.json()["schema"]
    assert "main.orders" in schema
    cols = {c["name"] for c in schema["main.orders"]}
    assert cols == {"id", "region", "revenue"}


def test_live_db_dataset_is_queryable_by_agent_tools(sqlite_db):
    ds_id = _connect(sqlite_db)["dataset_id"]

    # list_tables / get_schema tools
    assert "main.orders" in schema_tools.list_tables_tool(ds_id)["tables"]
    assert "columns" in schema_tools.get_schema_tool(ds_id, "main.orders")

    # run_sql over the live DB
    res = sql_tool.run_sql(
        ds_id, "SELECT region, SUM(revenue) AS total FROM main.orders GROUP BY region ORDER BY region"
    )
    assert "error" not in res, res
    assert res["rows"] == [["North", 250.0], ["South", 250.0]]


def test_live_db_dataset_works_with_run_python(sqlite_db):
    ds_id = _connect(sqlite_db)["dataset_id"]
    # Qualified table main.orders should be exposed as the `orders` DataFrame.
    res = python_tool.run_python(ds_id, "print('rows', len(orders))")
    assert res["return_code"] == 0, res
    assert "rows 3" in res["stdout"]


def test_preview_and_delete_live_db_dataset(sqlite_db):
    ds_id = _connect(sqlite_db)["dataset_id"]

    prev = client.get(f"/datasets/{ds_id}/preview", params={"table": "main.orders"})
    assert prev.status_code == 200
    assert prev.json()["row_count"] == 3

    assert client.delete(f"/datasets/{ds_id}").status_code == 200
    assert client.get(f"/datasets/{ds_id}").status_code == 404


def test_password_is_redacted_in_api_responses(tmp_path):
    """Stored credentials must never be echoed back over the API."""
    p = tmp_path / "creds.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE t (a INTEGER)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()

    res = client.post(
        "/datasets/connect_db",
        json={"engine": "sqlite", "name": "creds", "database": str(p),
              "user": "bob", "password": "hunter2"},
    )
    ds_id = res.json()["dataset_id"]

    detail = client.get(f"/datasets/{ds_id}").json()
    assert detail["connection"]["password"] == "***"
    listing = client.get("/datasets/").json()["datasets"]
    assert all(d.get("connection", {}).get("password") != "hunter2" for d in listing)
    # ...but the real password is still on disk for the connection to work.
    assert duck.load_meta(ds_id)["connection"]["password"] == "hunter2"


def test_unsupported_engine_rejected():
    res = client.post("/datasets/connect_db", json={"engine": "oracle", "database": "x"})
    assert res.status_code == 400
    assert "Unsupported engine" in res.json()["detail"]


def test_bad_connection_returns_400(tmp_path):
    """A postgres host that doesn't exist should fail cleanly, not 500."""
    res = client.post(
        "/datasets/connect_db",
        json={"engine": "postgres", "host": "127.0.0.1", "port": 1,
              "user": "u", "password": "p", "database": "nope"},
    )
    assert res.status_code == 400
    assert "Could not connect" in res.json()["detail"]


@pytest.mark.parametrize(
    "engine,expected_ext,must_contain",
    [
        ("postgres", "postgres", ["dbname=mydb", "host=h1", "port=5432", "TYPE postgres", "READ_ONLY"]),
        ("mysql", "mysql", ["database=mydb", "host=h1", "port=3306", "TYPE mysql", "READ_ONLY"]),
    ],
)
def test_attach_sql_built_correctly_for_server_engines(engine, expected_ext, must_contain):
    """Postgres/MySQL share the tested SQLite path; only the DSN differs."""
    conn = {"engine": engine, "host": "h1", "user": "u", "password": "p", "database": "mydb"}
    if engine == "postgres":
        conn["port"] = 5432
    else:
        conn["port"] = 3306
    ext, sql = _attach_sql(conn)
    assert ext == expected_ext
    for frag in must_contain:
        assert frag in sql, f"{frag} missing from: {sql}"
