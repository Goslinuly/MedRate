"""Claude calls: text + vision extraction and service-name canonicalization.

Uses the official Anthropic SDK with structured outputs (``messages.parse``) so
the model returns strictly-shaped JSON — the README's "strict JSON" guarantee.
Note: current Claude models (Opus 4.8) don't accept a ``temperature`` parameter;
determinism comes from the enforced schema, not a sampling setting.
"""
from __future__ import annotations

import functools
import os
import time
from pathlib import Path
from typing import Optional

import anthropic
from pydantic import BaseModel

from .normalize import CATEGORIES, FLAGS

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_MODEL = "claude-opus-4-8"
# Cap images per request so a big scanned PDF doesn't blow the request size.
MAX_IMAGES_PER_REQUEST = 20


# --- structured-output schemas -------------------------------------------------

class PriceRecord(BaseModel):
    service_name_raw: str
    service_name_normalized: Optional[str] = None
    service_name_kz: Optional[str] = None
    category: str
    price: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = None
    unit: Optional[str] = None
    confidence: float
    flags: list[str]
    notes: Optional[str] = None


class ExtractionResult(BaseModel):
    records: list[PriceRecord]


class NameMapping(BaseModel):
    from_name: str
    to_name: str


class CanonicalMap(BaseModel):
    mappings: list[NameMapping]


# --- client / prompts ----------------------------------------------------------

def get_client() -> anthropic.Anthropic:
    """Construct a client. Reads ANTHROPIC_API_KEY from the environment."""
    return anthropic.Anthropic()


def get_model() -> str:
    return os.environ.get("MODEL", DEFAULT_MODEL)


@functools.lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _vocab_reminder() -> str:
    return (
        "\n\nAllowed categories: "
        + ", ".join(CATEGORIES)
        + ".\nAllowed flags: "
        + ", ".join(FLAGS)
        + "."
    )


def _parse_with_retry(client, *, model, max_tokens, system, content, schema, retries=2):
    """Call messages.parse with simple exponential backoff on transient errors."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_format=schema,
            )
            if resp.stop_reason == "refusal":
                raise RuntimeError("model refused the request")
            return resp.parsed_output
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            last_exc = exc
            status = getattr(exc, "status_code", 500)
            if isinstance(exc, anthropic.APIStatusError) and status < 500 and status != 429:
                raise  # non-retryable client error
            time.sleep(min(2 ** attempt, 8))
    raise last_exc  # type: ignore[misc]


# --- extraction ----------------------------------------------------------------

def _build_content(chunks: list[dict]) -> list[dict]:
    """Turn extractor chunks into Claude content blocks (text + images)."""
    blocks: list[dict] = []
    text_parts: list[str] = []
    images = 0

    for chunk in chunks:
        if chunk["kind"] == "text" and chunk.get("text"):
            label = f"[page {chunk.get('page')}]" if chunk.get("page") is not None else ""
            text_parts.append(f"{label}\n{chunk['text']}".strip())

    if text_parts:
        blocks.append({"type": "text", "text": "DOCUMENT TEXT:\n\n" + "\n\n---\n\n".join(text_parts)})

    for chunk in chunks:
        if chunk["kind"] == "image" and chunk.get("image_b64"):
            if images >= MAX_IMAGES_PER_REQUEST:
                break
            page = chunk.get("page")
            blocks.append({"type": "text", "text": f"IMAGE — page {page}:" if page is not None else "IMAGE:"})
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": chunk.get("media_type", "image/png"),
                        "data": chunk["image_b64"],
                    },
                }
            )
            images += 1

    return blocks


def extract_records(client, chunks: list[dict], *, clinic_name: str, source_file: str,
                    model: Optional[str] = None) -> list[dict]:
    """Extract structured price records from one document's chunks.

    Returns a list of plain dicts with provenance (clinic_name, clinic_id,
    source_file) attached. Returns [] if there's nothing to send.
    """
    content = _build_content(chunks)
    if not content:
        return []

    model = model or get_model()
    system = load_prompt("extraction.txt") + _vocab_reminder()
    result: ExtractionResult = _parse_with_retry(
        client, model=model, max_tokens=16000, system=system,
        content=content, schema=ExtractionResult,
    )
    if result is None:
        return []

    clinic_id = slugify(clinic_name)
    out: list[dict] = []
    for rec in result.records:
        d = rec.model_dump()
        d["clinic_name"] = clinic_name
        d["clinic_id"] = clinic_id
        d["source_file"] = source_file
        d["source_page"] = None
        out.append(d)
    return out


# --- canonicalization ----------------------------------------------------------

def canonicalize_names(client, names: list[str], *, model: Optional[str] = None) -> dict[str, str]:
    """Map distinct service names to canonical Russian names. Identity on failure."""
    names = [n for n in dict.fromkeys(names) if n]  # dedupe, keep order
    if not names:
        return {}

    model = model or get_model()
    system = load_prompt("normalization.txt")
    content = [{"type": "text", "text": "INPUT NAMES:\n" + "\n".join(f"- {n}" for n in names)}]
    try:
        result: CanonicalMap = _parse_with_retry(
            client, model=model, max_tokens=8000, system=system,
            content=content, schema=CanonicalMap,
        )
    except Exception:
        return {n: n for n in names}
    if result is None:
        return {n: n for n in names}

    mapping = {m.from_name: m.to_name for m in result.mappings if m.from_name and m.to_name}
    # Ensure every input has an entry (fall back to itself).
    return {n: mapping.get(n, n) for n in names}


def slugify(text: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unknown"
