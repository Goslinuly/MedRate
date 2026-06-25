"""Excel / CSV -> table text chunks.

Each sheet becomes one text chunk so the LLM sees structure without us guessing
which row is the header (it reads the whole grid the way a human would).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def _frame_to_text(df: pd.DataFrame) -> str:
    # Keep it dense and readable; don't drop rows — headers may be on any row.
    df = df.fillna("")
    return df.to_csv(index=False)


def extract(path: str) -> list[dict]:
    p = Path(path)
    chunks: list[dict] = []

    if p.suffix.lower() == ".csv":
        try:
            df = pd.read_csv(p, header=None, dtype=str, keep_default_na=False)
        except Exception:
            df = pd.read_csv(p, header=None, dtype=str, keep_default_na=False,
                             sep=";", encoding="utf-8", engine="python")
        chunks.append({"kind": "text", "text": _frame_to_text(df), "page": 1})
        return chunks

    # .xlsx / .xls — read every sheet.
    sheets = pd.read_excel(p, sheet_name=None, header=None, dtype=str)
    for i, (name, df) in enumerate(sheets.items(), start=1):
        text = f"# Sheet: {name}\n{_frame_to_text(df)}"
        chunks.append({"kind": "text", "text": text, "page": i})
    return chunks
