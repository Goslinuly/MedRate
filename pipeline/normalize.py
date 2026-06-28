import json
import re
from pathlib import Path
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz, process

from config import CATEGORIES, CURRENCY_RATES, LLM_TIEBREAK, REFERENCE_DIR, REFERENCE_FILE
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
    "консультация": "прием",
    "консультативный": "прием",
    "осмотр": "прием",
    "консультирование": "прием",
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


def _split_synonyms(value) -> list[str]:
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [part.strip() for part in re.split(r"[;,|/]", str(value)) if part.strip()]


def _find_column(columns, *candidates) -> Optional[str]:
    lookup = {str(c).strip().lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    return None


def active_reference_path() -> Path:
    """The catalogue currently in force — an uploaded JSON takes priority over the XLSX."""
    json_path = REFERENCE_DIR / "services.json"
    if json_path.exists():
        return json_path
    return REFERENCE_FILE


def load_reference_rows(path: Optional[Path] = None) -> list[dict]:
    """Load the target catalogue from XLSX or JSON into a uniform row shape.

    Supported optional columns/keys: synonyms, category, specialty/icd.
    """
    path = Path(path) if path is not None else active_reference_path()
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("services", [])
        rows = []
        for index, item in enumerate(items):
            name = str(item.get("service_name") or item.get("name") or "").strip()
            if not name:
                continue
            sid = item.get("service_id", index)
            rows.append({
                "id": int(sid) if str(sid).isdigit() else index,
                "name": name,
                "specialty": str(item.get("specialty") or "").strip(),
                "category": str(item.get("category") or "").strip().lower(),
                "synonyms": _split_synonyms(item.get("synonyms")),
            })
        return rows

    df = pd.read_excel(path)
    name_col = _find_column(df.columns, "Name_ru", "service_name", "name", "наименование")
    syn_col = _find_column(df.columns, "synonyms", "синонимы")
    cat_col = _find_column(df.columns, "category", "категория")
    spec_col = _find_column(df.columns, "Специальность", "specialty", "специальность")
    if name_col is None:
        return []
    rows = []
    for ref_id, row in df.iterrows():
        name = str(row[name_col]).strip()
        if not name or name.lower() == "nan":
            continue
        rows.append({
            "id": int(ref_id),
            "name": name,
            "specialty": str(row[spec_col]).strip() if spec_col else "",
            "category": str(row[cat_col]).strip().lower() if cat_col else "",
            "synonyms": _split_synonyms(row[syn_col]) if syn_col else [],
        })
    return rows


class ReferenceIndex:
    def __init__(self, rows: list[dict]):
        self.entries: list[dict] = []
        self._exact: dict[str, int] = {}
        for row in rows:
            name = str(row["name"]).strip()
            if not name:
                continue
            norm = normalize_text(name)
            entry = {
                "id": int(row["id"]),
                "name": name,
                "specialty": row.get("specialty", ""),
                "category": row.get("category", ""),
                "synonyms": row.get("synonyms", []),
                "norm": norm,
            }
            self.entries.append(entry)
            self._exact.setdefault(norm, entry["id"])
            for synonym in entry["synonyms"]:
                syn_norm = normalize_text(synonym)
                if syn_norm:
                    self._exact.setdefault(syn_norm, entry["id"])
        self._choices = {entry["id"]: entry["norm"] for entry in self.entries}
        self._by_id = {entry["id"]: entry for entry in self.entries}

    def exact_match(self, norm: str) -> Optional[int]:
        return self._exact.get(norm)

    def fuzzy(self, norm: str, limit: int = SHORTLIST_SIZE) -> list[tuple[dict, float]]:
        matches = process.extract(
            norm, self._choices, scorer=fuzz.token_set_ratio, limit=limit
        )
        return [(self._by_id[ref_id], score) for _, score, ref_id in matches]

    def search(self, query: str, limit: int = 20) -> list[dict]:
        norm = normalize_text(query)
        if not norm:
            return []
        matches = process.extract(norm, self._choices, scorer=fuzz.token_set_ratio, limit=limit)
        return [self._by_id[ref_id] for _, score, ref_id in matches if score > 50]

    def get(self, ref_id: int) -> dict:
        return self._by_id[ref_id]


def build_ref_index(conn=None) -> ReferenceIndex:
    rows = load_reference_rows()
    if conn is not None:
        from db import reference_extra_rows
        rows = rows + reference_extra_rows(conn)
    return ReferenceIndex(rows)


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
    if "₽" in blob or "rub" in blob or "руб" in blob or "рос" in blob:
        return "RUB", []
    if any(token in blob for token in ("kzt", "тг", "тенге", "₸")):
        return "KZT", []
    return "KZT", ["currency_assumed"]


def parse_price(raw: Optional[str], currency_raw: Optional[str] = None) -> dict:
    result = {
        "price": None,
        "price_min": None,
        "price_max": None,
        "price_original": None,
        "currency": "KZT",
        "currency_original": None,
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

    result["currency_original"] = currency
    result["price_original"] = result["price"] if result["price"] is not None else result["price_min"]
    if currency in CURRENCY_RATES:
        rate = CURRENCY_RATES[currency]
        for key in ("price", "price_min", "price_max"):
            if result[key] is not None:
                result[key] = round(result[key] * rate, 2)
        result["flags"].append(f"kzt_converted_from_{currency.lower()}")
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
    if candidates and LLM_TIEBREAK:
        decision = _safe_match(service_name_raw, candidates, conn)
        ref_id = decision.get("ref_service_id")
        if isinstance(ref_id, int) and ref_id in {c["id"] for c in candidates}:
            entry = ref_index.get(ref_id)
            confidence = float(decision.get("confidence") or 0.6)
            return _matched(entry, confidence)
    return _unmatched(candidates)


def _safe_match(service_name_raw: str, candidates: list[dict], conn) -> dict:
    try:
        return llm.match_service(service_name_raw, candidates, conn=conn)
    except Exception:
        return {}


def _matched(entry: dict, confidence: float) -> dict:
    category = entry.get("category") or ""
    return {
        "service_name_norm": entry["name"],
        "ref_service_id": entry["id"],
        "category": category if category in VALID_CATEGORIES else None,
        "confidence": confidence,
        "flags": [],
        "candidates": [],
    }


def _unmatched(candidates: list[dict]) -> dict:
    return {
        "service_name_norm": None,
        "ref_service_id": None,
        "category": None,
        "confidence": 0.0,
        "flags": ["unmatched_service"],
        "candidates": candidates,
    }
