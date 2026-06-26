from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from pipeline.models import RawDoc, clinic_meta_from_filename

LINES_PER_CHUNK = 150


def _iter_blocks(document: DocumentType):
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _document_lines(document: DocumentType) -> list[str]:
    lines = []
    for block in _iter_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                lines.append(text)
        else:
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
    return lines


def extract_docx(path: Path) -> list[RawDoc]:
    meta = clinic_meta_from_filename(path)
    lines = _document_lines(Document(str(path)))
    docs = []
    for index, start in enumerate(range(0, len(lines), LINES_PER_CHUNK), start=1):
        chunk = lines[start : start + LINES_PER_CHUNK]
        if not chunk:
            continue
        docs.append(
            RawDoc(
                source_file=path.name,
                kind="docx",
                source_page=index,
                text="\n".join(chunk),
                **meta,
            )
        )
    return docs
