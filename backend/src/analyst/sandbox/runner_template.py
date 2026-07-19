"""Template for the script executed in the subprocess sandbox.

The dataset's tables are pre-exported to Parquet and loaded here as pandas
DataFrames named after each table. The model's code runs between the markers.
If it assigns a plotly Figure to `fig`, we serialize it to __result__.json.

Resource limits are applied *inside* the child, as the very first thing it
does, rather than via subprocess(preexec_fn=...) — preexec_fn is documented as
unsafe when the parent has threads, and FastAPI runs sync endpoints in a
threadpool. Setting both the soft and hard limit means the model's code cannot
raise them back afterwards. rlimits only exist on Unix, so this is a no-op on
Windows (see README: the strong sandbox is the containerized Linux deployment).
"""

RUNNER_TEMPLATE = '''\
# --- resource limits (applied before any model code runs) ---
try:
    import resource as _resource

    _MEM_BYTES = {mem_bytes}
    _CPU_SECONDS = {cpu_seconds}
    _FSIZE_BYTES = {fsize_bytes}

    if _MEM_BYTES > 0:
        _resource.setrlimit(_resource.RLIMIT_AS, (_MEM_BYTES, _MEM_BYTES))
    if _CPU_SECONDS > 0:
        _resource.setrlimit(_resource.RLIMIT_CPU, (_CPU_SECONDS, _CPU_SECONDS))
    if _FSIZE_BYTES > 0:
        _resource.setrlimit(_resource.RLIMIT_FSIZE, (_FSIZE_BYTES, _FSIZE_BYTES))
    _resource.setrlimit(_resource.RLIMIT_CORE, (0, 0))
except Exception:
    # Not available on this platform (e.g. Windows); the wall-clock timeout in
    # the parent still applies.
    pass

import json
import pandas as pd

pd.set_option("display.max_rows", 20)
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 200)

{table_loads}

fig = None

# ---- BEGIN MODEL CODE ----
{user_code}
# ---- END MODEL CODE ----

_out = {{"fig_json": None}}
try:
    if fig is not None and hasattr(fig, "to_json"):
        _out["fig_json"] = fig.to_json()
except Exception as _e:
    _out["fig_error"] = "{{}}: {{}}".format(type(_e).__name__, _e)

with open("__result__.json", "w", encoding="utf-8") as _f:
    json.dump(_out, _f)
'''
