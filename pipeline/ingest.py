import tempfile
import zipfile
from pathlib import Path
from typing import Literal

import pdfplumber

from pipeline.extract_docx import extract_docx
from pipeline.extract_excel import extract_excel
from pipeline.extract_image import extract_image
from pipeline.extract_pdf import extract_pdf
from pipeline.models import RawDoc

Kind = Literal["excel", "csv", "pdf_text", "pdf_scan", "docx", "image"]

SUPPORTED_SUFFIXES = {".xlsx", ".xls", ".csv", ".pdf", ".docx", ".png", ".jpg", ".jpeg"}
EXCEL_SUFFIXES = {".xlsx", ".xls", ".csv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PDF_TEXT_PROBE_PAGES = 3
PDF_TEXT_MIN_CHARS = 60


def _safe_extract(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = _decode_name(member)
            destination = (target / Path(name).name).resolve()
            if not str(destination).startswith(str(target.resolve())):
                continue
            with archive.open(member) as source, open(destination, "wb") as out:
                out.write(source.read())


def _decode_name(member: zipfile.ZipInfo) -> str:
    if member.flag_bits & 0x800:
        return member.filename
    try:
        return member.filename.encode("cp437").decode("cp866")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return member.filename


def unzip_or_walk(path: Path) -> list[Path]:
    path = Path(path)
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES)
    if path.suffix.lower() == ".zip":
        target = Path(tempfile.mkdtemp(prefix="medrate_"))
        _safe_extract(path, target)
        return sorted(p for p in target.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES)
    return [path]


def detect_kind(path: Path) -> Kind:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return "docx"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in EXCEL_SUFFIXES:
        return "csv" if suffix == ".csv" else "excel"
    if suffix == ".pdf":
        return "pdf_text" if _pdf_has_text_layer(path) else "pdf_scan"
    raise ValueError(f"unsupported file type: {path.name}")


def _pdf_has_text_layer(path: Path) -> bool:
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:PDF_TEXT_PROBE_PAGES]:
            if len((page.extract_text() or "").strip()) >= PDF_TEXT_MIN_CHARS:
                return True
    return False


def ingest(path: Path) -> list[RawDoc]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    if suffix in IMAGE_SUFFIXES:
        return extract_image(path)
    if suffix in EXCEL_SUFFIXES:
        return extract_excel(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    raise ValueError(f"unsupported file type: {path.name}")
