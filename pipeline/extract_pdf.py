"""PDF -> text or rendered-page images.

Detects whether a page has a usable text layer (pdfplumber). Pages with little
or no extractable text are treated as scans and rendered to images (pdf2image +
poppler) for vision extraction.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import pdfplumber

# A page with fewer than this many characters of extractable text is treated as
# a scan and rendered to an image instead.
_MIN_TEXT_CHARS = 40
_RENDER_DPI = 200


def _render_pages_to_images(path: str, page_numbers: list[int]) -> dict[int, str]:
    """Render specific 1-indexed pages to base64 PNGs. Empty dict if unavailable."""
    try:
        from pdf2image import convert_from_path
    except Exception:
        return {}

    out: dict[int, str] = {}
    for n in page_numbers:
        try:
            images = convert_from_path(path, dpi=_RENDER_DPI, first_page=n, last_page=n)
        except Exception:
            continue
        if not images:
            continue
        buf = io.BytesIO()
        images[0].save(buf, format="PNG")
        out[n] = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return out


def extract(path: str) -> list[dict]:
    chunks: list[dict] = []
    scan_pages: list[int] = []

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if len(text) >= _MIN_TEXT_CHARS:
                chunks.append({"kind": "text", "text": text, "page": i})
            else:
                scan_pages.append(i)

    if scan_pages:
        rendered = _render_pages_to_images(str(Path(path)), scan_pages)
        for n in scan_pages:
            if n in rendered:
                chunks.append({
                    "kind": "image",
                    "image_b64": rendered[n],
                    "media_type": "image/png",
                    "page": n,
                })

    return chunks
