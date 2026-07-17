"""
Shared test fixtures.

Note: importing `api` pulls in `src.vectors`, which connects to the real
Pinecone project at import time (an existing constraint of the app, not
introduced by these tests) — so a valid PINECONE_API_KEY in `.env` is still
required just to load the app. Everything that actually costs API quota or
needs determinism (embeddings, vector search, and Gemini generation) is
replaced with in-memory fakes below, so tests don't call Gemini or write to
real Pinecone data.
"""
import pytest

from src import vectors as vectors_module
from src import llm as llm_module


class FakeEmbedder:
    """Deterministic stand-in for GeminiEmbedder: encodes text as a small
    bag-of-keywords vector so semantically related chunks score higher,
    without any real embedding call."""

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


class FakeGeminiResponse:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def fake_backend(monkeypatch):
    """Replaces the Gemini embedder, the Pinecone index, and the Gemini
    generation call with deterministic in-memory fakes."""
    fake_index = FakeIndex()
    monkeypatch.setattr(vectors_module, "embedder", FakeEmbedder())
    monkeypatch.setattr(vectors_module, "index", fake_index)

    def fake_generate_content(model, contents, config=None):
        return FakeGeminiResponse(
            "Tigers can roar loud enough to be heard from up to 3 kilometers away. [chunk 0]"
        )

    monkeypatch.setattr(llm_module.client.models, "generate_content", fake_generate_content)
    return fake_index
