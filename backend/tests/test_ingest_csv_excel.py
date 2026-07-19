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


def test_upload_non_utf8_csv_falls_back_to_other_encodings(tmp_path):
    """Real-world CSVs (Kaggle, Excel-on-Windows exports) are often cp1252 or
    latin-1. DuckDB's reader is UTF-8 only, so we must fall back rather than
    reject the file."""
    csv_path = tmp_path / "latin1.csv"
    csv_path.write_text(
        "city,cafe_name,rating\nZürich,Café Beic,4.5\nMálaga,Señor Tapas,4.2\n",
        encoding="latin-1",
    )
    with open(csv_path, "rb") as f:
        res = client.post("/datasets/upload", files={"file": ("latin1.csv", f, "text/csv")})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tables"][0]["row_count"] == 2

    # Characters must round-trip, not arrive as mojibake.
    preview = client.get(f"/datasets/{body['dataset_id']}/preview")
    assert preview.status_code == 200
    cities = [row[0] for row in preview.json()["rows"]]
    assert "Zürich" in cities and "Málaga" in cities


def test_upload_csv_with_messy_headers_preserves_names(tmp_path):
    """Headers with spaces/symbols are common in the wild; they should survive
    ingestion so the agent can reference them."""
    csv_path = tmp_path / "messy.csv"
    csv_path.write_text(
        "Order ID,Sales ($),Discount %\nORD-1,100.5,0.2\nORD-2,250.0,0.1\n",
        encoding="utf-8",
    )
    with open(csv_path, "rb") as f:
        res = client.post("/datasets/upload", files={"file": ("messy.csv", f, "text/csv")})

    assert res.status_code == 200, res.text
    cols = {c["name"] for c in res.json()["tables"][0]["columns"]}
    assert cols == {"Order ID", "Sales ($)", "Discount %"}
