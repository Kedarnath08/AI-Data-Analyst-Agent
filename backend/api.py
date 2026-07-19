"""Unified backend: RAG document Q&A + agentic data analyst in one FastAPI app.

- RAG routes:       /ingest, /ingest_text, /query, /query_stream, /collections/*
- Data analyst:     /datasets/*, /ask
"""
import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.cors import setup_cors
from src.rag.routes import router as rag_router, sse_event
from src.rag.collections import router as collections_router
from src.analyst.datasets import router as datasets_router
from src.analyst import duck
from src.analyst.llm import iter_agent, run_agent

apps = FastAPI(title="AI Data Analyst Agent + RAG Chatbot", version="1.0.0")

setup_cors(apps)

# RAG (document Q&A)
apps.include_router(rag_router)
apps.include_router(collections_router)
# Data analyst (tabular / DB analysis)
apps.include_router(datasets_router)


class AskIn(BaseModel):
    dataset_id: str
    question: str


@apps.get("/health")
def health():
    return {"ok": True}


@apps.post("/ask")
def ask(body: AskIn):
    if not duck.exists(body.dataset_id):
        raise HTTPException(404, "Dataset not found")
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "Question is empty.")
    return run_agent(body.dataset_id, q)


@apps.post("/ask_stream")
async def ask_stream(body: AskIn):
    """Same as /ask, but streams the agent's progress as SSE.

    A question can take a minute or more (several model calls, plus waiting out
    free-tier rate limits), so the client needs to see each step as it happens
    rather than staring at a spinner.
    """
    if not duck.exists(body.dataset_id):
        raise HTTPException(404, "Dataset not found")
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "Question is empty.")

    async def event_generator():
        # iter_agent blocks (network calls, subprocesses, time.sleep), so each
        # step is advanced in a worker thread to keep the event loop free.
        # Pulling one item at a time is deliberate: driving the generator from a
        # background task through a memory stream breaks when this async
        # generator is suspended mid-yield (the task group tears down and the
        # producer dies with BrokenResourceError).
        agent = iter_agent(body.dataset_id, q)
        done = object()

        def next_event():
            try:
                return next(agent)
            except StopIteration:
                return done

        try:
            while True:
                event = await anyio.to_thread.run_sync(next_event)
                if event is done:
                    break
                kind = event.pop("type")
                yield sse_event(kind, event)
        except Exception as e:
            yield sse_event("final", {"payload": {
                "answer": None,
                "error": f"{type(e).__name__}: {e}",
                "trace": [],
                "fig_json": None,
            }})
        finally:
            agent.close()

    return StreamingResponse(
        event_generator(),
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
