"""CSV and Excel ingestion into a dataset's DuckDB file."""
from pathlib import Path

import pandas as pd

from src import duck
from src.ingest import _describe, _dedupe_cols, _safe_col, _safe_table_name


def ingest_csv(dataset_id: str, path: Path) -> dict:
    con = duck.connect(dataset_id)
    try:
        # DuckDB's native reader streams and infers types without loading the
        # whole file into a pandas frame first. sample_size=-1 scans the full
        # file for robust type inference on messy CSVs.
        con.execute(
            "CREATE OR REPLACE TABLE data AS "
            "SELECT * FROM read_csv_auto(?, sample_size=-1)",
            [str(path)],
        )
        table_info = _describe(con, "data")
    finally:
        con.close()
    return {"tables": [table_info], "extraction_method": "duckdb_read_csv"}


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
