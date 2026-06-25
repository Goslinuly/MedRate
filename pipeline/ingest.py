"""Ingest: unzip / walk a folder, dispatch each file to the right extractor.

Yields a flat list of documents, each with its source path, a guessed clinic
name (the immediate parent folder, or the filename stem), and the extractor
chunks ready for the LLM.
"""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from . import extract_docx, extract_excel, extract_image, extract_pdf

# Map extensions to their extractor's `extract(path) -> list[chunk]` function.
_EXTRACTORS = {
    ".xlsx": extract_excel.extract,
    ".xls": extract_excel.extract,
    ".csv": extract_excel.extract,
    ".pdf": extract_pdf.extract,
    ".docx": extract_docx.extract,
    ".png": extract_image.extract,
    ".jpg": extract_image.extract,
    ".jpeg": extract_image.extract,
}

SUPPORTED_EXTENSIONS = sorted(_EXTRACTORS.keys())


def _clinic_name_for(file_path: Path, root: Path) -> str:
    """Best-effort clinic name: first folder under the root, else the file stem."""
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        rel = file_path
    parts = rel.parts
    if len(parts) > 1:
        return parts[0]
    return file_path.stem


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in _EXTRACTORS and not path.name.startswith("."):
            yield path


def ingest(path: str) -> list[dict]:
    """Ingest a zip archive or a folder. Returns a list of document dicts:

        {clinic_name, source_file, ftype, chunks, error}

    `error` is set (and `chunks` empty) if extraction of that file failed.
    """
    src = Path(path)
    docs: list[dict] = []

    if src.is_file() and src.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="medrate_"))
        with zipfile.ZipFile(src) as zf:
            zf.extractall(tmp)
        root = tmp
    elif src.is_dir():
        root = src
    elif src.is_file():
        # A single supported file.
        root = src.parent
    else:
        raise FileNotFoundError(path)

    files = [src] if (src.is_file() and src.suffix.lower() != ".zip") else list(_iter_files(root))

    for file_path in files:
        if file_path.suffix.lower() not in _EXTRACTORS:
            continue
        doc = {
            "clinic_name": _clinic_name_for(file_path, root),
            "source_file": file_path.name,
            "ftype": file_path.suffix.lower().lstrip("."),
            "chunks": [],
            "error": None,
        }
        try:
            doc["chunks"] = _EXTRACTORS[file_path.suffix.lower()](str(file_path))
        except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
            doc["error"] = f"{type(exc).__name__}: {exc}"
        docs.append(doc)

    return docs
