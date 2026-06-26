import re
from pathlib import Path

import pandas as pd

from pipeline.models import RawDoc, clinic_meta_from_filename

HEADER_KEYWORDS = re.compile(
    r"наимен|услуг|цена|стоимост|тариф|\bкод\b|ед\.?\s*изм|price|name|cost",
    re.IGNORECASE,
)

HEADER_SCAN_ROWS = 40
ROWS_PER_CHUNK = 120


def _engine_for(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        return {"engine": "xlrd"}
    return {"engine": "openpyxl"}


def _read_sheets(path: Path) -> list[tuple[str, pd.DataFrame]]:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
        return [("csv", df)]
    book = pd.read_excel(path, sheet_name=None, header=None, dtype=str, **_engine_for(path))
    return [(name, df.fillna("")) for name, df in book.items()]


def _score_header(row: pd.Series) -> int:
    non_empty = [str(v).strip() for v in row if str(v).strip()]
    if len(non_empty) < 2:
        return 0
    return sum(1 for value in non_empty if HEADER_KEYWORDS.search(value))


def _detect_header_row(df: pd.DataFrame) -> int:
    best_row, best_score = 0, 0
    for index in range(min(HEADER_SCAN_ROWS, len(df))):
        score = _score_header(df.iloc[index])
        if score > best_score:
            best_row, best_score = index, score
    return best_row


def _rows_to_lines(header: list[str], body: pd.DataFrame) -> list[str]:
    columns = [c if c else f"col{i}" for i, c in enumerate(header)]
    lines = [" | ".join(columns)]
    for _, row in body.iterrows():
        cells = [str(v).strip() for v in row.tolist()]
        if not any(cells):
            continue
        lines.append(" | ".join(cells))
    return lines


def extract_excel(path: Path) -> list[RawDoc]:
    meta = clinic_meta_from_filename(path)
    docs: list[RawDoc] = []
    page = 0
    for sheet_name, df in _read_sheets(path):
        if df.empty:
            continue
        header_row = _detect_header_row(df)
        header = [str(v).strip() for v in df.iloc[header_row].tolist()]
        body = df.iloc[header_row + 1 :]
        lines = _rows_to_lines(header, body)
        if len(lines) <= 1:
            continue
        header_line, data_lines = lines[0], lines[1:]
        for start in range(0, len(data_lines), ROWS_PER_CHUNK):
            page += 1
            chunk = data_lines[start : start + ROWS_PER_CHUNK]
            docs.append(
                RawDoc(
                    source_file=path.name,
                    kind="excel",
                    source_page=page,
                    sheet=sheet_name,
                    text="\n".join([header_line, *chunk]),
                    **meta,
                )
            )
    return docs
