from fastapi import FastAPI
from pydantic import BaseModel

from src.cors import setup_cors
from src.datasets import router as datasets_router
from src.llm import run_agent

apps = FastAPI(title="AI Data Analyst Agent", version="0.1.0")

setup_cors(apps)
apps.include_router(datasets_router)


class AskIn(BaseModel):
    dataset_id: str
    question: str


@apps.get("/health")
def health():
    return {"ok": True}


@apps.post("/ask")
def ask(body: AskIn):
    from fastapi import HTTPException

    from src import duck

    if not duck.exists(body.dataset_id):
        raise HTTPException(404, "Dataset not found")
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "Question is empty.")
    return run_agent(body.dataset_id, q)
