"""Unified backend: RAG document Q&A + agentic data analyst in one FastAPI app.

- RAG routes:       /ingest, /ingest_text, /query, /query_stream, /collections/*
- Data analyst:     /datasets/*, /ask
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.cors import setup_cors
from src.rag.routes import router as rag_router
from src.rag.collections import router as collections_router
from src.analyst.datasets import router as datasets_router
from src.analyst import duck
from src.analyst.llm import run_agent

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
