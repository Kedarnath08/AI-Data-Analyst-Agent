"""PDF ingestion: extract tables with pdfplumber, fall back to page text.

Kept intentionally simple: each table pdfplumber finds becomes its own DuckDB
table (no cross-page stitching). When no tables are found, page text is stored
as a document_text(page, text) table so the agent can still query the content.
"""
from pathlib import Path

import pandas as pd
import pdfplumber

from src.analyst import duck
from src.analyst.ingest import _describe, _dedupe_cols, _safe_col
from src.analyst.ingest.tabular import _load_df


def ingest_pdf(dataset_id: str, path: Path) -> dict:
    extracted: list[tuple[int, list[list]]] = []
    page_texts: list[tuple[int, str]] = []
    with pdfplumber.open(path) as doc:
        for page_num, page in enumerate(doc.pages, start=1):
            for raw in page.extract_tables() or []:
                if raw and len(raw) > 1:
                    extracted.append((page_num, raw))
            page_texts.append((page_num, page.extract_text() or ""))

    con = duck.connect(dataset_id)
    tables = []
    try:
        if extracted:
            for i, (page_num, raw) in enumerate(extracted):
                header, *body = raw
                cols = _dedupe_cols(
                    [_safe_col(h, j) for j, h in enumerate(header)]
                )
                df = pd.DataFrame(body, columns=cols)
                table = f"table_{i + 1}_p{page_num}"
                _load_df(con, table, df)
                tables.append(_describe(con, table))
            method = "pdfplumber_tables"
        else:
            df = pd.DataFrame(
                {"page": [p for p, _ in page_texts],
                 "text": [t for _, t in page_texts]}
            )
            _load_df(con, "document_text", df)
            tables.append(_describe(con, "document_text"))
            method = "text_fallback"
    finally:
        con.close()
    return {"tables": tables, "extraction_method": method}
