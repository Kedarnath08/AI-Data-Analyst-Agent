import plotly.io as pio
import pytest

from src.analyst.tools import python_tool
from src.analyst.ingest.tabular import ingest_csv
from tests.conftest_helpers import make_csv


@pytest.fixture
def csv_dataset(tmp_path):
    ingest_csv("dspy", make_csv(tmp_path))
    return "dspy"


def test_run_python_captures_stdout(csv_dataset):
    res = python_tool.run_python(csv_dataset, "print('rows', len(data))")
    assert res["return_code"] == 0
    assert "rows 4" in res["stdout"]
    assert res["fig_json"] is None


def test_run_python_returns_plotly_fig(csv_dataset):
    code = (
        "import plotly.graph_objects as go\n"
        "agg = data.groupby('region')['revenue'].sum().reset_index()\n"
        "fig = go.Figure(go.Bar(x=agg['region'], y=agg['revenue']))\n"
        "print('made chart')\n"
    )
    res = python_tool.run_python(csv_dataset, code)
    assert res["return_code"] == 0
    assert res["fig_json"] is not None
    # Round-trips through plotly's JSON loader.
    fig = pio.from_json(res["fig_json"])
    assert fig.data[0].type == "bar"


def test_run_python_surfaces_exception(csv_dataset):
    res = python_tool.run_python(csv_dataset, "raise ValueError('boom')")
    assert res["return_code"] != 0
    assert "boom" in res["stderr"]


def test_run_python_times_out(csv_dataset, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "PY_TIMEOUT_SECONDS", 2)
    res = python_tool.run_python(csv_dataset, "import time; time.sleep(10)")
    assert "error" in res
    assert "timed out" in res["error"].lower()
