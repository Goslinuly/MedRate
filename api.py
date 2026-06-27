import json
import tempfile
import uuid
from pathlib import Path as FsPath
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Path, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import db
import queries
from config import CATEGORIES, COARSE_CATEGORIES

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
    {"name": "Верификация", "description": "Очередь ручной верификации позиций оператором."},
    {"name": "Загрузка", "description": "Загрузка архива прайсов и запуск обработки."},
    {"name": "Сервис", "description": "Служебные метрики обработки и фильтры."},
]

app = FastAPI(
    title="MedPartners API",
    version="1.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
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
    verified: int
    needs_review: int
    flags: dict[str, int] = {}
    ingest_log: list[dict] = []


class FilterOptions(BaseModel):
    cities: list[str] = []
    categories: list[dict] = []
    clinics: list[dict] = []


class ClinicYearPrice(BaseModel):
    partner_id: str
    partner_name: str
    source_year: Optional[int] = None
    price: Optional[float] = None
    is_active: Optional[int] = 1


class ServiceHistory(BaseModel):
    service_id: int
    service_name: Optional[str] = None
    points: list[ClinicYearPrice] = []


class VerificationItem(BaseModel):
    record_id: int
    clinic_id: Optional[str] = None
    clinic_name: Optional[str] = None
    service_name_raw: str
    service_name_norm: Optional[str] = None
    ref_service_id: Optional[int] = None
    category: Optional[str] = None
    price: Optional[float] = None
    price_resident: Optional[float] = None
    price_nonresident: Optional[float] = None
    currency: Optional[str] = None
    unit: Optional[str] = None
    confidence: Optional[float] = None
    verification_note: Optional[str] = None
    source_file: Optional[str] = None
    source_page: Optional[int] = None
    source_year: Optional[int] = None
    flags: list[str] = []


class VerifyIn(BaseModel):
    record_id: int = Field(examples=[101])
    action: str = Field(description="approve | reject | correct", examples=["approve"])
    price_resident: Optional[float] = None
    price_nonresident: Optional[float] = None
    service_name_norm: Optional[str] = None
    ref_service_id: Optional[int] = None
    note: Optional[str] = None


class VerifyResult(BaseModel):
    record_id: int
    action: str
    is_verified: int
    is_active: int


class IngestStarted(BaseModel):
    job_id: str
    files_received: int


class IngestStatus(BaseModel):
    job_id: str
    state: str
    files: int = 0
    services: int = 0
    normalized: int = 0
    failed_files: int = 0
    error: Optional[str] = None


class MatchIn(BaseModel):
    ref_service_id: int = Field(description="id услуги справочника", examples=[42])
    service_name_norm: str = Field(examples=["Прием кардиолога"])
    record_id: Optional[int] = Field(default=None, description="record_id позиции прайса", examples=[101])
    queue_id: Optional[int] = Field(default=None, description="id записи из очереди /unmatched", examples=[7])
    clinic_id: Optional[str] = Field(default=None, examples=["clinic_4"])
    service_name_raw: Optional[str] = Field(default=None, examples=["Озонотерапия лица"])


class MatchResult(BaseModel):
    ref_service_id: int
    matched: bool
    affected: int


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
    if body.record_id is not None:
        cur = conn.execute(
            "UPDATE services SET ref_service_id = ?, service_name_norm = ? WHERE record_id = ?",
            (body.ref_service_id, body.service_name_norm, body.record_id),
        )
    elif body.clinic_id and body.service_name_raw:
        cur = conn.execute(
            """
            UPDATE services SET ref_service_id = ?, service_name_norm = ?
            WHERE clinic_id = ? AND service_name_raw = ? AND ref_service_id IS NULL
            """,
            (body.ref_service_id, body.service_name_norm, body.clinic_id, body.service_name_raw),
        )
    else:
        raise HTTPException(status_code=400, detail="нужен record_id или (clinic_id + service_name_raw)")

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="позиция прайса не найдена")

    if body.queue_id is not None:
        conn.execute("DELETE FROM unmatched_queue WHERE id = ?", (body.queue_id,))
    elif body.clinic_id and body.service_name_raw:
        conn.execute(
            "DELETE FROM unmatched_queue WHERE clinic_id = ? AND service_name_raw = ?",
            (body.clinic_id, body.service_name_raw),
        )
    conn.commit()
    return {"ref_service_id": body.ref_service_id, "matched": True, "affected": cur.rowcount}


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
    verified = conn.execute("SELECT COUNT(*) FROM services WHERE is_verified = 1").fetchone()[0]

    flag_counts: dict[str, int] = {}
    for (value,) in conn.execute("SELECT flags FROM services WHERE flags IS NOT NULL AND flags != '[]'"):
        for flag in _flags(value):
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

    log = [dict(r) for r in conn.execute(
        "SELECT source_file, stage, status, reason, created_at FROM ingest_log ORDER BY id DESC LIMIT 30"
    ).fetchall()]

    return {
        "price_items": total,
        "normalized": normalized,
        "normalized_pct": round(100 * normalized / total, 1) if total else 0,
        "partners": conn.execute("SELECT COUNT(DISTINCT clinic_id) FROM services").fetchone()[0],
        "unmatched": conn.execute("SELECT COUNT(*) FROM unmatched_queue").fetchone()[0],
        "verified": verified,
        "needs_review": total - verified,
        "flags": dict(sorted(flag_counts.items(), key=lambda kv: kv[1], reverse=True)),
        "ingest_log": log,
    }


@app.get(
    "/filters",
    response_model=FilterOptions,
    tags=["Сервис"],
    summary="Опции фильтров",
    description="Города, категории (с русскими подписями) и клиники для выпадающих списков UI.",
)
def filters():
    conn = _conn()
    cities = queries.distinct_values(conn, "city")
    present = queries.distinct_values(conn, "category")
    categories = [
        {"value": cat, "label": COARSE_CATEGORIES.get(cat, cat)}
        for cat in CATEGORIES
        if cat in present
    ]
    clinics = [
        {"partner_id": cid, "partner_name": name}
        for name, cid in queries.clinic_options(conn).items()
    ]
    return {"cities": cities, "categories": categories, "clinics": clinics}


@app.get(
    "/services/{ref_service_id}/history",
    response_model=ServiceHistory,
    tags=["Услуги"],
    summary="История цен услуги",
    description="Цены по годам для услуги справочника, сгруппированные по клинике — для графика истории.",
)
def service_history(ref_service_id: int = Path(examples=[42])):
    rows = _conn().execute(
        f"""
        SELECT clinic_id AS partner_id, clinic_name AS partner_name,
               source_year, {PRICE} AS price, is_active, service_name_norm
        FROM services
        WHERE ref_service_id = ? AND source_year IS NOT NULL AND {PRICE} IS NOT NULL
        ORDER BY partner_name, source_year
        """,
        (ref_service_id,),
    ).fetchall()
    name = rows[0]["service_name_norm"] if rows else None
    return {
        "service_id": ref_service_id,
        "service_name": name,
        "points": [
            {k: r[k] for k in ("partner_id", "partner_name", "source_year", "price", "is_active")}
            for r in rows
        ],
    }


@app.get(
    "/verification",
    response_model=list[VerificationItem],
    tags=["Верификация"],
    summary="Очередь верификации",
    description="Позиции прайсов, требующие ручной верификации (is_verified = 0): с флагами, причиной и ценами рез/нерез.",
)
def verification_queue(
    flag: Optional[str] = Query(default=None, description="фильтр по флагу, напр. price_anomaly"),
    limit: int = 200,
):
    clauses = ["is_verified = 0"]
    params: list = []
    if flag:
        clauses.append("flags LIKE ?")
        params.append(f'%"{flag}"%')
    where = " AND ".join(clauses)
    rows = _conn().execute(
        f"""
        SELECT record_id, clinic_id, clinic_name, service_name_raw, service_name_norm,
               ref_service_id, category, {PRICE} AS price, price_resident, price_nonresident,
               currency, unit, confidence, verification_note, source_file, source_page,
               source_year, flags
        FROM services WHERE {where}
        ORDER BY confidence ASC, record_id LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [{**dict(r), "flags": _flags(r["flags"])} for r in rows]


@app.post(
    "/verify",
    response_model=VerifyResult,
    tags=["Верификация"],
    summary="Верифицировать позицию",
    description="Подтвердить (approve), отклонить (reject) или исправить (correct) позицию прайса.",
)
def verify(body: VerifyIn):
    conn = _conn()
    row = conn.execute(
        "SELECT is_active FROM services WHERE record_id = ?", (body.record_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="позиция прайса не найдена")

    if body.action == "reject":
        conn.execute(
            "UPDATE services SET is_active = 0, is_verified = 0, verification_note = ? WHERE record_id = ?",
            (body.note or "отклонено оператором", body.record_id),
        )
        conn.commit()
        return {"record_id": body.record_id, "action": "reject", "is_verified": 0, "is_active": 0}

    if body.action == "correct":
        sets = ["is_verified = 1", "verification_note = ?"]
        params: list = [body.note or "исправлено оператором"]
        for column, value in (
            ("price_resident", body.price_resident),
            ("price_nonresident", body.price_nonresident),
            ("price", body.price_resident),
            ("service_name_norm", body.service_name_norm),
            ("ref_service_id", body.ref_service_id),
        ):
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)
        params.append(body.record_id)
        conn.execute(f"UPDATE services SET {', '.join(sets)} WHERE record_id = ?", params)
        conn.commit()
        return {"record_id": body.record_id, "action": "correct", "is_verified": 1, "is_active": 1}

    if body.action == "approve":
        conn.execute(
            "UPDATE services SET is_verified = 1, verification_note = ? WHERE record_id = ?",
            (body.note or "", body.record_id),
        )
        conn.commit()
        return {"record_id": body.record_id, "action": "approve", "is_verified": 1, "is_active": 1}

    raise HTTPException(status_code=400, detail="action должно быть approve | reject | correct")


_INGEST_JOBS: dict[str, dict] = {}


def _run_ingest(job_id: str, paths: list[FsPath], reset: bool) -> None:
    from pipeline.process import process_paths

    conn = db.connect(check_same_thread=False)
    db.init_db(conn)
    try:
        if reset:
            db.clear_pipeline_tables(conn)
        stats_result = process_paths(paths, conn)
        _INGEST_JOBS[job_id] = {"state": "done", **stats_result}
    except Exception as error:  # noqa: BLE001
        _INGEST_JOBS[job_id] = {"state": "error", "error": f"{type(error).__name__}: {error}"}
    finally:
        conn.close()


@app.post(
    "/ingest",
    response_model=IngestStarted,
    tags=["Загрузка"],
    summary="Загрузить и обработать прайсы",
    description="Принимает архив(ы) ZIP или отдельные файлы прайсов и запускает обработку в фоне. Статус — GET /ingest/status/{job_id}.",
)
async def ingest_upload(
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    reset: bool = Form(default=False),
):
    job_dir = FsPath(tempfile.mkdtemp(prefix="medrate_ingest_"))
    saved: list[FsPath] = []
    for upload in files:
        destination = job_dir / (upload.filename or f"file_{len(saved)}")
        destination.write_bytes(await upload.read())
        saved.append(destination)

    job_id = uuid.uuid4().hex
    _INGEST_JOBS[job_id] = {"state": "running"}
    background.add_task(_run_ingest, job_id, saved, reset)
    return {"job_id": job_id, "files_received": len(saved)}


@app.get(
    "/ingest/status/{job_id}",
    response_model=IngestStatus,
    tags=["Загрузка"],
    summary="Статус обработки",
    description="Состояние фоновой задачи обработки архива.",
)
def ingest_status(job_id: str):
    job = _INGEST_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="задача не найдена")
    return {"job_id": job_id, **job}


if get_scalar_api_reference is not None:

    @app.get("/reference", include_in_schema=False)
    def scalar_reference():
        return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)
