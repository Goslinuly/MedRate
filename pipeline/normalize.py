"""Normalize extracted records: prices, currency, categories, flags.

Operates on the raw dicts returned by the LLM (see pipeline.llm). Cleans values
the model may have left messy, validates them against fixed vocabularies, and
fills derived fields. Never invents numbers — unreadable values stay ``None``.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Fixed category vocabulary (README -> Data schema).
CATEGORIES = [
    "consultation",
    "lab tests",
    "ultrasound",
    "CT/MRI",
    "x-ray/fluorography",
    "dentistry",
    "physiotherapy",
    "surgery",
    "procedures",
    "vaccination",
    "inpatient",
    "other",
]

# Fixed quality-signal vocabulary.
FLAGS = [
    "low_quality_scan",
    "ambiguous_price",
    "name_uncertain",
    "price_is_range",
    "currency_assumed",
    "multi_column_layout",
    "non_price_row",
]

DEFAULT_CURRENCY = "KZT"

_NUM_RE = re.compile(r"[-+]?\d[\d\s.,]*")


def _to_number(value: Any) -> Optional[float]:
    """Coerce a price-ish value to a float, or None if not a clean number.

    Handles thousands separators ("12 000", "12.000,50", "12,000") without
    guessing — anything we can't parse confidently becomes None.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    match = _NUM_RE.search(value)
    if not match:
        return None
    raw = match.group(0).strip().replace(" ", "")

    # Decide which separator is the decimal point.
    if "," in raw and "." in raw:
        # The rightmost separator is the decimal point.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        # Treat as decimal only if it looks like "123,45"; else thousands.
        if re.fullmatch(r"\d+,\d{1,2}", raw):
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "." in raw:
        # Dot-only is ambiguous. KZT prices have no sub-unit in practice, so a
        # dot with 3+ trailing digits (or several dots) is a thousands separator;
        # "123.45" stays a decimal.
        if raw.count(".") > 1 or re.fullmatch(r"\d+\.\d{3,}", raw):
            raw = raw.replace(".", "")

    try:
        return float(raw)
    except ValueError:
        return None


def _clean_flags(flags: Any) -> list[str]:
    if not isinstance(flags, list):
        return []
    seen: list[str] = []
    for flag in flags:
        if flag in FLAGS and flag not in seen:
            seen.append(flag)
    return seen


def normalize_record(record: dict) -> dict:
    """Return a cleaned copy of ``record`` with validated fields and flags."""
    out = dict(record)
    flags = _clean_flags(out.get("flags"))

    # --- category ---
    category = (out.get("category") or "").strip()
    if category not in CATEGORIES:
        category = "other"
    out["category"] = category

    # --- prices ---
    price = _to_number(out.get("price"))
    price_min = _to_number(out.get("price_min"))
    price_max = _to_number(out.get("price_max"))

    if price_min is not None and price_max is not None:
        if price_min > price_max:
            price_min, price_max = price_max, price_min
        if "price_is_range" not in flags:
            flags.append("price_is_range")
        if price is None:
            price = price_min
    elif price is not None and price_min is None and price_max is None:
        price_min = price_max = price

    out["price"] = price
    out["price_min"] = price_min
    out["price_max"] = price_max

    # --- currency ---
    currency = (out.get("currency") or "").strip().upper()
    if not currency:
        currency = DEFAULT_CURRENCY
        if "currency_assumed" not in flags:
            flags.append("currency_assumed")
    out["currency"] = currency

    # --- confidence ---
    try:
        conf = float(out.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.0
    out["confidence"] = max(0.0, min(1.0, conf))

    # Rows with no usable price and no value are suspect.
    if price is None and price_min is None and "non_price_row" not in flags:
        if "ambiguous_price" not in flags:
            flags.append("ambiguous_price")

    out["flags"] = flags
    return out


def normalize_all(records: list[dict]) -> list[dict]:
    return [normalize_record(r) for r in records]
