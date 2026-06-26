import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RawDoc:
    source_file: str
    kind: str
    source_page: Optional[int] = None
    sheet: Optional[str] = None
    text: Optional[str] = None
    image_b64: Optional[str] = None
    image_media_type: Optional[str] = None
    clinic_id: Optional[str] = None
    clinic_name: Optional[str] = None
    source_year: Optional[int] = None
    context: dict = field(default_factory=dict)

    @property
    def is_image(self) -> bool:
        return self.image_b64 is not None


_CLINIC_RE = re.compile(r"[Кк]линика[\s_]*(\d+)")
_YEAR_RE = re.compile(r"(20\d{2})")


def clinic_meta_from_filename(path: Path) -> dict:
    name = path.stem
    clinic_match = _CLINIC_RE.search(name)
    year_match = _YEAR_RE.search(name)
    number = clinic_match.group(1) if clinic_match else None
    return {
        "clinic_id": f"clinic_{number}" if number else f"clinic_{_slug(name)}",
        "clinic_name": f"Клиника {number}" if number else name,
        "source_year": int(year_match.group(1)) if year_match else None,
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "unknown"
