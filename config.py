import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SAMPLES_DIR = DATA_DIR / "samples"
REFERENCE_FILE = DATA_DIR / "reference" / "services.xlsx"
PROMPTS_DIR = BASE_DIR / "prompts"
DB_PATH = BASE_DIR / "medrate.db"
EXPORT_PATH = BASE_DIR / "output.xlsx"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
EXTRACT_MODEL = os.getenv("MEDRATE_EXTRACT_MODEL", "claude-sonnet-4-6")
VISION_MODEL = os.getenv("MEDRATE_VISION_MODEL", "claude-sonnet-4-6")
NORMALIZE_MODEL = os.getenv("MEDRATE_NORMALIZE_MODEL", "claude-opus-4-8")
CATEGORY_MODEL = os.getenv("MEDRATE_CATEGORY_MODEL", "claude-haiku-4-5-20251001")

USD_KZT_RATE = float(os.getenv("USD_KZT_RATE", "470"))

ACTIVE_MAX_AGE_DAYS = 30
RAW_RETENTION_DAYS = 90

CATEGORIES = [
    "consultation",
    "lab_tests",
    "ultrasound",
    "ct_mri",
    "xray",
    "dentistry",
    "physiotherapy",
    "surgery",
    "procedures",
    "vaccination",
    "inpatient",
    "other",
]

COARSE_CATEGORIES = {
    "consultation": "Прием врача",
    "lab_tests": "Лаборатория",
    "ultrasound": "Диагностика",
    "ct_mri": "Диагностика",
    "xray": "Диагностика",
    "dentistry": "Стоматология",
    "physiotherapy": "Процедуры",
    "surgery": "Хирургия",
    "procedures": "Процедуры",
    "vaccination": "Процедуры",
    "inpatient": "Стационар",
    "other": "Прочее",
}

KNOWN_FLAGS = {
    "low_quality_scan",
    "ambiguous_price",
    "name_uncertain",
    "price_is_range",
    "currency_assumed",
    "multi_column_layout",
    "non_price_row",
    "unmatched_service",
    "kzt_converted_from_usd",
}


def coarse_category(category: str) -> str:
    return COARSE_CATEGORIES.get(category or "other", "Прочее")
