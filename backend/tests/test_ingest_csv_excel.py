from fastapi.testclient import TestClient

import api
from tests.conftest_helpers import make_csv, make_excel

client = TestClient(api.apps)


def test_upload_csv_creates_dataset_with_schema(tmp_path):
    csv = make_csv(tmp_path)
    with open(csv, "rb") as f:
        res = client.post("/datasets/upload", files={"file": ("sales.csv", f, "text/csv")})
    assert res.status_code == 200
    body = res.json()
    ds_id = body["dataset_id"]
    assert len(body["tables"]) == 1
    table = body["tables"][0]
    assert table["name"] == "data"
    assert table["row_count"] == 4
    colnames = {c["name"] for c in table["columns"]}
    assert colnames == {"region", "product", "units", "revenue"}

    # GET returns metadata + schema
    got = client.get(f"/datasets/{ds_id}")
    assert got.status_code == 200
    schema = got.json()["schema"]
    assert "data" in schema

    # preview returns rows
    prev = client.get(f"/datasets/{ds_id}/preview")
    assert prev.status_code == 200
    assert prev.json()["row_count"] == 4


def test_upload_excel_creates_one_table_per_sheet(tmp_path):
    xlsx = make_excel(tmp_path)
    with open(xlsx, "rb") as f:
        res = client.post(
            "/datasets/upload",
            files={"file": ("book.xlsx", f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert res.status_code == 200
    tables = {t["name"] for t in res.json()["tables"]}
    assert tables == {"cities", "items"}


def test_upload_rejects_unsupported_extension(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello", encoding="utf-8")
    with open(bad, "rb") as f:
        res = client.post("/datasets/upload", files={"file": ("notes.txt", f, "text/plain")})
    assert res.status_code == 400
    assert "Unsupported" in res.json()["detail"]
