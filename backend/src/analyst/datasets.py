"""Dataset CRUD: upload -> DuckDB, list/get/preview/delete.

A "dataset" is one uploaded file materialized as one DuckDB database file,
with a JSON sidecar catalog (data/datasets/<id>.meta.json). This mirrors the
sibling RAG backend's collections router, but with real CRUD since DuckDB
files are concrete local artifacts.
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.analyst import duck
from src.analyst.db_connect import SUPPORTED_ENGINES, test_and_introspect
from src.config import settings
from src.analyst.ingest import SUPPORTED_EXTENSIONS, ingest_file

router = APIRouter(prefix="/datasets", tags=["datasets"])

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _write_meta(dataset_id: str, meta: dict) -> None:
    duck.meta_path(dataset_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _read_meta(dataset_id: str) -> dict | None:
    p = duck.meta_path(dataset_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _public_meta(meta: dict) -> dict:
    """Strip secrets before returning dataset metadata over the API."""
    if not isinstance(meta, dict) or "connection" not in meta:
        return meta
    safe = dict(meta)
    conn = dict(safe.get("connection") or {})
    if conn.get("password"):
        conn["password"] = "***"
    safe["connection"] = conn
    return safe


@router.get("/")
def list_datasets():
    datasets = []
    for meta_file in sorted(duck.DATASETS_DIR.glob("*.meta.json")):
        try:
            datasets.append(_public_meta(json.loads(meta_file.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return {"datasets": datasets}


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(..., description="CSV, Excel, PDF, or DOCX file"),
    name: str | None = Form(None, description="Optional friendly dataset name"),
):
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    content = await file.read()
    if not content or len(content) < 10:
        raise HTTPException(400, "Uploaded file appears empty.")
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(400, f"File too large (max {settings.MAX_UPLOAD_MB}MB).")

    dataset_id = uuid4().hex[:12]
    upload_subdir = UPLOAD_DIR / dataset_id
    upload_subdir.mkdir(parents=True, exist_ok=True)
    dest = upload_subdir / filename
    dest.write_bytes(content)

    try:
        result = ingest_file(dataset_id, dest)
    except Exception as e:
        # Clean up partial artifacts so a failed upload leaves nothing behind.
        _cleanup(dataset_id)
        raise HTTPException(
            400, f"Ingestion failed: {type(e).__name__}: {e}"
        )

    meta = {
        "id": dataset_id,
        "name": name or filename,
        "source_filename": filename,
        "file_type": ext.lstrip("."),
        "extraction_method": result.get("extraction_method"),
        "tables": result["tables"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_meta(dataset_id, meta)
    return {"dataset_id": dataset_id, "name": meta["name"], "tables": result["tables"]}


class ConnectDbIn(BaseModel):
    engine: str                       # postgres | mysql | sqlite
    name: str | None = None           # friendly dataset name
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None
    database: str | None = None       # db name (or file path for sqlite)


@router.post("/connect_db")
def connect_database(body: ConnectDbIn):
    """Register a live external database as a dataset.

    The connection is opened READ_ONLY via DuckDB's ATTACH, verified, and its
    schema introspected. Credentials are stored in the dataset's gitignored
    meta.json in plaintext — acceptable for local use, not for production.
    """
    engine = (body.engine or "").lower()
    if engine not in SUPPORTED_ENGINES:
        raise HTTPException(
            400, f"Unsupported engine '{body.engine}'. Supported: {sorted(SUPPORTED_ENGINES)}"
        )

    connection = {
        "engine": engine,
        "host": body.host,
        "port": body.port,
        "user": body.user,
        "password": body.password,
        "database": body.database,
    }

    try:
        schema = test_and_introspect(connection)
    except Exception as e:
        raise HTTPException(400, f"Could not connect: {type(e).__name__}: {e}")

    if not schema:
        raise HTTPException(400, "Connected, but no user tables were found in that database.")

    tables = [
        {"name": t, "row_count": None, "columns": cols}
        for t, cols in schema.items()
    ]

    dataset_id = uuid4().hex[:12]
    label = body.name or f"{engine}:{body.database or ''}"
    meta = {
        "id": dataset_id,
        "name": label,
        "kind": "database",
        "engine": engine,
        "connection": connection,
        "tables": tables,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_meta(dataset_id, meta)
    return {"dataset_id": dataset_id, "name": label, "engine": engine, "tables": tables}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str):
    meta = _read_meta(dataset_id)
    if meta is None or not duck.exists(dataset_id):
        raise HTTPException(404, "Dataset not found")
    return {**_public_meta(meta), "schema": duck.get_schema(dataset_id)}


@router.get("/{dataset_id}/preview")
def preview_dataset(dataset_id: str, table: str | None = None, limit: int = 50):
    if not duck.exists(dataset_id):
        raise HTTPException(404, "Dataset not found")
    tables = duck.list_tables(dataset_id)
    if not tables:
        raise HTTPException(404, "Dataset has no tables.")
    target = table or tables[0]
    if target not in tables:
        raise HTTPException(404, f"Table '{target}' not found in dataset.")
    limit = max(1, min(500, limit))
    con = duck.connect(dataset_id, read_only=True)
    try:
        cur = con.execute(f"SELECT * FROM {duck.sql_ref(target)} LIMIT {limit}")
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        con.close()
    return {"table": target, "columns": columns, "rows": rows, "row_count": len(rows)}


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str):
    if not duck.exists(dataset_id) and _read_meta(dataset_id) is None:
        raise HTTPException(404, "Dataset not found")
    _cleanup(dataset_id)
    return {"ok": True}


def _cleanup(dataset_id: str) -> None:
    duck.db_path(dataset_id).unlink(missing_ok=True)
    duck.meta_path(dataset_id).unlink(missing_ok=True)
    shutil.rmtree(UPLOAD_DIR / dataset_id, ignore_errors=True)
