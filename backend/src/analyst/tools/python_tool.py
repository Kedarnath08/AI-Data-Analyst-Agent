"""Python execution tool: runs model-generated analysis code in a subprocess.

SECURITY: this is a wall-clock timeout + a scoped working directory ONLY. It is
NOT a security boundary — the child runs as the same OS user with full disk and
network access, and memory is not capped (no resource.setrlimit on Windows).
Do not expose to untrusted users without real isolation (Docker/gVisor). See README.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from src.analyst import duck
from src.config import settings
from src.analyst.sandbox.runner_template import RUNNER_TEMPLATE

SANDBOX_ROOT = Path("data/uploads/_sandbox")


def _safe_var(display_name: str, used: set[str]) -> str:
    """Turn a table display name into a valid, unique Python identifier.

    File datasets give plain names ("data"); live-DB datasets give qualified
    names ("public.users") which can't be used as variables as-is.
    """
    base = re.sub(r"\W+", "_", display_name.split(".")[-1]).strip("_").lower()
    if not base or base[0].isdigit():
        base = f"t_{base}" if base else "table"
    name = base
    i = 2
    while name in used:
        name = f"{base}_{i}"
        i += 1
    used.add(name)
    return name


def _prepare_sandbox(dataset_id: str, workdir: Path) -> dict[str, str]:
    """Export each dataset table to Parquet inside workdir.

    Returns {python_var_name: parquet_path}. Works for both file-backed and
    live-DB datasets (duck.list_tables / duck.sql_ref are kind-aware).
    """
    con = duck.connect(dataset_id, read_only=True)
    paths: dict[str, str] = {}
    used: set[str] = set()
    try:
        for display in duck.list_tables(dataset_id):
            var = _safe_var(display, used)
            p = workdir / f"{var}.parquet"
            # COPY TO requires a string-literal path (no '?' params). The path is
            # a controlled temp path; escape single quotes defensively anyway.
            escaped = str(p).replace("'", "''")
            con.execute(
                f"COPY {duck.sql_ref(display)} TO '{escaped}' (FORMAT PARQUET)"
            )
            paths[var] = str(p)
    finally:
        con.close()
    return paths


def _restricted_env() -> dict:
    """Minimal env for the child — strips app secrets like GOOGLE_API_KEY.

    Note: this is defense-in-depth only; it does not sandbox the filesystem
    or network.
    """
    import os

    keep = {}
    for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT",
              "PYTHONHASHSEED", "LANG", "LC_ALL"):
        if k in os.environ:
            keep[k] = os.environ[k]
    return keep


def run_python(dataset_id: str, code: str) -> dict:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="dabx_", dir=str(SANDBOX_ROOT)))
    try:
        table_paths = _prepare_sandbox(dataset_id, workdir)
        table_loads = "\n".join(
            f'{table} = pd.read_parquet(r"{path}")'
            for table, path in table_paths.items()
        )
        script = RUNNER_TEMPLATE.format(
            table_loads=table_loads,
            user_code=code,
            mem_bytes=settings.PY_MAX_MEMORY_MB * 1024 * 1024,
            cpu_seconds=settings.PY_MAX_CPU_SECONDS,
            fsize_bytes=settings.PY_MAX_WRITE_MB * 1024 * 1024,
        )
        (workdir / "run.py").write_text(script, encoding="utf-8")

        try:
            proc = subprocess.run(
                [sys.executable, "run.py"],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=settings.PY_TIMEOUT_SECONDS,
                env=_restricted_env(),
            )
        except subprocess.TimeoutExpired:
            return {"error": f"Execution timed out after {settings.PY_TIMEOUT_SECONDS}s"}

        limit = settings.PY_MAX_OUTPUT_CHARS
        stdout = (proc.stdout or "")[-limit:]
        stderr = (proc.stderr or "")[-limit:]

        fig_json = None
        result_file = workdir / "__result__.json"
        if result_file.exists():
            try:
                fig_json = json.loads(result_file.read_text(encoding="utf-8")).get("fig_json")
            except Exception:
                fig_json = None

        return {
            "stdout": stdout,
            "stderr": stderr if proc.returncode != 0 else "",
            "return_code": proc.returncode,
            "fig_json": fig_json,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
