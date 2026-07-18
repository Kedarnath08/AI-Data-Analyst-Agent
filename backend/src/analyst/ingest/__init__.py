"""Ingestion dispatch: an uploaded file -> DuckDB tables in the dataset's db.

Each ingest_* function returns {"tables": [ {name, row_count, columns}, ... ],
"extraction_method": str}. Column/table identifiers coming from files are always
sanitized (see _safe_col / _safe_table_name) before being used in SQL.
"""
import re
from pathlib import Path

import duckdb

from src.analyst import duck


def ingest_file(dataset_id: str, path: Path) -> dict:
    """Dispatch on file extension. Raises ValueError for unsupported types."""
    from src.analyst.ingest import tabular, pdf_tables, docx_tables

    ext = path.suffix.lower()
    if ext == ".csv":
        return tabular.ingest_csv(dataset_id, path)
    if ext in (".xlsx", ".xls"):
        return tabular.ingest_excel(dataset_id, path)
    if ext == ".pdf":
        return pdf_tables.ingest_pdf(dataset_id, path)
    if ext == ".docx":
        return docx_tables.ingest_docx(dataset_id, path)
    raise ValueError(f"Unsupported file type: {ext}")


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf", ".docx"}


def _safe_table_name(raw: str, fallback_index: int = 0) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", (raw or "").strip().lower()).strip("_")
    if not name or name[0].isdigit():
        name = f"table_{fallback_index + 1}" if not name else f"t_{name}"
    return name[:63]


def _safe_col(raw, index: int) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", str(raw or "").strip().lower()).strip("_")
    if not name or name[0].isdigit():
        name = f"col_{index + 1}" if not name else f"c_{name}"
    return name[:63]


def _dedupe_cols(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 1
            out.append(c)
    return out


def _describe(con: duckdb.DuckDBPyConnection, table: str) -> dict:
    row_count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return {
        "name": table,
        "row_count": row_count,
        "columns": [{"name": c, "type": t} for c, t in cols],
    }
