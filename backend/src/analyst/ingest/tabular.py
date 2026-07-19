"""CSV and Excel ingestion into a dataset's DuckDB file."""
from pathlib import Path

import pandas as pd

from src.analyst import duck
from src.analyst.ingest import _describe, _dedupe_cols, _safe_col, _safe_table_name


# Tried in order when DuckDB can't decode the file. DuckDB's CSV reader is
# UTF-8 only, but real-world CSVs (Kaggle exports, anything out of Excel on
# Windows) are frequently cp1252/latin-1. latin-1 maps every byte, so it always
# succeeds — it's the last resort rather than a guess.
_FALLBACK_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _is_encoding_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "unicode" in msg or "byte sequence" in msg or "encoding" in msg


def ingest_csv(dataset_id: str, path: Path) -> dict:
    con = duck.connect(dataset_id)
    try:
        try:
            # DuckDB's native reader streams and infers types without loading the
            # whole file into a pandas frame first. sample_size=-1 scans the full
            # file for robust type inference on messy CSVs.
            con.execute(
                "CREATE OR REPLACE TABLE data AS "
                "SELECT * FROM read_csv_auto(?, sample_size=-1)",
                [str(path)],
            )
            method = "duckdb_read_csv"
        except Exception as e:
            if not _is_encoding_error(e):
                raise
            df, used = _read_csv_any_encoding(path)
            _load_df(con, "data", df)
            method = f"pandas_{used}"
        table_info = _describe(con, "data")
    finally:
        con.close()
    return {"tables": [table_info], "extraction_method": method}


def _read_csv_any_encoding(path: Path) -> tuple[pd.DataFrame, str]:
    """Decode a non-UTF-8 CSV by trying likely encodings in turn."""
    last: Exception | None = None
    for enc in _FALLBACK_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc), enc
        except (UnicodeDecodeError, LookupError) as e:
            last = e
    raise ValueError(
        f"Could not decode CSV with any of {_FALLBACK_ENCODINGS}: {last}"
    )


def _load_df(con, table: str, df: pd.DataFrame) -> None:
    con.register("tmp_df", df)
    try:
        con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM tmp_df')
    finally:
        con.unregister("tmp_df")


def ingest_excel(dataset_id: str, path: Path) -> dict:
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    con = duck.connect(dataset_id)
    tables = []
    try:
        used_names: set[str] = set()
        for i, (sheet_name, df) in enumerate(sheets.items()):
            if df is None or df.empty:
                continue
            df = _normalize_df_columns(df)
            table = _safe_table_name(sheet_name, i)
            while table in used_names:
                table = f"{table}_x"
            used_names.add(table)
            _load_df(con, table, df)
            tables.append(_describe(con, table))
        if not tables:
            raise ValueError("Excel file has no non-empty sheets.")
    finally:
        con.close()
    return {"tables": tables, "extraction_method": "pandas_openpyxl"}


def _normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = _dedupe_cols([_safe_col(c, i) for i, c in enumerate(df.columns)])
    df = df.copy()
    df.columns = cols
    return df
