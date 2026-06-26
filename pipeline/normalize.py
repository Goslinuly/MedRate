import re
from functools import lru_cache
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz, process

from config import CATEGORIES, REFERENCE_FILE, USD_KZT_RATE
from pipeline import llm

EXACT_CONFIDENCE = 0.97
FUZZY_ACCEPT_SCORE = 90
FUZZY_SHORTLIST_SCORE = 70
SHORTLIST_SIZE = 6

VALID_CATEGORIES = set(CATEGORIES)

SYNONYMS = {
    "оак": "общий анализ крови",
    "оам": "общий анализ мочи",
    "узи": "ультразвуковое исследование",
    "экг": "электрокардиография",
    "ээг": "электроэнцефалография",
    "кт": "компьютерная томография",
    "мрт": "магнитно-резонансная томография",
    "фгдс": "фиброгастродуоденоскопия",
    "ктг": "кардиотокография",
    "ктр": "кардиотокография",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_RANGE_RE = re.compile(r"(\d[\d\s .,]*)\s*[-–—]\s*(\d[\d\s .,]*)")
_NUMBER_RE = re.compile(r"\d[\d\s .,]*\d|\d")


def normalize_text(value: str) -> str:
    text = (value or "").lower().replace("ё", "е")
    text = _PUNCT_RE.sub(" ", text)
    tokens = [SYNONYMS.get(token, token) for token in _SPACE_RE.sub(" ", text).strip().split()]
    return " ".join(tokens)


class ReferenceIndex:
    def __init__(self, df: pd.DataFrame):
        self.entries: list[dict] = []
        self._exact: dict[str, int] = {}
        for ref_id, row in df.iterrows():
            name = str(row["Name_ru"]).strip()
            if not name:
                continue
            norm = normalize_text(name)
            entry = {
                "id": int(ref_id),
                "name": name,
                "specialty": str(row.get("Специальность") or "").strip(),
                "norm": norm,
            }
            self.entries.append(entry)
            self._exact.setdefault(norm, entry["id"])
        self._choices = {entry["id"]: entry["norm"] for entry in self.entries}
        self._by_id = {entry["id"]: entry for entry in self.entries}

    def exact_match(self, norm: str) -> Optional[int]:
        return self._exact.get(norm)

    def fuzzy(self, norm: str, limit: int = SHORTLIST_SIZE) -> list[tuple[dict, float]]:
        matches = process.extract(
            norm, self._choices, scorer=fuzz.token_set_ratio, limit=limit
        )
        return [(self._by_id[ref_id], score) for _, score, ref_id in matches]

    def get(self, ref_id: int) -> dict:
        return self._by_id[ref_id]


@lru_cache(maxsize=1)
def build_ref_index() -> ReferenceIndex:
    df = pd.read_excel(REFERENCE_FILE)
    return ReferenceIndex(df)


def _to_number(token: str) -> Optional[float]:
    cleaned = token.replace(" ", "").replace(" ", "")
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _detect_currency(raw: str, currency_raw: Optional[str]) -> tuple[str, list[str]]:
    blob = f"{raw} {currency_raw or ''}".lower()
    if "$" in blob or "usd" in blob or "долл" in blob:
        return "USD", []
    if any(token in blob for token in ("kzt", "тг", "тенге", "₸")):
        return "KZT", []
    return "KZT", ["currency_assumed"]


def parse_price(raw: Optional[str], currency_raw: Optional[str] = None) -> dict:
    result = {
        "price": None,
        "price_min": None,
        "price_max": None,
        "currency": "KZT",
        "flags": [],
    }
    if raw is None or not str(raw).strip():
        return result

    text = str(raw)
    currency, flags = _detect_currency(text, currency_raw)
    result["flags"].extend(flags)

    range_match = _RANGE_RE.search(text)
    if range_match:
        low, high = _to_number(range_match.group(1)), _to_number(range_match.group(2))
        result["price_min"], result["price_max"] = low, high
        result["flags"].append("price_is_range")
    else:
        numbers = [n for n in (_to_number(t) for t in _NUMBER_RE.findall(text)) if n is not None]
        if not numbers:
            return result
        if re.search(r"\bот\b|^\s*от", text.lower()):
            result["price_min"] = numbers[0]
            result["flags"].append("price_is_range")
        else:
            result["price"] = numbers[0]

    if currency == "USD":
        for key in ("price", "price_min", "price_max"):
            if result[key] is not None:
                result[key] = round(result[key] * USD_KZT_RATE, 2)
        result["flags"].append("kzt_converted_from_usd")
    result["currency"] = "KZT"
    return result


def map_category(category_guess: Optional[str]) -> str:
    guess = (category_guess or "").strip().lower()
    return guess if guess in VALID_CATEGORIES else "other"


def canonicalize(service_name_raw: str, ref_index: ReferenceIndex, conn=None) -> dict:
    norm = normalize_text(service_name_raw)
    if not norm:
        return _unmatched([])

    exact_id = ref_index.exact_match(norm)
    if exact_id is not None:
        entry = ref_index.get(exact_id)
        return _matched(entry, EXACT_CONFIDENCE)

    shortlist = ref_index.fuzzy(norm)
    if not shortlist:
        return _unmatched([])

    best_entry, best_score = shortlist[0]
    if best_score >= FUZZY_ACCEPT_SCORE:
        return _matched(best_entry, round(best_score / 100, 2))

    candidates = [
        {"id": entry["id"], "name": entry["name"], "specialty": entry["specialty"]}
        for entry, score in shortlist
        if score >= FUZZY_SHORTLIST_SCORE
    ]
    if candidates:
        decision = llm.match_service(service_name_raw, candidates, conn=conn)
        ref_id = decision.get("ref_service_id")
        if isinstance(ref_id, int) and ref_id in {c["id"] for c in candidates}:
            entry = ref_index.get(ref_id)
            confidence = float(decision.get("confidence") or 0.6)
            return _matched(entry, confidence)
    return _unmatched(candidates)


def _matched(entry: dict, confidence: float) -> dict:
    return {
        "service_name_norm": entry["name"],
        "ref_service_id": entry["id"],
        "confidence": confidence,
        "flags": [],
        "candidates": [],
    }


def _unmatched(candidates: list[dict]) -> dict:
    return {
        "service_name_norm": None,
        "ref_service_id": None,
        "confidence": 0.0,
        "flags": ["unmatched_service"],
        "candidates": candidates,
    }
