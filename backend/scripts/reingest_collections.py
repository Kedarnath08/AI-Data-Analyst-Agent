"""Rebuild Pinecone collections with the current embedding model.

Why this exists: collections ingested with an older embedding model are
effectively dead — queries embedded with the current model land in a different
vector space, so nothing ever matches and every question answers "not present
in the provided document". Re-ingesting fixes that.

Usage (from the backend/ directory, with .env configured):
    python scripts/reingest_collections.py            # rebuild the configured sets
    python scripts/reingest_collections.py --dry-run  # show the plan only
    python scripts/reingest_collections.py --drop Hello

Run it against a running app? No — this talks to Pinecone directly, so the API
server does not need to be up.
"""
import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/reingest_collections.py` from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings  # noqa: E402
from src.rag import chunk, pdf  # noqa: E402
from src.rag.vectors import index, upsert_chunks  # noqa: E402

UPLOADS = Path("data/uploads")

# collection -> source PDFs to rebuild it from
PLAN: dict[str, list[str]] = {
    "animals": ["animalfacts.pdf", "rag_sample_animal_guide.pdf"],
    "AIML": ["AI-NOTES-UNIT-1.pdf", "AIML-NOTE__6th-SEM.pdf"],
}


def existing_namespaces() -> dict:
    return index.describe_index_stats().get("namespaces", {}) or {}


def drop(namespace: str) -> None:
    if namespace in existing_namespaces():
        index.delete(namespace=namespace, delete_all=True)
        print(f"  dropped namespace '{namespace}'")
    else:
        print(f"  namespace '{namespace}' not present, nothing to drop")


def ingest_pdf(collection: str, path: Path) -> int:
    pages = pdf.extract_text_from_pdf(str(path))
    chunks: list[dict] = []
    for page in pages:
        text = (page.get("text") or "").strip()
        if not text:
            continue
        chunks.extend(
            chunk.chunk_text(
                text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP,
                page=page.get("page"),
            )
        )
    if not chunks:
        print(f"  !! {path.name}: no extractable text, skipped")
        return 0
    upsert_chunks(collection, chunks, path.name)
    print(f"  {path.name}: {len(chunks)} chunks")
    return len(chunks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ap.add_argument("--drop", nargs="*", default=["Hello"],
                    help="namespaces to delete without rebuilding")
    args = ap.parse_args()

    print(f"Embedding model: {settings.EMBED_MODEL}")
    print(f"Pinecone index:  {settings.PINECONE_INDEX}")
    print(f"Existing namespaces: {sorted(existing_namespaces())}\n")

    missing = [
        f for files in PLAN.values() for f in files if not (UPLOADS / f).exists()
    ]
    if missing:
        print(f"ERROR: missing source PDFs in {UPLOADS}/: {missing}")
        return 1

    if args.dry_run:
        for collection, files in PLAN.items():
            print(f"would rebuild '{collection}' from {files}")
        for ns in args.drop:
            print(f"would drop '{ns}'")
        return 0

    for ns in args.drop:
        print(f"Dropping '{ns}':")
        drop(ns)

    for collection, files in PLAN.items():
        print(f"\nRebuilding '{collection}':")
        drop(collection)
        total = sum(ingest_pdf(collection, UPLOADS / f) for f in files)
        print(f"  -> {total} chunks total")

    print(f"\nDone. Namespaces now: {sorted(existing_namespaces())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
