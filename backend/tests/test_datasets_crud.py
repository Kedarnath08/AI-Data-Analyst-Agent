from fastapi.testclient import TestClient

import api
from tests.conftest_helpers import make_csv

client = TestClient(api.apps)


def _upload(tmp_path):
    csv = make_csv(tmp_path)
    with open(csv, "rb") as f:
        res = client.post("/datasets/upload", files={"file": ("sales.csv", f, "text/csv")})
    return res.json()["dataset_id"]


def test_list_get_delete_lifecycle(tmp_path):
    assert client.get("/datasets/").json()["datasets"] == []

    ds_id = _upload(tmp_path)
    listing = client.get("/datasets/").json()["datasets"]
    assert len(listing) == 1
    assert listing[0]["id"] == ds_id

    assert client.get(f"/datasets/{ds_id}").status_code == 200

    dele = client.delete(f"/datasets/{ds_id}")
    assert dele.status_code == 200
    assert dele.json()["ok"] is True

    assert client.get("/datasets/").json()["datasets"] == []
    assert client.get(f"/datasets/{ds_id}").status_code == 404


def test_get_missing_dataset_404(tmp_path):
    assert client.get("/datasets/doesnotexist").status_code == 404


def test_delete_missing_dataset_404(tmp_path):
    assert client.delete("/datasets/doesnotexist").status_code == 404


def test_preview_missing_dataset_404(tmp_path):
    assert client.get("/datasets/doesnotexist/preview").status_code == 404


def test_ask_missing_dataset_404(tmp_path):
    res = client.post("/ask", json={"dataset_id": "nope", "question": "hi"})
    assert res.status_code == 404
