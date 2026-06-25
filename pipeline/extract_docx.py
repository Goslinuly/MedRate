"""Word (.docx) -> text chunks (paragraphs + tables)."""
from __future__ import annotations

from docx import Document


def extract(path: str) -> list[dict]:
    doc = Document(path)
    parts: list[str] = []

    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())

    for t_idx, table in enumerate(doc.tables, start=1):
        parts.append(f"# Table {t_idx}")
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))

    text = "\n".join(parts)
    if not text.strip():
        return []
    return [{"kind": "text", "text": text, "page": 1}]
