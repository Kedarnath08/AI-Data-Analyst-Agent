"""The agentic tool-calling loop over Gemini native function calling.

IMPORTANT (verified against the live API): gemini-3-flash-preview is a thinking
model. Each function_call part carries a `thought_signature` that MUST be sent
back on the next request or the API returns 400 INVALID_ARGUMENT. We preserve it
by appending the model's own `candidate.content` back into the history VERBATIM —
never reconstruct the model turn from scratch. This requires google-genai>=2.12.1.
"""
import re
import time
from typing import Any

from google import genai
from google.genai import types

from src.config import settings
from src.analyst.tools import python_tool, schema_tools, sql_tool

client = genai.Client(api_key=settings.GOOGLE_API_KEY)

SYSTEM_PROMPT = (
    "You are an expert data analyst agent working with a single dataset, queried "
    "through DuckDB. The dataset is either an uploaded file or a live external "
    "database (Postgres/MySQL/SQLite) attached read-only. You have tools to inspect "
    "the schema, run read-only SQL, and run Python (pandas + plotly are available). \n"
    "- If you don't know the table/column names, call list_tables and get_schema first.\n"
    "- Use table names exactly as returned by those tools. For live databases they are "
    "schema-qualified (e.g. public.users) — use them verbatim in SQL.\n"
    "- Prefer run_sql for filtering and aggregation; it is read-only (SELECT/WITH only).\n"
    "- Use run_python when you need a chart or logic SQL can't express. In run_python, "
    "each table is preloaded as a pandas DataFrame named after the table. To return a "
    "chart, assign a plotly.graph_objects Figure to a variable named `fig`. Print a short "
    "text summary of any results — do not print entire DataFrames.\n"
    "- When you have enough information, reply with a concise final answer in plain text "
    "and stop calling tools."
)

TOOLS = [{
    "function_declarations": [
        {
            "name": "list_tables",
            "description": "List all table names available in this dataset.",
            "parameters": {"type": "OBJECT", "properties": {}},
        },
        {
            "name": "get_schema",
            "description": "Get column names and types for one table, or all tables if 'table' is omitted.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "table": {"type": "STRING", "description": "Table name; omit for all tables."}
                },
            },
        },
        {
            "name": "run_sql",
            "description": (
                "Run a single read-only DuckDB SQL SELECT/WITH query and return the resulting "
                f"rows (capped at {settings.SQL_ROW_LIMIT}). Use aggregation or LIMIT for large tables."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {"query": {"type": "STRING", "description": "A single SELECT/WITH statement."}},
                "required": ["query"],
            },
        },
        {
            "name": "run_python",
            "description": (
                "Run Python (pandas + plotly available) for analysis or charting. Each dataset "
                "table is preloaded as a pandas DataFrame named after the table (for "
                "schema-qualified tables like public.users the variable is just `users`). "
                "Assign a plotly Figure to `fig` to return a chart. print() any textual results "
                "you want back."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {"code": {"type": "STRING", "description": "Python source to execute."}},
                "required": ["code"],
            },
        },
    ]
}]

TOOL_IMPLS = {
    "list_tables": lambda dataset_id, **a: schema_tools.list_tables_tool(dataset_id),
    "get_schema": lambda dataset_id, **a: schema_tools.get_schema_tool(dataset_id, a.get("table")),
    "run_sql": lambda dataset_id, **a: sql_tool.run_sql(dataset_id, a.get("query", "")),
    "run_python": lambda dataset_id, **a: python_tool.run_python(dataset_id, a.get("code", "")),
}


def _as_response_dict(result: Any) -> dict:
    """function_response.response must be a JSON dict."""
    if isinstance(result, dict):
        return result
    return {"result": result}


def _preview(result: Any) -> Any:
    """Compact result for the trace (avoid dumping huge blobs)."""
    if isinstance(result, dict):
        out = {}
        for k, v in result.items():
            if k == "fig_json":
                out[k] = "<figure>" if v else None
            elif isinstance(v, str) and len(v) > 500:
                out[k] = v[:500] + "…"
            else:
                out[k] = v
        return out
    s = str(result)
    return s[:500] + "…" if len(s) > 500 else s


def _config() -> dict:
    return {
        "system_instruction": SYSTEM_PROMPT,
        "tools": TOOLS,
        "temperature": 0.2,
    }


_RETRY_AFTER_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")
# Google reports which quota was hit; per-day ones are not worth retrying.
_PER_DAY_QUOTA_RE = re.compile(r"PerDay", re.IGNORECASE)
_QUOTA_LIMIT_RE = re.compile(r"limit:\s*(\d+)")


class RateLimitExhausted(Exception):
    """Ran out of the request's total budget for waiting on rate limits."""


class DailyQuotaExhausted(Exception):
    """The model's per-day free-tier quota is spent; retrying cannot help."""


class _WaitBudget:
    """Caps total time spent sleeping on 429s across a whole /ask request.

    Retrying per-call is not enough: one question makes several model calls, so
    an unbounded per-call retry can stack into many minutes of silent waiting
    while the UI just shows a spinner. A single shared budget bounds the worst
    case for the request as a whole.
    """

    def __init__(self, total_seconds: float):
        self.remaining = total_seconds
        self.waited = 0.0

    def sleep(self, seconds: float) -> None:
        if seconds > self.remaining:
            raise RateLimitExhausted(
                f"Waited {self.waited:.0f}s on API rate limits and the next retry "
                f"needs {seconds:.0f}s more, which exceeds the "
                f"{settings.MAX_RATE_LIMIT_WAIT_SECONDS}s budget for one question."
            )
        self.remaining -= seconds
        self.waited += seconds
        time.sleep(seconds)


def _generate_streaming(contents, budget: "_WaitBudget"):
    """Generator wrapper around a Gemini call that retries on rate limits.

    Yields {"type": "waiting", ...} before each sleep so callers can tell the
    user *why* nothing is happening, then finally yields
    {"type": "response", "resp": ...}. It's a generator rather than a callback
    because the caller needs to emit an event mid-retry.

    The free tier allows only ~5 generate requests/minute while one question
    needs several, so 429s mid-run are normal. Honoring the server's retryDelay
    lets the run finish instead of failing — bounded by `budget`.

    `client.models` is looked up at call time so tests can monkeypatch it.
    """
    while True:
        try:
            resp = client.models.generate_content(
                model=settings.GEN_MODEL,
                contents=contents,
                config=_config(),
            )
            yield {"type": "response", "resp": resp}
            return
        except Exception as e:
            msg = str(e)
            if not ("429" in msg or "RESOURCE_EXHAUSTED" in msg):
                raise
            # A *daily* quota won't free up by waiting — it resets at midnight
            # Pacific. Retrying just burns minutes for nothing, so fail fast
            # and say so. Only per-minute limits are worth sleeping on.
            if _PER_DAY_QUOTA_RE.search(msg):
                limit = _QUOTA_LIMIT_RE.search(msg)
                raise DailyQuotaExhausted(
                    "Daily Gemini quota exhausted for model "
                    f"'{settings.GEN_MODEL}'"
                    + (f" (limit: {limit.group(1)} requests/day)" if limit else "")
                    + ". This resets at midnight Pacific — waiting won't help. "
                    "Switch GEN_MODEL in backend/.env to a model with more free "
                    "headroom (e.g. gemini-flash-lite-latest), or enable billing."
                ) from e

            m = _RETRY_AFTER_RE.search(msg)
            wait = min(float(m.group(1)) + 2.0, 60.0) if m else 20.0
            print(f"[agent] rate limited; waiting {wait:.0f}s "
                  f"({budget.remaining:.0f}s of budget left)")
            yield {"type": "waiting", "seconds": round(wait),
                   "budget_left": round(budget.remaining)}
            budget.sleep(wait)


def _generate_with_retry(contents, budget: "_WaitBudget"):
    """Blocking form of _generate_streaming, for the non-streaming /ask path."""
    for event in _generate_streaming(contents, budget):
        if event["type"] == "response":
            return event["resp"]


def iter_agent(dataset_id: str, question: str):
    """Run the agent, yielding progress events as it goes.

    Events are dicts with a "type": "thinking" (a model call is in flight),
    "tool_start"/"tool_end" (a tool is running / finished), "waiting" (sleeping
    off a rate limit), and finally "final" carrying the same payload run_agent
    returns. Streaming these is what lets the UI show what the agent is doing
    instead of an opaque spinner — a single question can take a minute or more
    on the free tier.
    """
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    trace: list[dict] = []
    fig_json = None  # last chart produced by run_python, surfaced in the response

    budget = _WaitBudget(settings.MAX_RATE_LIMIT_WAIT_SECONDS)

    for i in range(settings.MAX_AGENT_ITERATIONS):
        yield {"type": "thinking", "iteration": i + 1}
        resp = None
        try:
            for event in _generate_streaming(contents, budget):
                if event["type"] == "response":
                    resp = event["resp"]
                else:
                    yield event  # surface "waiting" to the client
        except DailyQuotaExhausted as e:
            yield {"type": "final", "payload": {
                "answer": None,
                "error": str(e),
                "quota_exhausted": True,
                "trace": trace,
                "fig_json": fig_json,
                "iterations": i + 1,
                "waited_seconds": round(budget.waited),
            }}
            return
        except RateLimitExhausted as e:
            yield {"type": "final", "payload": {
                "answer": None,
                "error": str(e),
                "rate_limited": True,
                "trace": trace,
                "fig_json": fig_json,
                "iterations": i + 1,
                "waited_seconds": round(budget.waited),
            }}
            return
        except Exception as e:
            yield {"type": "final", "payload": {
                "answer": None,
                "error": f"Model call failed: {type(e).__name__}: {e}",
                "trace": trace,
                "fig_json": fig_json,
                "iterations": i + 1,
                "waited_seconds": round(budget.waited),
            }}
            return

        candidate = resp.candidates[0]
        parts = candidate.content.parts or []
        function_calls = [p.function_call for p in parts if p.function_call is not None]

        if not function_calls:
            yield {"type": "final", "payload": {
                "answer": (resp.text or "").strip(),
                "trace": trace,
                "fig_json": fig_json,
                "iterations": i + 1,
                "waited_seconds": round(budget.waited),
            }}
            return

        # Echo the model's own turn back verbatim (preserves thought_signature).
        contents.append(candidate.content)

        response_parts = []
        for fc in function_calls:
            name = fc.name
            args = dict(fc.args or {})
            yield {"type": "tool_start", "tool": name, "args": args}

            impl = TOOL_IMPLS.get(name)
            if impl is None:
                result = {"error": f"Unknown tool '{name}'."}
            else:
                try:
                    result = impl(dataset_id, **args)
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}

            if name == "run_python" and isinstance(result, dict):
                if result.get("fig_json"):
                    fig_json = result["fig_json"]
                # Don't send the (potentially huge) figure JSON back to the model.
                model_result = {k: v for k, v in result.items() if k != "fig_json"}
                model_result["chart_generated"] = bool(result.get("fig_json"))
            else:
                model_result = result

            step = {"tool": name, "args": args, "result_preview": _preview(model_result)}
            trace.append(step)
            yield {"type": "tool_end", "step": step,
                   "chart": bool(name == "run_python" and fig_json)}

            response_parts.append(
                types.Part.from_function_response(name=name, response=_as_response_dict(model_result))
            )

        contents.append(types.Content(role="user", parts=response_parts))

    yield {"type": "final", "payload": {
        "answer": "I couldn't reach a final answer within the tool-call budget. "
                  "See the trace for what I found so far.",
        "trace": trace,
        "fig_json": fig_json,
        "iterations": settings.MAX_AGENT_ITERATIONS,
        "truncated": True,
        "waited_seconds": round(budget.waited),
    }}


def run_agent(dataset_id: str, question: str) -> dict:
    """Blocking form of iter_agent: drains the events and returns the result."""
    payload: dict = {}
    for event in iter_agent(dataset_id, question):
        if event["type"] == "final":
            payload = event["payload"]
    return payload
