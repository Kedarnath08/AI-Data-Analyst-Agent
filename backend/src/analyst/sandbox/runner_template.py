"""Template for the script executed in the subprocess sandbox.

The dataset's tables are pre-exported to Parquet and loaded here as pandas
DataFrames named after each table. The model's code runs between the markers.
If it assigns a plotly Figure to `fig`, we serialize it to __result__.json.
"""

RUNNER_TEMPLATE = '''\
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
