"""The agentic tool-calling loop over Gemini native function calling.

IMPORTANT (verified against the live API): gemini-3-flash-preview is a thinking
model. Each function_call part carries a `thought_signature` that MUST be sent
back on the next request or the API returns 400 INVALID_ARGUMENT. We preserve it
by appending the model's own `candidate.content` back into the history VERBATIM —
never reconstruct the model turn from scratch. This requires google-genai>=2.12.1.
"""
from typing import Any

from google import genai
from google.genai import types

from src.config import settings
from src.tools import python_tool, schema_tools, sql_tool

client = genai.Client(api_key=settings.GOOGLE_API_KEY)

SYSTEM_PROMPT = (
    "You are an expert data analyst agent working with a single dataset stored in "
    "DuckDB. You have tools to inspect the schema, run read-only SQL, and run Python "
    "(pandas + plotly are available). \n"
    "- If you don't know the table/column names, call list_tables and get_schema first.\n"
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
                "table is preloaded as a pandas DataFrame named after the table. Assign a plotly "
                "Figure to `fig` to return a chart. print() any textual results you want back."
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


def run_agent(dataset_id: str, question: str) -> dict:
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    trace: list[dict] = []
    fig_json = None  # last chart produced by run_python, surfaced in the HTTP response

    for i in range(settings.MAX_AGENT_ITERATIONS):
        try:
            resp = client.models.generate_content(
                model=settings.GEN_MODEL,
                contents=contents,
                config=_config(),
            )
        except Exception as e:
            return {
                "answer": None,
                "error": f"Model call failed: {type(e).__name__}: {e}",
                "trace": trace,
                "fig_json": fig_json,
                "iterations": i + 1,
            }
        candidate = resp.candidates[0]
        parts = candidate.content.parts or []
        function_calls = [p.function_call for p in parts if p.function_call is not None]

        if not function_calls:
            return {
                "answer": (resp.text or "").strip(),
                "trace": trace,
                "fig_json": fig_json,
                "iterations": i + 1,
            }

        # Echo the model's own turn back verbatim (preserves thought_signature).
        contents.append(candidate.content)

        response_parts = []
        for fc in function_calls:
            name = fc.name
            args = dict(fc.args or {})
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

            trace.append({"tool": name, "args": args, "result_preview": _preview(model_result)})
            response_parts.append(
                types.Part.from_function_response(name=name, response=_as_response_dict(model_result))
            )

        contents.append(types.Content(role="user", parts=response_parts))

    return {
        "answer": "I couldn't reach a final answer within the tool-call budget. "
                  "See the trace for what I found so far.",
        "trace": trace,
        "fig_json": fig_json,
        "iterations": settings.MAX_AGENT_ITERATIONS,
        "truncated": True,
    }
