# AI Data Analyst Agent + RAG Chatbot

**🔗 Live demo:** https://ai-data-analyst-agent-1-nxxa.onrender.com/
> Free-tier hosting: the first request after a period of inactivity can take 30-60s to wake up,
> and uploaded datasets don't persist across a redeploy/restart. No authentication — don't upload
> anything sensitive.

Two AI workspaces behind one UI and one backend:

- **📊 Data Analyst** — upload a CSV/Excel/PDF/DOCX *or* connect a live Postgres/MySQL/SQLite
  database, ask a question in plain English, and an agent writes and executes SQL and Python
  (pandas/Plotly) to answer it — returning charts plus a step-by-step trace of everything it ran.
- **📄 Document Chat (RAG)** — upload PDFs and ask questions, getting streamed answers grounded
  in the documents with citations back to the source file and page.

Built to demonstrate **AI agents, native tool/function calling, sandboxed code execution,
retrieval-augmented generation, and data analysis** — with the agent loop hand-written against
the Gemini API rather than wrapped in a framework.

```
├── backend/       # one FastAPI app serving both capabilities   (port 8090)
├── AI-agent-UI/   # one Next.js app with a mode switch          (port 3000)
└── sample-data/   # small files to try it with
```

---

## Quick start

You need **Python 3.12+**, **Node 20+**, a **Google AI (Gemini) API key**, and — for Document
Chat only — a **Pinecone** account. Both have free tiers.

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows (PowerShell: .\.venv\Scripts\Activate.ps1)
# source .venv/bin/activate      # macOS / Linux
pip install -r requirements.txt

cp env_sample.txt .env           # then add your keys
uvicorn api:apps --host 0.0.0.0 --port 8090
```

> On Windows, if activation is fiddly, skip it entirely:
> `.venv\Scripts\python.exe -m uvicorn api:apps --port 8090`

### 2. Frontend

```bash
cd AI-agent-UI
npm install
npm run dev
```

Open **http://localhost:3000**. API docs are at **http://localhost:8090/docs**.

### 3. Try it

Upload `sample-data/sales.csv` in **Data Analyst** mode and ask:

> *What is total revenue by region? Show a bar chart.*

Then expand **"How I got this"** to see the SQL and Python the agent actually ran.

`sample-data/` also has `company.xlsx` (two sheets → two tables, good for testing a join) and
`quarterly.docx` (a Word table).

---

## How the analyst agent works

1. An uploaded file is materialized into a **DuckDB** database; a live database is instead
   attached **read-only** via DuckDB's `ATTACH`, so the agent can never write to your data.
2. `POST /ask` runs a hand-rolled **Gemini function-calling loop**. The model picks tools —
   `list_tables` → `get_schema` → `run_sql` / `run_python` — the backend executes them and feeds
   results back, until the model produces a final answer.
3. `run_sql` is restricted to a single read-only `SELECT`/`WITH`, row-capped.
4. `run_python` exports the tables to Parquet in a temp directory and runs the model's code in a
   **subprocess with a timeout and resource limits**. A Plotly figure assigned to `fig` is
   returned as JSON and rendered in the UI.
5. `POST /ask_stream` streams the agent's progress as SSE, so the UI shows each step live
   instead of an opaque spinner.

> **Gemini SDK note:** requires `google-genai>=2.12.1`. Thinking models attach a
> `thought_signature` to every function call that must be echoed back on subsequent turns; older
> SDKs drop it and the multi-turn tool loop fails outright. The loop appends the model's own
> `content` verbatim to preserve it.

### Choosing a model

`GEN_MODEL` in `backend/.env` serves both the agent and RAG generation. **Model choice matters
more than it looks** — free-tier quotas vary wildly, and an agent makes several calls per
question:

| Model | Free-tier reality |
|---|---|
| `gemini-flash-lite-latest` | **Recommended.** Enough headroom for agent loops |
| `gemini-flash-latest` | Only ~20 requests/**day** — exhausted in ~3 questions |

If answers stop with a quota message, switch models or enable billing.

---

## Architecture

```
backend/
├── api.py                  # mounts all routers; /ask, /ask_stream, /health
├── scripts/
│   └── reingest_collections.py   # rebuild Pinecone namespaces after a model change
└── src/
    ├── config.py           # merged settings (one GOOGLE_API_KEY / GEN_MODEL)
    ├── cors.py
    ├── rag/                # Document Chat
    │   ├── routes.py       #   /ingest, /ingest_text, /query, /query_stream (SSE)
    │   ├── collections.py  #   /collections (Pinecone namespaces)
    │   ├── vectors.py      #   Gemini embeddings + Pinecone, with 429 backoff
    │   ├── pdf.py chunk.py #   per-page extraction, overlapping chunking
    │   └── llm.py          #   context-only answering + token streaming
    └── analyst/            # Data Analyst
        ├── datasets.py     #   /datasets CRUD + /datasets/connect_db
        ├── duck.py         #   DuckDB helpers, kind-aware (file vs live DB)
        ├── db_connect.py   #   Postgres/MySQL/SQLite ATTACH (READ_ONLY)
        ├── llm.py          #   the tool-calling agent loop
        ├── ingest/         #   csv/excel, pdf_tables, docx_tables
        ├── tools/          #   list_tables, get_schema, run_sql, run_python
        └── sandbox/        #   subprocess runner template

AI-agent-UI/src/
├── app/page.js             # shell: theme, sidebar, active mode
├── components/
│   ├── ModeTabs.js         # Document Chat ↔ Data Analyst
│   ├── DocumentChat.js     # RAG chat: streaming, citations, collections
│   ├── DataAnalyst.js      # analyst chat: live progress, charts, tool trace
│   ├── DatasetManager.js   # upload a file or connect a database
│   ├── DataPreview.js      # sample rows + column types
│   └── SuggestedQuestions.js
└── utils/                  # collections.js (RAG), datasets.js (analyst)
```

### Key endpoints

| Purpose | Endpoint |
|---|---|
| Ingest PDFs / raw text | `POST /ingest`, `POST /ingest_text` |
| Ask a document question | `POST /query`, `POST /query_stream` (SSE) |
| Manage RAG collections | `GET/POST /collections/`, `DELETE /collections/{name}` |
| Upload a dataset | `POST /datasets/upload` |
| Connect a live database | `POST /datasets/connect_db` |
| Inspect / preview / delete | `GET /datasets/{id}`, `.../preview`, `DELETE /datasets/{id}` |
| Ask an analyst question | `POST /ask`, `POST /ask_stream` (SSE) |

### Connecting a live database

```json
POST /datasets/connect_db
{ "engine": "postgres", "name": "Prod replica", "host": "localhost",
  "port": 5432, "user": "readonly", "password": "...", "database": "shop" }
```

Attached via DuckDB `ATTACH ... (READ_ONLY)`, so the agent can never write to it. Tables appear
schema-qualified (`public.orders`); in `run_python` each becomes a DataFrame named after the
table (`orders`). For SQLite, pass the file path as `database`.

---

## Configuration

All backend settings live in `backend/.env` (see `env_sample.txt`):

| Setting | Default | Purpose |
|---|---|---|
| `GEN_MODEL` | `gemini-flash-lite-latest` | Agent + RAG generation |
| `EMBED_MODEL` | `gemini-embedding-001` | RAG embeddings |
| `TOP_K` / `SIM_THRESHOLD` | `8` / `0.5` | Retrieval breadth / strictness |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `900` / `300` | PDF chunking |
| `MAX_AGENT_ITERATIONS` | `8` | Tool-call budget per question |
| `SQL_ROW_LIMIT` | `200` | Rows returned to the model |
| `PY_TIMEOUT_SECONDS` | `20` | Sandbox wall-clock limit |
| `PY_MAX_MEMORY_MB` / `PY_MAX_CPU_SECONDS` | `2048` / `20` | Sandbox rlimits (Unix) |
| `MAX_RATE_LIMIT_WAIT_SECONDS` | `180` | Total wait on API rate limits |
| `MAX_UPLOAD_MB` | `50` | Upload size cap |

Frontend: `AI-agent-UI/.env.local` → `NEXT_PUBLIC_API_BASE=http://localhost:8090`

---

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

**42 tests.** Only the external boundaries (Gemini, Pinecone) are mocked — DuckDB, file
extraction, SQL, and the Python subprocess all run for real, so the suite runs offline and costs
no API quota. Live-database behavior is covered via SQLite, which exercises the identical
`ATTACH` code path as Postgres/MySQL without needing a server.

---

## Running with Docker

```bash
cp backend/env_sample.txt backend/.env    # add your keys
docker compose up --build
```

`NEXT_PUBLIC_API_BASE` is inlined at **build** time (the browser calls it), so deploying
anywhere other than localhost means rebuilding the frontend image:

```bash
NEXT_PUBLIC_API_BASE=https://api.example.com docker compose build frontend
```

### Why Docker matters beyond packaging

`run_python` executes model-generated code. Containerizing is what gives its sandbox real teeth:

| Control | Local (Windows) | In Docker (Linux) |
|---|---|---|
| Wall-clock timeout | ✅ | ✅ |
| Memory / CPU / file-size rlimits | ❌ (no `resource` module) | ✅ |
| Non-root execution | ❌ | ✅ |
| Container memory/PID/CPU caps | ❌ | ✅ |
| Filesystem blast radius | whole user account | container only |

---

## Deploying (Render, free tier)

> ⚠️ This deploys the app **with no authentication** (see "Known limitations" below) on a public
> URL. Anyone who finds it can query or delete datasets and burn your Gemini/Pinecone quota. Fine
> for a demo you control the link to; add auth before sharing it widely.

`render.yaml` at the repo root is a [Render Blueprint](https://render.com/docs/blueprint-spec)
that deploys the backend and frontend as two free-tier Docker web services.

1. Push this repo to GitHub (Render Blueprints deploy from a connected repo).
2. In the Render dashboard: **New → Blueprint**, pick this repo. Render reads `render.yaml`.
3. Fill in the secret env vars it prompts for (`GOOGLE_API_KEY`, `PINECONE_API_KEY`).
4. Confirm the backend service's actual `*.onrender.com` URL matches `render.yaml`'s
   `NEXT_PUBLIC_API_BASE`; if it differs, update it and manually redeploy the frontend — this
   value is inlined at **build** time, same caveat as the local Docker setup above.

**Free-tier caveats:**
- **No persistent disk** — uploaded datasets (DuckDB files) don't survive a redeploy or
  idle spin-down. Fine for a demo, not for real usage.
- **Spin-down** after ~15 min idle; the next request eats a 30-60s cold start.
- **CPU throttling** on the shared free instance can make the agent loop slower than local, so
  `render.yaml` raises `PY_TIMEOUT_SECONDS`, `PY_MAX_CPU_SECONDS`, and `MAX_AGENT_ITERATIONS`
  above the `env_sample.txt` defaults. If the agent still hits its tool-call budget, ask a
  narrower question.

Railway is an equally viable alternative — no code changes needed, just not set up here.

---

## Known limitations

These are deliberate trade-offs, documented rather than hidden:

- **`run_python` is not a hardened sandbox.** Under Docker it gets rlimits, a non-root user, and
  container caps; on Windows it's only a timeout and a scoped working directory. Either way it
  shares the backend's network and filesystem — per-execution containers or gVisor would be
  needed for genuinely untrusted input.
- **No authentication.** Anyone who can reach the API can query or delete any dataset. Do not
  expose this publicly as-is.
- **Live-DB credentials** are stored in plaintext in the dataset's gitignored `meta.json`
  (redacted in API responses). Use a dedicated read-only database user.
- **Prompt injection** is possible via uploaded content. Partial mitigations: read-only SQL
  guard, execution timeout, `READ_ONLY` database attach.
- **Free-tier quotas are tight** — an agentic loop makes several model calls per question. See
  the model table above.
- **Scanned/image PDFs** have no text layer and will fail ingestion (no OCR).
- Changing `EMBED_MODEL` invalidates existing Pinecone vectors (different vector space); rebuild
  them with `scripts/reingest_collections.py`.

## Roadmap

1. Add authentication before any public deployment.
2. Per-execution container isolation for `run_python`.
