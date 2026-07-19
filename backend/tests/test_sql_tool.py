import pytest

from src.analyst import duck
from src.analyst.tools import sql_tool
from tests.conftest_helpers import make_csv
from src.analyst.ingest.tabular import ingest_csv


@pytest.fixture
def csv_dataset(tmp_path):
    csv = make_csv(tmp_path)
    ingest_csv("ds1", csv)
    return "ds1"


def test_run_sql_select_returns_rows(csv_dataset):
    res = sql_tool.run_sql(csv_dataset, "SELECT region, revenue FROM data ORDER BY revenue")
    assert "error" not in res
    assert res["columns"] == ["region", "revenue"]
    assert res["row_count"] == 4
    assert res["truncated"] is False


def test_run_sql_rejects_non_select(csv_dataset):
    for bad in ["DROP TABLE data", "DELETE FROM data", "UPDATE data SET units=0",
                "INSERT INTO data VALUES (1)", "CREATE TABLE x AS SELECT 1"]:
        res = sql_tool.run_sql(csv_dataset, bad)
        assert "error" in res, f"should reject: {bad}"


def test_run_sql_rejects_multiple_statements(csv_dataset):
    res = sql_tool.run_sql(csv_dataset, "SELECT 1; DROP TABLE data")
    assert "error" in res


def test_run_sql_row_limit_truncates(csv_dataset, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "SQL_ROW_LIMIT", 2)
    res = sql_tool.run_sql(csv_dataset, "SELECT * FROM data")
    assert res["row_count"] == 2
    assert res["truncated"] is True


def test_run_sql_error_is_captured(csv_dataset):
    res = sql_tool.run_sql(csv_dataset, "SELECT nonexistent_col FROM data")
    assert "error" in res


def test_with_cte_allowed(csv_dataset):
    res = sql_tool.run_sql(
        csv_dataset,
        "WITH t AS (SELECT region, SUM(revenue) r FROM data GROUP BY region) SELECT * FROM t",
    )
    assert "error" not in res
    assert res["row_count"] == 2


def test_dates_and_decimals_are_json_serializable(tmp_path):
    """Query results are JSON-encoded into SSE frames and the model's
    function_response, but DuckDB returns real date objects — which json.dumps
    cannot encode. They must come back as ISO strings."""
    import json

    from src.analyst import duck
    from src.analyst.tools.sql_tool import run_sql

    ds = "datetypes"
    con = duck.connect(ds)
    con.execute(
        "CREATE TABLE data AS SELECT * FROM (VALUES "
        "(DATE '2026-01-05', TIMESTAMP '2026-01-05 10:30:00', 12.5), "
        "(DATE '2026-02-10', TIMESTAMP '2026-02-10 08:00:00', 7.25)"
        ") AS t(d, ts, amount)"
    )
    con.close()

    out = run_sql(ds, "SELECT d, ts, amount FROM data ORDER BY d")
    assert "error" not in out, out

    # The whole result must survive a plain json.dumps, as SSE requires.
    json.dumps(out)

    assert out["rows"][0][0] == "2026-01-05"
    assert out["rows"][0][1].startswith("2026-01-05T")
    assert out["rows"][0][2] == 12.5
