import base64
import hashlib
import json
import time
from functools import lru_cache
from typing import Optional

from google import genai
from google.genai import errors, types

from config import EXTRACT_MODEL, GOOGLE_API_KEY, NORMALIZE_MODEL, PROMPTS_DIR, VISION_MODEL
from db import cache_get, cache_set
from pipeline.models import RawDoc

MAX_RETRIES = 4
BASE_DELAY = 2.0
EXTRACT_MAX_TOKENS = 32768
NORMALIZE_MAX_TOKENS = 512
RETRYABLE_CODES = {500, 502, 503, 504}


@lru_cache(maxsize=None)
def _client() -> genai.Client:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set")
    return genai.Client(api_key=GOOGLE_API_KEY)


@lru_cache(maxsize=None)
def _prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _call(model: str, system: str, contents: list, max_tokens: int) -> str:
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
    )
    if model.startswith("gemini-2.5"):
        config.thinking_config = types.ThinkingConfig(thinking_budget=0)
    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            response = _client().models.generate_content(model=model, contents=contents, config=config)
            return response.text or ""
        except errors.APIError as error:
            last_error = error
            if getattr(error, "code", None) in RETRYABLE_CODES and attempt < MAX_RETRIES - 1:
                time.sleep(BASE_DELAY * (2**attempt))
                continue
            raise
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts: {last_error}")


def _strip_json(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    return cleaned.strip()


def _parse_array(text: str) -> list[dict]:
    cleaned = _strip_json(text)
    start = cleaned.find("[")
    if start == -1:
        return []
    end = cleaned.rfind("]")
    if end != -1:
        try:
            data = json.loads(cleaned[start : end + 1])
            return [item for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    return _salvage_array(cleaned, start)


def _salvage_array(cleaned: str, start: int) -> list[dict]:
    last_object = cleaned.rfind("}")
    if last_object == -1:
        return []
    try:
        data = json.loads(cleaned[start : last_object + 1] + "]")
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]


def _parse_object(text: str) -> dict:
    cleaned = _strip_json(text)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _doc_content(doc: RawDoc) -> list:
    if doc.is_image:
        image = types.Part.from_bytes(
            data=base64.b64decode(doc.image_b64), mime_type=doc.image_media_type
        )
        return [image, "Извлеки строки услуг из этого прайс-листа."]
    return [doc.text or ""]


def _cache_key(model: str, prompt: str, payload: str) -> str:
    digest = hashlib.sha256(f"{model}\n{prompt}\n{payload}".encode("utf-8")).hexdigest()
    return f"extract:{digest}"


def extract_rows(doc: RawDoc, conn=None) -> list[dict]:
    model = VISION_MODEL if doc.is_image else EXTRACT_MODEL
    system = _prompt("extraction.txt")
    payload = doc.image_b64 if doc.is_image else (doc.text or "")
    key = _cache_key(model, system, payload)
    if conn is not None:
        cached = cache_get(conn, key)
        if cached is not None:
            return cached
    rows = _parse_array(_call(model, system, _doc_content(doc), EXTRACT_MAX_TOKENS))
    if conn is not None:
        cache_set(conn, key, rows)
    return rows


def match_service(service_name_raw: str, candidates: list[dict], conn=None) -> dict:
    system = _prompt("normalization.txt")
    listing = "\n".join(
        f"{index}. id={c['id']} | {c['name']} | {c.get('specialty', '')}"
        for index, c in enumerate(candidates, start=1)
    )
    user = f"Исходное название: {service_name_raw}\n\nКандидаты:\n{listing}"
    key = _cache_key(NORMALIZE_MODEL, system, user)
    if conn is not None:
        cached = cache_get(conn, key)
        if cached is not None:
            return cached
    result = _parse_object(_call(NORMALIZE_MODEL, system, [user], NORMALIZE_MAX_TOKENS))
    if conn is not None:
        cache_set(conn, key, result)
    return result
