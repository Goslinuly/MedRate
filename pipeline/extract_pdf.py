from pathlib import Path

import pdfplumber
from pdf2image import convert_from_path

from pipeline.extract_image import encode_image
from pipeline.models import RawDoc, clinic_meta_from_filename

TEXT_CHARS_THRESHOLD = 60
PAGES_PER_TEXT_CHUNK = 3
SCAN_DPI = 200


def _page_text(page) -> str:
    table_text = ""
    try:
        tables = page.extract_tables()
        rows = ["\t".join(cell or "" for cell in row) for table in tables for row in table]
        table_text = "\n".join(rows)
    except Exception:
        table_text = ""
    plain = page.extract_text() or ""
    return plain if len(plain) >= len(table_text) else table_text


def extract_pdf(path: Path) -> list[RawDoc]:
    meta = clinic_meta_from_filename(path)
    docs: list[RawDoc] = []
    text_buffer: list[tuple[int, str]] = []
    scan_pages: list[int] = []

    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = _page_text(page)
            if len(text.strip()) >= TEXT_CHARS_THRESHOLD:
                text_buffer.append((number, text))
            else:
                scan_pages.append(number)

    docs.extend(_flush_text(path, meta, text_buffer))
    docs.extend(_render_scans(path, meta, scan_pages))
    return docs


def _flush_text(path: Path, meta: dict, pages: list[tuple[int, str]]) -> list[RawDoc]:
    docs = []
    for start in range(0, len(pages), PAGES_PER_TEXT_CHUNK):
        chunk = pages[start : start + PAGES_PER_TEXT_CHUNK]
        body = "\n\n".join(f"[Страница {number}]\n{text}" for number, text in chunk)
        docs.append(
            RawDoc(
                source_file=path.name,
                kind="pdf_text",
                source_page=chunk[0][0],
                text=body,
                **meta,
            )
        )
    return docs


def _render_scans(path: Path, meta: dict, pages: list[int]) -> list[RawDoc]:
    docs = []
    for number in pages:
        images = convert_from_path(path, dpi=SCAN_DPI, first_page=number, last_page=number)
        if not images:
            continue
        payload, media_type = encode_image(images[0])
        docs.append(
            RawDoc(
                source_file=path.name,
                kind="pdf_scan",
                source_page=number,
                image_b64=payload,
                image_media_type=media_type,
                **meta,
            )
        )
    return docs
