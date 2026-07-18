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
