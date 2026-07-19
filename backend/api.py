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
        # iter_agent is blocking (network calls, subprocesses, time.sleep), so
        # it runs in a worker thread and hands events back through a queue —
        # otherwise it would stall the whole event loop.
        send, receive = anyio.create_memory_object_stream(max_buffer_size=100)

        def produce():
            try:
                for event in iter_agent(body.dataset_id, q):
                    anyio.from_thread.run(send.send, event)
            except Exception as e:
                anyio.from_thread.run(
                    send.send,
                    {"type": "final", "payload": {
                        "answer": None,
                        "error": f"{type(e).__name__}: {e}",
                        "trace": [],
                        "fig_json": None,
                    }},
                )
            finally:
                anyio.from_thread.run(send.aclose)

        async with anyio.create_task_group() as tg:
            tg.start_soon(anyio.to_thread.run_sync, produce)
            async with receive:
                async for event in receive:
                    kind = event.pop("type")
                    yield sse_event(kind, event)

    return StreamingResponse(
        event_generator(),
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
