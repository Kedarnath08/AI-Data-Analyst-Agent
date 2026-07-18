# Unified Backend — RAG Chatbot + AI Data Analyst Agent

A single FastAPI service combining two capabilities:

- **Document Chat (RAG)** — upload PDFs, ask questions, get streamed answers grounded in the
  documents with citations. Backed by Gemini embeddings + Pinecone vector search.
- **Data Analyst Agent** — upload CSV/Excel/PDF/DOCX (or connect a live SQL database), ask in
  plain English, and an agent writes and runs SQL + Python (pandas/Plotly) to answer with charts.

Both run in one process, one port, one virtualenv.

## Layout

```
backend/
├── api.py                 # single FastAPI app `apps`; mounts all routers; /ask, /health
└── src/
    ├── config.py          # merged settings (RAG + analyst knobs, one GOOGLE_API_KEY/GEN_MODEL)
    ├── cors.py            # shared CORS (allows the Next.js dev UI on :3000)
    ├── rag/               # Document Chat: routes, Pinecone vectors, PDF/chunk, Gemini answerer
    └── analyst/           # Data Analyst: datasets, DuckDB, ingestion, agent loop, tools, sandbox
```

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy env_sample.txt .env    # then edit .env with your keys
uvicorn api:apps --host 0.0.0.0 --port 8090
```

Swagger UI: http://localhost:8090/docs

### Model / SDK notes
- One `GEN_MODEL` (default `gemini-flash-latest`) serves both RAG generation and the analyst's
  function-calling agent. `EMBED_MODEL` (default `gemini-embedding-001`) is used for RAG embeddings.
- Requires `google-genai>=2.12.1`: Gemini thinking models attach a `thought_signature` to each
  function call that must be echoed back across turns, which older SDKs drop.

## Endpoints

**RAG:** `POST /ingest` (PDFs), `POST /ingest_text`, `POST /query`, `POST /query_stream` (SSE),
`GET/POST /collections/`, `DELETE /collections/{name}`.

**Data Analyst:** `POST /datasets/upload`, `GET /datasets/`, `GET /datasets/{id}`,
`GET /datasets/{id}/preview`, `DELETE /datasets/{id}`, `POST /ask`.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

Tests mock only the external boundaries (Gemini + Pinecone) and run everything else for real
(DuckDB, extraction, subprocess execution), so they run offline with no API quota.

## Known limitations
- **`run_python` is not a security sandbox** — subprocess + wall-clock timeout + scoped working dir
  only; no filesystem/network/memory isolation (no `resource.setrlimit` on Windows). Do not expose
  to untrusted users without real isolation (Docker/gVisor); planned for the deployment phase.
- Prompt-injection surface via uploaded content; `run_sql` is restricted to read-only SELECT/WITH.
- Gemini free-tier quota is low; the agent makes several calls per question — use a billed key for
  sustained use.
