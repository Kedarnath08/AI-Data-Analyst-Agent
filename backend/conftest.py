"""Shared test fixtures for the unified backend.

Strategy (same for both halves): mock ONLY the external boundaries — Gemini and
Pinecone — and run everything else for real (real DuckDB, real pandas/pdfplumber/
python-docx extraction, real subprocess for run_python). Tests run offline and
cost no API quota.

Note: importing `api` pulls in `src.rag.vectors`, which connects to the real
Pinecone project at import time (a pre-existing app constraint), so a valid
PINECONE_API_KEY in `.env` is still required just to load the app. The
`fake_backend` fixture then swaps in in-memory fakes so no real Pinecone data is
touched during tests.
"""
from types import SimpleNamespace

import pytest
from google.genai import types

from src.rag import vectors as vectors_module
from src.rag import llm as rag_llm_module


# --------------------------------------------------------------------------
# Filesystem isolation (data analyst tests write real DuckDB files)
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Run each test in its own temp dir so data/datasets and data/uploads are
    fresh and isolated. Analyst modules compute paths relative to cwd at call time."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "datasets").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "uploads").mkdir(parents=True, exist_ok=True)
    yield


# --------------------------------------------------------------------------
# RAG: fake Gemini embedder + Pinecone index + Gemini generation
# --------------------------------------------------------------------------
class FakeEmbedder:
    """Deterministic stand-in for GeminiEmbedder: bag-of-keywords vectors."""

    KEYWORDS = ["tiger", "roar", "kilometer", "pizza", "cheese", "sauce"]

    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            out.append([1.0 if kw in low else 0.0 for kw in self.KEYWORDS])
        return out


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class _FakeMatch:
    def __init__(self, score, metadata):
        self.score = score
        self.metadata = metadata


class _FakeQueryResult:
    def __init__(self, matches):
        self.matches = matches


class FakeIndex:
    """In-memory stand-in for a Pinecone Index, scoped by namespace."""

    def __init__(self):
        self._store = {}

    def upsert(self, vectors, namespace):
        ns = self._store.setdefault(namespace, {})
        for item in vectors:
            ns[item["id"]] = {"values": item["values"], "metadata": item["metadata"]}

    def query(self, vector, top_k, include_metadata=True, namespace=None, filter=None):
        ns = self._store.get(namespace, {})
        scored = [
            (_cosine(vector, item["values"]), item["metadata"])
            for item in ns.values()
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        matches = [_FakeMatch(score, meta) for score, meta in scored[:top_k]]
        return _FakeQueryResult(matches)

    def delete(self, namespace, delete_all=False):
        self._store.pop(namespace, None)


class _SimpleTextResponse:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def fake_backend(monkeypatch):
    """Replaces the Gemini embedder, the Pinecone index, and the Gemini
    generation call with deterministic in-memory fakes (RAG side)."""
    fake_index = FakeIndex()
    monkeypatch.setattr(vectors_module, "embedder", FakeEmbedder())
    monkeypatch.setattr(vectors_module, "index", fake_index)

    def fake_generate_content(model, contents, config=None):
        return _SimpleTextResponse(
            "Tigers can roar loud enough to be heard from up to 3 kilometers away. [chunk 0]"
        )

    monkeypatch.setattr(rag_llm_module.client.models, "generate_content", fake_generate_content)
    return fake_index


# --------------------------------------------------------------------------
# Data analyst: scripted Gemini function-calling responses
# --------------------------------------------------------------------------
class FakeGeminiResponse:
    """Mimics GenerateContentResponse: .candidates[0].content.parts and .text."""

    def __init__(self, parts):
        content = SimpleNamespace(parts=parts, role="model")
        self.candidates = [SimpleNamespace(content=content)]

    @property
    def text(self):
        texts = [p.text for p in self.candidates[0].content.parts
                 if getattr(p, "text", None)]
        return "".join(texts) if texts else None


@pytest.fixture
def scripted_agent(monkeypatch):
    """Script a sequence of Gemini turns for analyst llm.run_agent.

    Each turn is either a list of (tool_name, args) tuples -> function_call
    parts, or a string -> a final text answer.
    """
    from src.analyst import llm as analyst_llm_module

    def make(turns):
        state = {"i": 0}

        def fake_generate_content(model, contents, config=None):
            if state["i"] >= len(turns):
                return FakeGeminiResponse([types.Part.from_text(text="(end)")])
            turn = turns[state["i"]]
            state["i"] += 1
            if isinstance(turn, str):
                return FakeGeminiResponse([types.Part.from_text(text=turn)])
            parts = [types.Part.from_function_call(name=n, args=a) for n, a in turn]
            return FakeGeminiResponse(parts)

        monkeypatch.setattr(analyst_llm_module.client.models, "generate_content",
                            fake_generate_content)
        return state

    return make
