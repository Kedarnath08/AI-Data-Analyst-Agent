import re
import time
from typing import List
from src.config import settings
from google import genai
from pinecone import Pinecone, ServerlessSpec

# ---- Embeddings via Gemini ----

_RETRY_AFTER_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")


def _retry_delay_from_error(err: Exception, default: float) -> float:
    """Honor the server's suggested retryDelay when it gives one."""
    m = _RETRY_AFTER_RE.search(str(err))
    if m:
        try:
            return min(float(m.group(1)) + 2.0, 120.0)
        except ValueError:
            pass
    return default


class GeminiEmbedder:
    """Embeds text via Gemini, retrying on rate limits.

    The free tier allows ~100 embed requests/minute and a batch of N texts
    counts as N requests, so ingesting a large PDF reliably trips a 429. We
    back off and retry rather than failing the whole ingest.
    """

    MAX_ATTEMPTS = 6

    def __init__(self, api_key: str, model: str, output_dim: int = 768):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.output_dim = output_dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        delay = 30.0
        last_err = None
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                # We explicitly request 768-dimensional embeddings.
                res = self.client.models.embed_content(
                    model=self.model,
                    contents=texts,
                    config={"output_dimensionality": self.output_dim}
                )
                if hasattr(res, "embeddings"):
                    return [e.values for e in res.embeddings]
                return [res.embedding.values]
            except Exception as e:
                msg = str(e)
                is_rate_limited = "429" in msg or "RESOURCE_EXHAUSTED" in msg
                if not is_rate_limited or attempt == self.MAX_ATTEMPTS - 1:
                    raise
                last_err = e
                wait = _retry_delay_from_error(e, delay)
                print(f"[embed] rate limited; retrying in {wait:.0f}s "
                      f"(attempt {attempt + 1}/{self.MAX_ATTEMPTS})")
                time.sleep(wait)
                delay = min(delay * 2, 120.0)
        # Unreachable: the loop either returns or re-raises on the last attempt.
        raise last_err or RuntimeError("Embedding failed without an error")


EMBED_DIM = 768  # keep Pinecone index + Gemini output in sync
embedder = GeminiEmbedder(settings.GOOGLE_API_KEY,
                          settings.EMBED_MODEL, EMBED_DIM)

# ---- Pinecone setup (serverless) ----
PC_API_KEY = settings.PINECONE_API_KEY
PC_INDEX = settings.PINECONE_INDEX
PC_CLOUD = settings.PINECONE_CLOUD
PC_REGION = settings.PINECONE_REGION

pc = Pinecone(api_key=PC_API_KEY)

# Create index if it doesn't exist
existing = [i.name for i in pc.list_indexes()]
if PC_INDEX not in existing:
    pc.create_index(
        name=PC_INDEX,
        dimension=EMBED_DIM,
        metric="cosine",
        spec=ServerlessSpec(cloud=PC_CLOUD, region=PC_REGION)
    )

index = pc.Index(PC_INDEX)

BATCH = 100  # tune 64–200 based on your keys/limits


def batched(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i+size]


def upsert_chunks(collection_name: str, chunks: list, source_id: str):
    """
    Store vectors in Pinecone. Supports both:
      - list of strings: ["chunk1", "chunk2", ...]
      - list of dicts: [{"text": ..., "page": ...}, ...]
    Each chunk is embedded (text only), and metadata includes source, chunk_index, and page (if present).
    """
    namespace = collection_name
    idx_offset = 0
    for chunk_batch in batched(chunks, BATCH):
        norm_batch = []
        for c in chunk_batch:
            if isinstance(c, dict):
                text = str(c.get("text", "")).strip()
                page = c.get("page")
            else:
                text = str(c).strip()
                page = None
            if text:
                norm_batch.append({"text": text, "page": page})
        if not norm_batch:
            continue
        texts = [c["text"] for c in norm_batch]
        vectors = embedder.embed(texts)
        items = []
        for i, vec in enumerate(vectors):
            text_val = norm_batch[i]["text"]
            if isinstance(text_val, dict):
                text_val = text_val.get("text", "")
            elif not isinstance(text_val, str):
                text_val = str(text_val)
            meta = {
                "text": text_val,
                "source": source_id,
                "chunk_index": idx_offset + i
            }
            if norm_batch[i]["page"] is not None:
                meta["page"] = norm_batch[i]["page"]
            items.append({
                "id": f"{source_id}_{idx_offset + i}",
                "values": vec,
                "metadata": meta
            })
        index.upsert(vectors=items, namespace=namespace)
        idx_offset += len(norm_batch)


def search(collection_name: str, query: str, top_k: int, filter: dict = None):
    """
    Vector search: embed the query, retrieve top_k nearest chunks.
    Optionally filter results using Pinecone's filter dict.
    We return a structure compatible with the rest of the app.
    """
    namespace = collection_name
    qv = embedder.embed([query])[0]
    query_args = {
        "vector": qv,
        "top_k": top_k,
        "include_metadata": True,
        "namespace": namespace
    }
    if filter is not None:
        query_args["filter"] = filter

    res = index.query(**query_args)

    docs, metas, dists = [], [], []
    for match in res.matches:
        md = match.metadata or {}
        docs.append(md.get("text", ""))
        meta = {
            "source": md.get("source", ""),
            "chunk_index": int(md.get("chunk_index", -1))
        }
        if "page" in md:
            meta["page"] = md["page"]
        metas.append(meta)
        dists.append(1.0 - float(match.score)
                     if match.score is not None else 1.0)

    return {
        "documents": [docs],
        "metadatas": [metas],
        "distances": [dists]
    }
