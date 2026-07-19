"""read-only SQL execution tool exposed to the agent.

Rejects anything that isn't a single SELECT/WITH statement. This is a cheap
guard against the agent (or prompt-injected file content) issuing writes/DDL —
not a full SQL firewall, but it keeps the tool read-only in practice.
"""
import datetime
import decimal
import re

from src.analyst import duck
from src.config import settings

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _strip_comments(sql: str) -> str:
    sql = _COMMENT_RE.sub(" ", sql)
    sql = _LINE_COMMENT_RE.sub(" ", sql)
    return sql.strip()


def _is_read_only(sql: str) -> bool:
    cleaned = _strip_comments(sql).strip().rstrip(";").strip()
    if not cleaned:
        return False
    # Disallow multiple statements.
    if ";" in cleaned:
        return False
    first = cleaned.split(None, 1)[0].lower()
    return first in ("select", "with")


def run_sql(dataset_id: str, query: str) -> dict:
    if not _is_read_only(query):
        return {
            "error": "Only a single read-only SELECT/WITH query is allowed.",
        }
    con = duck.connect(dataset_id, read_only=True)
    try:
        cur = con.execute(query)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(settings.SQL_ROW_LIMIT + 1)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        con.close()

    truncated = len(rows) > settings.SQL_ROW_LIMIT
    rows = rows[: settings.SQL_ROW_LIMIT]
    return {
        "columns": columns,
        "rows": [[_json_safe(v) for v in r] for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


def _json_safe(value):
    """Coerce DuckDB values into something JSON-serializable.

    Query results flow into SSE frames (plain json.dumps) and into the model's
    function_response, and DuckDB happily returns date/datetime/Decimal/UUID —
    none of which json.dumps handles. Dates become ISO strings, which is also
    the clearest form for the model to reason about.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)
