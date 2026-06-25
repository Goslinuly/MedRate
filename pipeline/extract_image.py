"""Image files -> base64 image chunks for vision extraction."""
from __future__ import annotations

import base64
from pathlib import Path

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def media_type_for(path: str) -> str:
    return _MEDIA_TYPES.get(Path(path).suffix.lower(), "image/png")


def encode(path: str) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")


def extract(path: str) -> list[dict]:
    return [
        {
            "kind": "image",
            "image_b64": encode(path),
            "media_type": media_type_for(path),
            "page": 1,
        }
    ]
