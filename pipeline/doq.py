import json
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from db import log_ingest, now_iso, store_raw, upsert_clinic, upsert_service
from pipeline.dedup import finalize_active, make_dedup_key

DOQ_API_URL = "https://api.doq.kz/api/v1/doctors/"
CITY_INFO = {
    3: {"name": "Алматы", "slug": "almaty"},
}


def build_doq_url(city: int = 3, service: int = 73, limit: int = 100) -> str:
    params = {
        "city": city,
        "expand": "clinic_branches,services",
        "limit": limit,
        "offset": 0,
        "service": service,
    }
    return f"{DOQ_API_URL}?{urlencode(params)}"


def import_doq_doctors(
    conn,
    city: int = 3,
    service: int = 73,
    limit: int = 100,
    max_pages: Optional[int] = None,
) -> dict:
    url = build_doq_url(city=city, service=service, limit=limit)
    stats = {"pages": 0, "doctors": 0, "services": 0, "clinics": 0}
    clinics_seen: set[str] = set()

    while url:
        payload = fetch_json(url)
        stats["pages"] += 1
        store_raw(conn, url, None, payload)
        for doctor in payload.get("results") or []:
            stats["doctors"] += 1
            stored, clinics = store_doq_doctor(conn, doctor, city, service, url)
            stats["services"] += stored
            clinics_seen.update(clinics)
        conn.commit()
        if max_pages is not None and stats["pages"] >= max_pages:
            break
        url = payload.get("next")

    finalize_active(conn)
    conn.commit()
    stats["clinics"] = len(clinics_seen)
    log_ingest(conn, "doq.kz", "api", "ok", json.dumps(stats, ensure_ascii=False))
    conn.commit()
    return stats


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "MedRate/1.0"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def store_doq_doctor(
    conn,
    doctor: dict[str, Any],
    city_id: int,
    target_service_id: int,
    api_url: str,
) -> tuple[int, set[str]]:
    branches = {branch["id"]: branch for branch in doctor.get("clinic_branches") or []}
    stored = 0
    clinics_seen: set[str] = set()
    for service_item in doctor.get("services") or []:
        service = service_item.get("service") or {}
        if service.get("id") != target_service_id:
            continue
        branch = branches.get(service_item.get("clinic_branch"))
        if not branch or not service.get("name"):
            continue
        source_url = service_source_url(service, city_id)
        clinic = build_clinic(branch, city_id, source_url)
        upsert_clinic(conn, clinic)
        clinics_seen.add(clinic["clinic_id"])
        row = build_service_row(doctor, service_item, service, clinic, source_url, api_url)
        upsert_service(conn, row)
        stored += 1
    return stored, clinics_seen


def build_clinic(branch: dict[str, Any], city_id: int, source_url: str) -> dict[str, Any]:
    location = branch.get("location") or {}
    phones = branch.get("phones") or []
    return {
        "clinic_id": f"doq_branch_{branch['id']}",
        "clinic_name": branch.get("name"),
        "city": CITY_INFO.get(city_id, {}).get("name", str(city_id)),
        "address": branch.get("address"),
        "phone": ", ".join(phones) if phones else branch.get("direct_call_phone"),
        "working_hours": None,
        "source_url": source_url,
        "lat": location.get("lat"),
        "lon": location.get("lng"),
        "rating": branch.get("feedback_score"),
        "online_booking": True,
    }


def build_service_row(
    doctor: dict[str, Any],
    service_item: dict[str, Any],
    service: dict[str, Any],
    clinic: dict[str, Any],
    source_url: str,
    api_url: str,
) -> dict[str, Any]:
    price = service_item.get("discount_price") or service_item.get("total") or service_item.get("price")
    service_name = service.get("name")
    category = map_doq_category(service.get("type"))
    service_name_norm = normalize_doq_service_name(service_name, category)
    dedup_key = make_dedup_key(
        clinic["clinic_id"],
        None,
        service_name_norm,
        f"{doctor.get('name')} {service_name}",
        "прием" if category == "consultation" else None,
    )
    nearest_slot = service_item.get("nearest_slot_datetime")
    notes = []
    if nearest_slot:
        notes.append(f"nearest_slot={nearest_slot}")
    if service_item.get("qualification_display"):
        notes.append(f"qualification={service_item['qualification_display']}")
    return {
        "clinic_id": clinic["clinic_id"],
        "clinic_name": clinic["clinic_name"],
        "city": clinic["city"],
        "address": clinic["address"],
        "phone": clinic["phone"],
        "working_hours": clinic["working_hours"],
        "lat": clinic["lat"],
        "lon": clinic["lon"],
        "rating": doctor.get("feedback_score") or service_item.get("feedback_score"),
        "online_booking": 1 if nearest_slot else 0,
        "doctor_name": doctor.get("name"),
        "reviews_count": doctor.get("feedback_count"),
        "experience_years": doctor.get("experience"),
        "service_name_raw": service_name,
        "service_name_norm": service_name_norm,
        "service_name_kz": None,
        "ref_service_id": None,
        "category": category,
        "price": price,
        "price_min": None,
        "price_max": service_item.get("price") if service_item.get("price") != price else None,
        "currency": "KZT",
        "unit": "прием" if category == "consultation" else None,
        "duration_days": None,
        "source_file": f"doq.kz doctor:{doctor.get('id')} service:{service_item.get('id')}",
        "source_page": None,
        "source_year": None,
        "source_url": source_url,
        "parsed_at": now_iso(),
        "is_active": 1,
        "confidence": 0.95,
        "flags": [],
        "notes": "; ".join([*notes, f"api_url={api_url}"]),
        "dedup_key": dedup_key,
    }


def map_doq_category(service_type: Optional[str]) -> str:
    if service_type == "initial-appointment":
        return "consultation"
    if service_type == "procedure":
        return "procedures"
    return "other"


def normalize_doq_service_name(service_name: str, category: str) -> str:
    if category == "consultation":
        return f"Прием врача: {service_name}"
    return service_name


def service_source_url(service: dict[str, Any], city_id: int) -> str:
    city_slug = CITY_INFO.get(city_id, {}).get("slug", str(city_id))
    service_slug = service.get("slug") or service.get("id")
    return f"https://doq.kz/doctors/{city_slug}/{service_slug}"
