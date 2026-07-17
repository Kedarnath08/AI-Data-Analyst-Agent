# Project Overview — AI Data Analyst Agent ("Gemicone")

A RAG (Retrieval-Augmented Generation) chat app for PDFs: upload documents, they get chunked and embedded into Pinecone, and questions are answered by Gemini using only the retrieved chunks as context. Two independent folders, no shared package management:

- `rag-gemini-backend/` — Python FastAPI service
- `AI-agent-UI/` — Next.js 15 (App Router, React 19) frontend

No git repo is initialized at the root (each folder has its own `.gitignore` but this is not a git repository currently).

---

## Backend — `rag-gemini-backend/`

FastAPI app (`api.py`, app instance named `apps`), run via:
```
uvicorn api:apps --host 0.0.0.0 --port 8090
```

### Modules (`src/`)
- **`config.py`** — loads `.env` via `python-dotenv` into a `Settings` object: Gemini API key/models, Pinecone credentials, and RAG tuning knobs (`TOP_K=8`, `SIM_THRESHOLD=0.5`, `CHUNK_SIZE`, `CHUNK_OVERLAP`).
- **`pdf.py`** — extracts text per-page from a PDF using `pypdf`, returns `[{"text", "page"}, ...]`.
- **`chunk.py`** — cleans text (fixes ligatures, hyphenation, whitespace) and splits into overlapping word-based chunks, tagging each with a page number.
- **`vectors.py`** — the core RAG engine:
  - `GeminiEmbedder` wraps `google-genai` to produce 768-dim embeddings (`gemini-embedding-001` by default).
  - Connects to Pinecone (serverless), auto-creates the index (`rag-gemini-demo`, cosine metric, 768 dims) if missing.
  - `upsert_chunks()` — embeds and upserts chunks into a Pinecone **namespace** (namespace = "collection" in this app's vocabulary).
  - `search()` — embeds the query and does a top-k similarity query, optionally with a Pinecone metadata `filter`.
- **`collections.py`** — router (`/collections`) that lists/creates/deletes Pinecone namespaces. Note: "create" is a no-op (Pinecone namespaces are created implicitly on first upsert) — it just tracks the name for UI purposes. Delete wipes all vectors in that namespace.
- **`llm.py`** — builds a prompt that forces Gemini to answer *only* from provided context, replies with a fixed "not present in document" sentence otherwise, and asks for `[chunk N]` citations (which are then stripped from the final answer text — citations are actually surfaced separately as structured `citations` metadata, not inline text).
- **`cors.py`** — allows only `localhost:3000` / `127.0.0.1:3000` (the Next.js dev server).

### API endpoints (`api.py`)
- `POST /ingest` — multipart upload of up to 5 PDFs (50MB each) into a `collection`. Extracts text, chunks per-page, embeds, upserts. Returns per-file success/error + total chunk count.
- `POST /ingest_text` — same pipeline but for raw pasted text instead of a PDF.
- `POST /query` — non-streaming Q&A. Retrieves chunks above `sim_threshold`, asks Gemini, returns `{answer, citations}`. If nothing relevant is found, returns a fixed message plus a Google search suggestion link.
- `POST /query_stream` — Server-Sent Events version of the same flow. Emits `citations`, then `token` events. Note: true Gemini streaming isn't wired up (`answer_with_context.stream` doesn't exist on the function), so it always falls back to faking a stream by chopping the full answer into 60-char pieces with a small delay — response still waits for the full Gemini call before "streaming" starts.
- Collections sub-router: `GET/POST /collections/`, `DELETE /collections/{name}`, `GET /collections/{name}/sources` (not fully implemented — just returns vector count).

### Data / storage
- Uploaded PDFs are saved locally to `data/uploads/` (a handful of sample PDFs already exist there — class notes, marks cards, a cloud roadmap, animal-fact guides — these look like the developer's own test uploads).
- Vector storage is entirely in Pinecone (no local vector DB despite the folder name suggesting Chroma-style tuple returns — the `search()` return shape (`documents`/`metadatas`/`distances` lists) mimics a Chroma-like interface but is backed by Pinecone).

### Config / secrets
- `.env` (gitignored, correctly) currently holds **live** API keys for Google Gemini and Pinecone, plus `EMBED_MODEL=text-embedding-004`, `GEN_MODEL=gemini-2.5-flash`, `CHUNK_SIZE=900`, `CHUNK_OVERLAP=300`.
- `env_sample.txt` is the template for others to copy into `.env`.
- ⚠️ The code default in `config.py` (`GEN_MODEL` default `"gemini-3-flash-preview"`) differs from what's actually set in `.env` (`gemini-2.5-flash`) — the `.env` value wins at runtime, so this is just a stale/aspirational default, not a live bug.

---

## Frontend — `AI-agent-UI/`

Next.js 15 App Router project (Turbopack), plain CSS Modules (no component library), talks to the backend via `NEXT_PUBLIC_API_BASE` (set to `http://localhost:8090` in `.env.local`).

### Structure
- **`src/app/page.js`** — the entire chat UI in one large client component (`HomePage`, ~950 lines). Responsibilities:
  - Chat message list with user/assistant/system bubbles, a fake typewriter animation for assistant replies, basic Markdown rendering (code blocks/backticks/newlines only — via `dangerouslySetInnerHTML`, so no sanitization beyond the two regexes it applies).
  - Drag-and-drop / file-picker PDF attachments, per-file upload status chips, upload to `/ingest`.
  - Sends questions to `/query_stream`, hand-rolls SSE parsing (splits on `\n`, tracks `event:`/`data:` lines), handles `token`, `citations`, `not_found`, `error`, `done` events.
  - Renders citations as clickable chips (chunk index + page + source file).
  - "Regenerate" re-asks a prior question; "Stop" aborts the in-flight stream via `AbortController`.
  - Light/dark theme toggle (local state only, not persisted).
- **`src/components/Sidebar.js`** — left panel: app title, "New Chat" (just reloads the page — no real session/chat history persistence), embeds `CollectionManager`, and two *disabled* (display-only, not functional) inputs for `top_k`/`sim_threshold` — these settings are hardcoded in `page.js` (`top_k: 8, sim_threshold: 0.5`) and not actually wired to the UI inputs.
- **`src/components/CollectionManager.js`** — dropdown of collections fetched from the backend, "create" and "clear" (delete) actions. Also keeps a `localStorage`-backed shadow list (`ragui_local_collections`) so newly created collections still show up even though backend "create" is a no-op stats-wise; last-selected collection persisted in `localStorage` too.
- **`src/utils/collections.js`** — thin fetch wrappers for the `/collections` endpoints.

### Notable inconsistencies / rough edges (for awareness, not yet fixed)
- Fallback API base in `page.js` (`ask()`) is `http://127.0.0.1:8000`, but the configured/actual backend port is `8090` (per `.env.local` and the README). This only matters if `NEXT_PUBLIC_API_BASE` is ever unset.
- Streaming is simulated, not real token-by-token generation from Gemini.
- No authentication/authorization anywhere — anyone who can reach the API can ingest/query/delete any collection.
- Assistant/user text is rendered via `dangerouslySetInnerHTML` with only light regex-based Markdown handling — acceptable for a personal/local tool, but not XSS-safe if this were ever exposed publicly.
- `.next/` build output is present in the repo tree (should typically be gitignored, though there's no git repo here yet so it doesn't matter until one is initialized).

---

## How the pieces fit together
1. User picks/creates a **collection** (= Pinecone namespace) in the sidebar.
2. User drops a PDF → frontend `POST /ingest` → backend extracts text per page, chunks it, embeds each chunk (Gemini embeddings), upserts into Pinecone under that namespace.
3. User asks a question → frontend `POST /query_stream` → backend embeds the question, does a Pinecone similarity search scoped to that namespace, filters by `sim_threshold`, sends the top matches to Gemini with a "context-only" system prompt, streams back the answer (simulated) plus citations (chunk index, source filename, page number).
4. If no chunk clears the similarity threshold, the backend returns a fixed "not in document" message and a Google search suggestion link instead of calling the LLM.
