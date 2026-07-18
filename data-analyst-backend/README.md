# AI Data Analyst Agent (backend)

An agentic data-analyst API. Upload a **CSV, Excel, PDF, or DOCX** file, ask a question
in plain English, and a Gemini-powered agent inspects the data, writes and runs **SQL**
and **Python** (pandas + Plotly), and returns an answer, a step-by-step tool trace, and
an interactive chart.

This showcases hand-built **AI agent tool/function calling**, **code execution**, and
**data analysis** — no agent framework (LangChain/LangGraph); the tool-calling loop is
written directly against the Gemini API.

## How it works

1. **Upload** → the file is materialized into a per-dataset **DuckDB** database
   (`data/datasets/<id>.duckdb`) plus a JSON metadata sidecar. Tabular files become
   tables directly; PDFs/DOCX have their tables extracted (falling back to storing text).
2. **Ask** → the agent runs a tool-calling loop over Gemini with four tools:
   - `list_tables` / `get_schema` — inspect the dataset structure
   - `run_sql` — run a read-only DuckDB `SELECT`/`WITH` query
   - `run_python` — run pandas/Plotly code in a subprocess; assign a Plotly figure to
     `fig` to return a chart
   The model chains these autonomously until it produces a final plain-text answer.
3. **Response** → `{answer, trace, fig_json, iterations}`. `trace` is the ordered list
   of tool calls (for a future "thinking" timeline UI); `fig_json` is a Plotly figure
   spec the frontend renders with Plotly.js.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy env_sample.txt .env   # then edit .env with your GOOGLE_API_KEY
uvicorn api:apps --host 0.0.0.0 --port 8091
```

Open http://localhost:8091/docs for the interactive Swagger UI. Port 8091 is chosen so
this can run alongside the sibling RAG backend (port 8090).

### Model note
`GEN_MODEL` must be a function-calling capable Gemini model. The default is
`gemini-flash-latest` — a good fit for an agent, which makes several model calls per
question. The current SDK (`google-genai>=2.12.1`) is **required**: Gemini "thinking"
models attach a `thought_signature` to each function call that must be echoed back on the
next turn, and older SDK versions drop it (causing `400 INVALID_ARGUMENT`). The loop
preserves it by appending the model's own turn content back into history verbatim.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

Tests mock **only** the Gemini boundary (scripted tool-call sequences) and exercise
everything else for real — real DuckDB, real pandas/pdfplumber/python-docx extraction,
and real subprocess execution — so they run fully offline and cost no API quota.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/datasets/upload` | Upload a file (multipart `file`, optional `name`) → new dataset |
| GET | `/datasets/` | List datasets |
| GET | `/datasets/{id}` | Dataset metadata + schema |
| GET | `/datasets/{id}/preview?table=&limit=` | Sample rows |
| DELETE | `/datasets/{id}` | Delete a dataset |
| POST | `/ask` | `{dataset_id, question}` → agent answer + trace + chart |

## Known limitations (be honest — this is a portfolio v1, not hardened for untrusted use)

- **Code execution is NOT sandboxed for security.** `run_python` uses a subprocess with a
  wall-clock timeout and a scoped working directory only. There is **no** filesystem,
  network, or memory isolation (and Windows has no `resource.setrlimit`). Generated code
  runs as your OS user and could read/write your files or make network calls. **Do not
  expose this to untrusted users** without real isolation (Docker/gVisor/Firecracker) —
  planned for the later deployment phase.
- **Prompt-injection surface:** content from uploaded files can reach the model's context
  via tool results. `run_sql` is restricted to a single read-only `SELECT`/`WITH` as a
  partial mitigation, not a full guarantee.
- **PDF/DOCX table extraction is best-effort:** each detected table becomes its own table
  (no cross-page stitching); when no tables are found, text is stored so it's still
  queryable. Scanned/image PDFs won't yield text without OCR (not included).
- **Memory:** Excel/PDF/DOCX ingestion passes through pandas in memory, bounded only by
  `MAX_UPLOAD_MB` (default 50MB); very wide/many-sheet files can still spike memory.
- **Iteration cap:** `MAX_AGENT_ITERATIONS` (default 8) bounds runaway loops; genuinely
  complex analyses may be cut off and are flagged with `truncated: true`.
- **No streaming yet:** `/ask` is synchronous. The `trace` array already captures the tool
  sequence; mid-loop SSE streaming is a planned v2 item.
- **Free-tier quota:** Gemini free tier has low per-minute/per-day request caps; since the
  agent makes several calls per question, a few questions can exhaust a free-tier daily
  quota. Use a billed key for sustained use.
