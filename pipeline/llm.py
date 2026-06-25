"""Gemini calls: text + vision extraction and service-name canonicalization.

Uses Google's ``google-genai`` SDK with structured outputs (a Pydantic
``response_schema`` + ``response_mime_type="application/json"``) so the model
returns strictly-shaped JSON — the README's "strict JSON" guarantee. Gemini
accepts ``temperature=0`` for determinism.

Get a free API key at https://aistudio.google.com -> "Get API key", then set
GEMINI_API_KEY (or GOOGLE_API_KEY).
"""
from __future__ import annotations

import base64
import functools
import os
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from .normalize import CATEGORIES, FLAGS

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_MODEL = "gemini-2.5-flash"
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

def get_client() -> genai.Client:
    """Construct a Gemini client. Reads GEMINI_API_KEY / GOOGLE_API_KEY."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return genai.Client(api_key=key) if key else genai.Client()


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


def _generate(client, *, model, system, contents, schema, max_output_tokens, retries=2):
    """Call generate_content with JSON schema enforcement + backoff.

    Returns a parsed ``schema`` instance, or None if the model produced nothing
    usable. Thinking is disabled so the whole output budget goes to the JSON.
    """
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0,
        response_mime_type="application/json",
        response_schema=schema,
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            parsed = getattr(resp, "parsed", None)
            if parsed is None and getattr(resp, "text", None):
                parsed = schema.model_validate_json(resp.text)
            return parsed
        except errors.APIError as exc:
            last_exc = exc
            code = getattr(exc, "code", 500) or 500
            if code != 429 and code < 500:
                raise  # non-retryable client error
            time.sleep(min(2 ** attempt, 8))
    raise last_exc  # type: ignore[misc]


# --- extraction ----------------------------------------------------------------

def _build_contents(chunks: list[dict]) -> list:
    """Turn extractor chunks into Gemini content parts (text + images)."""
    parts: list = []
    text_parts: list[str] = []
    images = 0

    for chunk in chunks:
        if chunk["kind"] == "text" and chunk.get("text"):
            label = f"[page {chunk.get('page')}]" if chunk.get("page") is not None else ""
            text_parts.append(f"{label}\n{chunk['text']}".strip())

    if text_parts:
        parts.append(types.Part.from_text(text="DOCUMENT TEXT:\n\n" + "\n\n---\n\n".join(text_parts)))

    for chunk in chunks:
        if chunk["kind"] == "image" and chunk.get("image_b64"):
            if images >= MAX_IMAGES_PER_REQUEST:
                break
            page = chunk.get("page")
            parts.append(types.Part.from_text(text=f"IMAGE — page {page}:" if page is not None else "IMAGE:"))
            parts.append(
                types.Part.from_bytes(
                    data=base64.b64decode(chunk["image_b64"]),
                    mime_type=chunk.get("media_type", "image/png"),
                )
            )
            images += 1

    return parts


def extract_records(client, chunks: list[dict], *, clinic_name: str, source_file: str,
                    model: Optional[str] = None) -> list[dict]:
    """Extract structured price records from one document's chunks.

    Returns a list of plain dicts with provenance (clinic_name, clinic_id,
    source_file) attached. Returns [] if there's nothing to send.
    """
    contents = _build_contents(chunks)
    if not contents:
        return []

    model = model or get_model()
    system = load_prompt("extraction.txt") + _vocab_reminder()
    result: Optional[ExtractionResult] = _generate(
        client, model=model, system=system, contents=contents,
        schema=ExtractionResult, max_output_tokens=16000,
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
    contents = [types.Part.from_text(text="INPUT NAMES:\n" + "\n".join(f"- {n}" for n in names))]
    try:
        result: Optional[CanonicalMap] = _generate(
            client, model=model, system=system, contents=contents,
            schema=CanonicalMap, max_output_tokens=8000,
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
