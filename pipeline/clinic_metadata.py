import json
from functools import lru_cache

from config import CLINICS_FILE


@lru_cache(maxsize=1)
def load_clinic_metadata() -> dict[str, dict]:
    if not CLINICS_FILE.exists():
        return {}
    with CLINICS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return {item["clinic_id"]: item for item in data.get("clinics", [])}


def clinic_metadata(clinic_id: str) -> dict:
    return load_clinic_metadata().get(clinic_id, {})
