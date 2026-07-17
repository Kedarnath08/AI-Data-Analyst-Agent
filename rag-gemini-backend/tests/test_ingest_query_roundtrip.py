from fastapi.testclient import TestClient

import api as api_module

client = TestClient(api_module.apps)


def test_ingest_then_query_returns_answer_with_citations(fake_backend):
    collection = "test_roundtrip_tigers"

    ingest_res = client.post(
        "/ingest_text",
        json={
            "collection": collection,
            "text": (
                "The Bengal tiger's roar can be heard from up to 3 "
                "kilometers away in favorable conditions."
            ),
            "source": "test_source",
        },
    )
    assert ingest_res.status_code == 200
    ingest_body = ingest_res.json()
    assert ingest_body["ok"] is True
    assert ingest_body["chunks"] == 1

    query_res = client.post(
        "/query",
        json={
            "collection": collection,
            "question": "How far can a tiger's roar travel?",
            "sim_threshold": 0.1,
        },
    )
    assert query_res.status_code == 200
    data = query_res.json()
    assert "kilometers" in data["answer"]
    # The [chunk N] citation marker should be stripped from the answer text.
    assert "[chunk" not in data["answer"]
    assert len(data["citations"]) == 1
    assert data["citations"][0]["source"] == "test_source"
    assert data["citations"][0]["chunk_index"] == 0


def test_query_below_similarity_threshold_returns_not_found(fake_backend):
    collection = "test_roundtrip_pizza"

    client.post(
        "/ingest_text",
        json={
            "collection": collection,
            "text": (
                "Margherita pizza is topped with tomato sauce, mozzarella "
                "cheese, and fresh basil leaves."
            ),
            "source": "pizza_source",
        },
    )

    query_res = client.post(
        "/query",
        json={
            "collection": collection,
            "question": "How far can a tiger's roar travel?",
            "sim_threshold": 0.5,
        },
    )
    assert query_res.status_code == 200
    data = query_res.json()
    assert data["answer"] == "Sorry, that topic is not present in the provided document."
    assert "suggested_search" in data
