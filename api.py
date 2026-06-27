import json
from typing import Optional

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import db

try:
    from scalar_fastapi import get_scalar_api_reference
except ImportError:
    get_scalar_api_reference = None

DESCRIPTION = """
API нормализованной базы прайсов клиник-партнёров.

Архив прайс-листов (PDF / DOCX / XLSX / сканы) разбирается в единую базу: каждая
строка прайса привязывается к услуге справочника, что позволяет искать
**кто оказывает услугу и по какой цене**.

* **Услуги** — позиции справочника с числом партнёров и диапазоном цен.
* **Партнёры** — клиники и их прайсы.
* **Поиск** — полнотекстовый поиск по услугам и партнёрам.
* **Сопоставление** — несопоставленные позиции и ручная привязка к справочнику.
"""

TAGS = [
    {"name": "Услуги", "description": "Справочник услуг и партнёры, которые их оказывают."},
    {"name": "Партнёры", "description": "Клиники-партнёры и их прайсы."},
    {"name": "Поиск", "description": "Полнотекстовый поиск по услугам и партнёрам."},
    {"name": "Сопоставление", "description": "Очередь несопоставленных позиций и ручная привязка."},
    {"name": "Сервис", "description": "Служебные метрики обработки."},
]

app = FastAPI(
    title="MedPartners API",
    version="1.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
)

PRICE = "COALESCE(price, price_min, price_max)"


@app.on_event("startup")
def _ensure_schema():
    conn = db.connect(check_same_thread=False)
    db.init_db(conn)
    conn.close()


def _conn():
    return db.connect(check_same_thread=False)


def _flags(value) -> list[str]:
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


class ServiceSummary(BaseModel):
    ref_service_id: int = Field(examples=[42])
    service_name_norm: str = Field(examples=["Прием кардиолога"])
    category: Optional[str] = Field(default=None, examples=["consultation"])
    partner_count: int = Field(examples=[4])
    price_min: Optional[float] = Field(default=None, examples=[9500])
    price_max: Optional[float] = Field(default=None, examples=[16600])


class PartnerPrice(BaseModel):
    partner_id: str = Field(examples=["clinic_4"])
    partner_name: str = Field(examples=["Клиника 4"])
    city: Optional[str] = None
    service_name_raw: str = Field(examples=["Консультация врача (кмн) первичная"])
    price: Optional[float] = Field(default=None, examples=[16500])
    price_resident: Optional[float] = Field(default=None, examples=[16500])
    price_nonresident: Optional[float] = Field(default=None, examples=[20800])
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = Field(default="KZT", examples=["KZT"])
    unit: Optional[str] = Field(default=None, examples=["посещение"])
    is_verified: Optional[int] = Field(default=0, examples=[1])
    source_file: Optional[str] = None
    source_year: Optional[int] = None
    parsed_at: Optional[str] = None
    confidence: Optional[float] = None
    flags: list[str] = []


class ServicePartners(BaseModel):
    service_id: int
    service_name: Optional[str] = None
    partners: list[PartnerPrice]


class PartnerSummary(BaseModel):
    partner_id: str
    partner_name: str
    city: Optional[str] = None
    service_count: int


class PartnerServiceItem(BaseModel):
    service_name_norm: Optional[str] = None
    service_name_raw: str
    category: Optional[str] = None
    price: Optional[float] = None
    price_resident: Optional[float] = None
    price_nonresident: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = None
    unit: Optional[str] = None
    is_verified: Optional[int] = 0
    source_file: Optional[str] = None
    source_year: Optional[int] = None
    parsed_at: Optional[str] = None
    flags: list[str] = []


class PartnerServices(BaseModel):
    partner_id: str
    services: list[PartnerServiceItem]


class SearchHit(BaseModel):
    partner_id: str
    partner_name: str
    service_name_norm: Optional[str] = None
    service_name_raw: str
    ref_service_id: Optional[int] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    unit: Optional[str] = None
    source_file: Optional[str] = None
    parsed_at: Optional[str] = None


class UnmatchedItem(BaseModel):
    id: int
    service_name_raw: str
    clinic_id: Optional[str] = None
    source_file: Optional[str] = None
    candidates: list = []


class Stats(BaseModel):
    price_items: int
    normalized: int
    normalized_pct: float
    partners: int
    unmatched: int


class MatchIn(BaseModel):
    record_id: int = Field(description="record_id позиции прайса", examples=[101])
    ref_service_id: int = Field(description="id услуги справочника", examples=[42])
    service_name_norm: str = Field(examples=["Прием кардиолога"])


class MatchResult(BaseModel):
    record_id: int
    ref_service_id: int
    matched: bool


@app.get(
    "/services",
    response_model=list[ServiceSummary],
    tags=["Услуги"],
    summary="Список услуг справочника",
    description="Услуги, к которым привязан хотя бы один прайс, с числом партнёров и диапазоном цен. Фильтр по категории и подстроке названия.",
)
def list_services(
    category: Optional[str] = Query(default=None, examples=["consultation"]),
    q: Optional[str] = Query(default=None, description="подстрока названия услуги"),
    limit: int = 200,
):
    clauses = ["ref_service_id IS NOT NULL"]
    params: list = []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if q:
        clauses.append("ulower(service_name_norm) LIKE ulower(?)")
        params.append(f"%{q}%")
    where = " AND ".join(clauses)
    rows = _conn().execute(
        f"""
        SELECT ref_service_id, service_name_norm, category,
               COUNT(DISTINCT clinic_id) AS partner_count,
               MIN({PRICE}) AS price_min, MAX({PRICE}) AS price_max
        FROM services WHERE {where}
        GROUP BY ref_service_id, service_name_norm, category
        ORDER BY service_name_norm LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get(
    "/services/{ref_service_id}/partners",
    response_model=ServicePartners,
    tags=["Услуги"],
    summary="Партнёры, оказывающие услугу",
    description="Клиники, оказывающие услугу справочника, с ценами (от дешёвых к дорогим).",
)
def service_partners(
    ref_service_id: int = Path(examples=[42]),
    active_only: bool = True,
):
    clauses = ["ref_service_id = ?"]
    params: list = [ref_service_id]
    if active_only:
        clauses.append("is_active = 1")
    where = " AND ".join(clauses)
    rows = _conn().execute(
        f"""
        SELECT clinic_id AS partner_id, clinic_name AS partner_name, city,
               service_name_norm, service_name_raw, {PRICE} AS price,
               price_resident, price_nonresident, price_min, price_max,
               currency, unit, is_verified, source_file, source_year, parsed_at, confidence, flags
        FROM services WHERE {where}
        ORDER BY {PRICE} ASC
        """,
        params,
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="услуга не найдена или нет партнёров")
    return {
        "service_id": ref_service_id,
        "service_name": rows[0]["service_name_norm"],
        "partners": [{**dict(r), "flags": _flags(r["flags"])} for r in rows],
    }


@app.get(
    "/partners",
    response_model=list[PartnerSummary],
    tags=["Партнёры"],
    summary="Список партнёров",
    description="Клиники-партнёры с числом услуг. Фильтр по городу.",
)
def list_partners(city: Optional[str] = None, active_only: bool = True):
    clauses: list[str] = []
    params: list = []
    if city:
        clauses.append("city = ?")
        params.append(city)
    if active_only:
        clauses.append("is_active = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = _conn().execute(
        f"""
        SELECT clinic_id AS partner_id, clinic_name AS partner_name, city,
               COUNT(*) AS service_count
        FROM services {where}
        GROUP BY clinic_id, clinic_name, city
        ORDER BY clinic_name
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


@app.get(
    "/partners/{partner_id}/services",
    response_model=PartnerServices,
    tags=["Партнёры"],
    summary="Прайс партнёра",
    description="Все услуги конкретной клиники с ценами.",
)
def partner_services(partner_id: str = Path(examples=["clinic_4"]), active_only: bool = True):
    clauses = ["clinic_id = ?"]
    params: list = [partner_id]
    if active_only:
        clauses.append("is_active = 1")
    where = " AND ".join(clauses)
    rows = _conn().execute(
        f"""
        SELECT service_name_norm, service_name_raw, category,
               {PRICE} AS price, price_resident, price_nonresident, price_min, price_max,
               currency, unit, is_verified, source_file, source_year, parsed_at, flags
        FROM services WHERE {where}
        ORDER BY category, service_name_norm
        """,
        params,
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="партнёр не найден")
    return {"partner_id": partner_id, "services": [{**dict(r), "flags": _flags(r["flags"])} for r in rows]}


@app.get(
    "/search",
    response_model=list[SearchHit],
    tags=["Поиск"],
    summary="Полнотекстовый поиск",
    description="Поиск по нормализованным и исходным названиям услуг и по названиям партнёров.",
)
def search(q: str = Query(examples=["прием кардиолога"]), limit: int = 100):
    like = f"%{q}%"
    rows = _conn().execute(
        f"""
        SELECT clinic_id AS partner_id, clinic_name AS partner_name,
               service_name_norm, service_name_raw, ref_service_id,
               {PRICE} AS price, currency, unit, source_file, parsed_at
        FROM services
        WHERE ulower(service_name_norm) LIKE ulower(?)
           OR ulower(service_name_raw) LIKE ulower(?)
           OR ulower(clinic_name) LIKE ulower(?)
        ORDER BY {PRICE} ASC LIMIT ?
        """,
        (like, like, like, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get(
    "/unmatched",
    response_model=list[UnmatchedItem],
    tags=["Сопоставление"],
    summary="Несопоставленные позиции",
    description="Позиции прайсов, не привязанные к справочнику, с кандидатами для ручной разметки.",
)
def list_unmatched(limit: int = 200):
    rows = _conn().execute(
        "SELECT id, service_name_raw, clinic_id, source_file, candidates FROM unmatched_queue ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    return [{**dict(r), "candidates": _flags(r["candidates"])} for r in rows]


@app.post(
    "/match",
    response_model=MatchResult,
    tags=["Сопоставление"],
    summary="Ручное сопоставление",
    description="Привязать позицию прайса к услуге справочника вручную.",
)
def match(body: MatchIn):
    conn = _conn()
    cur = conn.execute(
        "UPDATE services SET ref_service_id = ?, service_name_norm = ? WHERE record_id = ?",
        (body.ref_service_id, body.service_name_norm, body.record_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="позиция прайса не найдена")
    conn.commit()
    return {"record_id": body.record_id, "ref_service_id": body.ref_service_id, "matched": True}


@app.get(
    "/stats",
    response_model=Stats,
    tags=["Сервис"],
    summary="Метрики обработки",
    description="Количество позиций, доля нормализованных, число партнёров и размер очереди.",
)
def stats():
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    normalized = conn.execute("SELECT COUNT(*) FROM services WHERE service_name_norm IS NOT NULL").fetchone()[0]
    return {
        "price_items": total,
        "normalized": normalized,
        "normalized_pct": round(100 * normalized / total, 1) if total else 0,
        "partners": conn.execute("SELECT COUNT(DISTINCT clinic_id) FROM services").fetchone()[0],
        "unmatched": conn.execute("SELECT COUNT(*) FROM unmatched_queue").fetchone()[0],
    }


if get_scalar_api_reference is not None:

    @app.get("/reference", include_in_schema=False)
    def scalar_reference():
        return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)
