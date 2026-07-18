# Project Overview — AI Data Analyst Agent + RAG Chatbot

One project, two AI workspaces behind a single UI and a single backend:

- **📄 Document Chat (RAG)** — upload PDFs, ask questions, get streamed answers grounded in
  your documents with citations back to chunk and page.
- **📊 Data Analyst (agentic)** — upload a CSV/Excel/PDF/DOCX *or* connect a live
  Postgres/MySQL/SQLite database, ask in plain English, and an agent writes and runs SQL and
  Python (pandas/Plotly) to answer, returning charts plus a trace of every step it took.

```
AI Data Analyst Agent/
├── backend/       # one FastAPI app serving both capabilities (port 8090)
└── AI-agent-UI/   # one Next.js app with a mode switch between the two (port 3000)
```

---

## Backend — `backend/`

Single FastAPI app (`api.py`, app object `apps`), one virtualenv, one port:

```powershell
cd backend
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy env_sample.txt .env      # add your keys
uvicorn api:apps --host 0.0.0.0 --port 8090
```

Swagger: http://localhost:8090/docs · Tests: `pip install -r requirements-dev.txt && pytest`

### Structure

```
backend/
├── api.py                  # mounts all routers; /ask, /health
├── scripts/
│   └── reingest_collections.py   # rebuild Pinecone namespaces after a model change
└── src/
    ├── config.py           # merged settings (one GOOGLE_API_KEY / GEN_MODEL)
    ├── cors.py             # shared CORS (allows the UI on :3000)
    ├── rag/                # Document Chat
    │   ├── routes.py       #   /ingest, /ingest_text, /query, /query_stream (SSE)
    │   ├── collections.py  #   /collections (Pinecone namespaces)
    │   ├── vectors.py      #   Gemini embeddings + Pinecone, with 429 retry/backoff
    │   ├── pdf.py chunk.py #   per-page extraction, overlapping chunking
    │   └── llm.py          #   context-only answering + true token streaming
    └── analyst/            # Data Analyst
        ├── datasets.py     #   /datasets CRUD + /datasets/connect_db
        ├── duck.py         #   DuckDB helpers, kind-aware (file vs live DB)
        ├── db_connect.py   #   Postgres/MySQL/SQLite ATTACH (READ_ONLY)
        ├── llm.py          #   the tool-calling agent loop
        ├── ingest/         #   csv/excel (tabular), pdf_tables, docx_tables
        ├── tools/          #   list_tables, get_schema, run_sql, run_python
        └── sandbox/        #   subprocess runner template
```

### How the analyst agent works

1. A dataset is either an uploaded file materialized into a **DuckDB file**, or a **live
   database attached READ_ONLY** via DuckDB's `ATTACH` (so the agent can never write to it).
2. `POST /ask` runs a hand-rolled **Gemini native function-calling loop**: the model picks
   tools (`list_tables` → `get_schema` → `run_sql` / `run_python`), the backend executes them
   and feeds results back, until the model answers in plain text.
3. `run_sql` is restricted to a single read-only `SELECT`/`WITH`, row-capped.
4. `run_python` exports the dataset's tables to Parquet into a temp dir and runs the model's
   code in a **subprocess with a wall-clock timeout**; a Plotly figure assigned to `fig` comes
   back as JSON and is rendered in the UI.
5. The response carries `answer`, `fig_json`, and a `trace` of every tool call — the UI shows
   the trace under "How I got this".

> **Gemini SDK note:** requires `google-genai>=2.12.1`. Thinking models attach a
> `thought_signature` to each function call that must be echoed back across turns; older SDKs
> drop it and the multi-turn tool loop fails. The loop appends the model's own `content`
> verbatim to preserve it.

### Key endpoints

| Purpose | Endpoint |
|---|---|
| Ingest PDFs / raw text | `POST /ingest`, `POST /ingest_text` |
| Ask a document question | `POST /query`, `POST /query_stream` (SSE) |
| Manage RAG collections | `GET/POST /collections/`, `DELETE /collections/{name}` |
| Upload a dataset | `POST /datasets/upload` |
| Connect a live database | `POST /datasets/connect_db` |
| Inspect / preview / delete | `GET /datasets/{id}`, `.../preview`, `DELETE /datasets/{id}` |
| Ask an analyst question | `POST /ask` |

---

## Frontend — `AI-agent-UI/`

Next.js 15 (App Router, React 19), CSS Modules, Plotly for charts.

```powershell
cd AI-agent-UI
npm install
npm run dev     # http://localhost:3000
```

- `src/app/page.js` — thin shell owning theme / sidebar / active mode.
- `src/components/ModeTabs.js` — the Document Chat ↔ Data Analyst switch.
- `src/components/DocumentChat.js` — RAG chat: streaming answers, citation chips,
  collection management, drag-and-drop PDF ingest, `top_k` / `sim_threshold` controls.
- `src/components/DataAnalyst.js` — analyst chat: Plotly charts, expandable tool-call trace,
  friendly handling of quota/key/model errors.
- `src/components/DatasetManager.js` — upload a file or connect a database; select/delete.
- `src/utils/` — `collections.js` (RAG), `datasets.js` (analyst).

Config: `.env.local` → `NEXT_PUBLIC_API_BASE=http://localhost:8090`

---

## Testing

`pytest` from `backend/` — 37 tests. Only the external boundaries (Gemini, Pinecone) are
mocked; DuckDB, file extraction, SQL, and the Python subprocess all run for real, so the suite
runs offline and costs no API quota. Live-database behavior is covered via SQLite, which
exercises the identical ATTACH code path as Postgres/MySQL without needing a server.

---

## Known limitations (deliberate, documented)

- **`run_python` is not a security sandbox.** Subprocess + timeout + scoped working directory
  only — no filesystem, network, or memory isolation (and no `resource.setrlimit` on Windows).
  Not safe for untrusted users; real isolation is the next phase (Docker).
- **Live-DB credentials** are stored in plaintext in the dataset's gitignored `meta.json`
  (redacted in API responses). Use a dedicated read-only DB user; move to a secret store
  before any real deployment.
- **Prompt injection**: uploaded content reaches the model. Partial mitigations: read-only SQL
  guard, execution timeout, READ_ONLY database attach.
- **Gemini free tier is tight** — the agent makes several model calls per question, and
  embedding is capped at ~100 requests/minute (ingestion retries with backoff). Use a billed
  key for sustained use.
- Changing `EMBED_MODEL` invalidates existing Pinecone vectors (different vector space);
  rebuild them with `scripts/reingest_collections.py`.

## Next up

Docker packaging and deployment — which also gives `run_python` a real isolation boundary.
