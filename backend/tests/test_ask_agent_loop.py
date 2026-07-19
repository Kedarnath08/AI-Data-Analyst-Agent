"""Tests for the agent tool-calling loop using scripted Gemini responses.

Only the Gemini boundary is mocked (via the scripted_agent fixture); the loop's
own parsing, tool dispatch, and function_response construction run for real
against real DuckDB data.
"""
from src.analyst.llm import run_agent
from src.analyst.ingest.tabular import ingest_csv
from tests.conftest_helpers import make_csv


def _make_dataset(tmp_path, ds_id="agents"):
    ingest_csv(ds_id, make_csv(tmp_path))
    return ds_id


def test_full_tool_sequence_reaches_answer(tmp_path, scripted_agent):
    ds = _make_dataset(tmp_path)
    scripted_agent([
        [("list_tables", {})],
        [("get_schema", {"table": "data"})],
        [("run_sql", {"query": "SELECT region, SUM(revenue) AS total FROM data GROUP BY region"})],
        "North has 6500 and South has 6750 in total revenue.",
    ])
    result = run_agent(ds, "Total revenue by region?")
    assert result["answer"].startswith("North has 6500")
    assert result["iterations"] == 4
    assert result.get("truncated") is None
    tools_called = [t["tool"] for t in result["trace"]]
    assert tools_called == ["list_tables", "get_schema", "run_sql"]


def test_run_sql_result_flows_into_trace(tmp_path, scripted_agent):
    ds = _make_dataset(tmp_path)
    scripted_agent([
        [("run_sql", {"query": "SELECT COUNT(*) AS n FROM data"})],
        "There are 4 rows.",
    ])
    result = run_agent(ds, "How many rows?")
    sql_trace = result["trace"][0]
    assert sql_trace["tool"] == "run_sql"
    assert sql_trace["result_preview"]["row_count"] == 1
    assert sql_trace["result_preview"]["rows"] == [[4]]


def test_loop_terminates_at_iteration_cap(tmp_path, scripted_agent, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "MAX_AGENT_ITERATIONS", 3)
    ds = _make_dataset(tmp_path)
    # Model never stops calling tools.
    scripted_agent([[("list_tables", {})]] * 10)
    result = run_agent(ds, "loop forever")
    assert result["truncated"] is True
    assert result["iterations"] == 3


def test_bad_tool_args_are_captured_not_crashed(tmp_path, scripted_agent):
    ds = _make_dataset(tmp_path)
    scripted_agent([
        [("run_sql", {"query": "SELECT bogus FROM nope"})],  # invalid SQL
        "Handled the error gracefully.",
    ])
    result = run_agent(ds, "trigger error")
    assert result["answer"] == "Handled the error gracefully."
    assert "error" in result["trace"][0]["result_preview"]


def test_python_fig_json_surfaced_but_not_sent_to_model(tmp_path, scripted_agent):
    ds = _make_dataset(tmp_path)
    code = (
        "import plotly.graph_objects as go\n"
        "fig = go.Figure(go.Bar(x=['a'], y=[1]))\n"
        "print('done')\n"
    )
    scripted_agent([
        [("run_python", {"code": code})],
        "Here is your chart.",
    ])
    result = run_agent(ds, "make a chart")
    # The figure is surfaced at the top level of the response...
    assert result["fig_json"] is not None
    # ...but never sent to the model / recorded in the trace (only a flag is).
    preview = result["trace"][0]["result_preview"]
    assert "fig_json" not in preview
    assert preview["chart_generated"] is True


def test_rate_limit_waiting_is_bounded_and_reported(monkeypatch, tmp_path):
    """A 429 storm must not hang the request. The wait budget caps total sleep
    and the result says it was rate limited rather than failing opaquely."""
    from src.analyst import llm as analyst_llm

    ds = _make_dataset(tmp_path, "ratelimited")

    slept: list[float] = []
    monkeypatch.setattr(analyst_llm.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(analyst_llm.settings, "MAX_RATE_LIMIT_WAIT_SECONDS", 45)

    def always_429(model, contents, config=None):
        raise RuntimeError("429 RESOURCE_EXHAUSTED ... 'retryDelay': '20s'")

    monkeypatch.setattr(analyst_llm.client.models, "generate_content", always_429)

    out = run_agent(ds, "how many rows?")

    assert out["rate_limited"] is True
    assert out["answer"] is None
    # 22s per retry against a 45s budget -> two sleeps, then give up.
    assert slept == [22.0, 22.0]
    assert sum(slept) <= 45
    assert out["waited_seconds"] == 44


def test_non_rate_limit_errors_are_not_retried(monkeypatch, tmp_path):
    """Only 429s are worth waiting on; other failures should surface at once."""
    from src.analyst import llm as analyst_llm

    ds = _make_dataset(tmp_path, "badkey")
    slept: list[float] = []
    monkeypatch.setattr(analyst_llm.time, "sleep", lambda s: slept.append(s))

    def boom(model, contents, config=None):
        raise RuntimeError("403 PERMISSION_DENIED: API key invalid")

    monkeypatch.setattr(analyst_llm.client.models, "generate_content", boom)

    out = run_agent(ds, "how many rows?")
    assert out["answer"] is None
    assert "PERMISSION_DENIED" in out["error"]
    assert slept == []
    assert not out.get("rate_limited")
