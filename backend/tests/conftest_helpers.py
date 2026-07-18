"""Helpers for building small test fixtures on the fly."""
from pathlib import Path

import pandas as pd


def make_csv(tmp_path: Path, name: str = "sales.csv") -> Path:
    p = tmp_path / name
    p.write_text(
        "region,product,units,revenue\n"
        "North,Widget,100,2500.0\n"
        "South,Widget,150,3750.0\n"
        "North,Gadget,80,4000.0\n"
        "South,Gadget,60,3000.0\n",
        encoding="utf-8",
    )
    return p


def make_excel(tmp_path: Path, name: str = "book.xlsx") -> Path:
    p = tmp_path / name
    with pd.ExcelWriter(p, engine="openpyxl") as writer:
        pd.DataFrame({"City": ["A", "B"], "Pop": [10, 20]}).to_excel(
            writer, sheet_name="Cities", index=False
        )
        pd.DataFrame({"Item": ["x", "y"], "Qty": [1, 2]}).to_excel(
            writer, sheet_name="Items", index=False
        )
    return p
