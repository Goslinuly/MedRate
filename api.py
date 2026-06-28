import json
import tempfile
import uuid
from io import BytesIO
from pathlib import Path as FsPath
from typing import Optional

import sqlite3

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Path, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import db
import queries
from config import CATEGORIES, COARSE_CATEGORIES, REFERENCE_DIR, REFERENCE_FILE, UPLOADS_DIR
from pipeline.normalize import build_ref_index, load_reference_rows

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
    {"name": "Аналитика", "description": "Рыночные метрики, корзина обследований, отчёт о качестве."},
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


def get_db():
    conn = db.connect(check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


_REF_INDEX = None


def _ref_index():
    global _REF_INDEX
    if _REF_INDEX is None:
        conn = db.connect(check_same_thread=False)
        try:
            _REF_INDEX = build_ref_index(conn)
        finally:
            conn.close()
    return _REF_INDEX


def _invalidate_ref_index():
    global _REF_INDEX
    _REF_INDEX = None


def _flags(value) -> list[str]:
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in 0..1) over a pre-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    low = int(pos)
    frac = pos - low
    if low + 1 >= len(sorted_values):
        return sorted_values[low]
    return sorted_values[low] + frac * (sorted_values[low + 1] - sorted_values[low])


def _market_stats(prices: list[float]) -> dict:
    values = sorted(p for p in prices if p is not None and p > 0)
    if not values:
        return {"count": 0, "median": None, "p25": None, "p75": None, "min": None, "max": None}
    return {
        "count": len(values),
        "median": round(_percentile(values, 0.5), 2),
        "p25": round(_percentile(values, 0.25), 2),
        "p75": round(_percentile(values, 0.75), 2),
        "min": values[0],
        "max": values[-1],
    }


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
    delta_pct: Optional[float] = Field(default=None, description="отклонение от медианы рынка, %", examples=[-18.0])
    is_outlier: bool = Field(default=False, description="ценовой выброс (подозрительно дорого)")


class MarketStats(BaseModel):
    count: int
    median: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None


class ServicePartners(BaseModel):
    service_id: int
    service_name: Optional[str] = None
    market: Optional[MarketStats] = None
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
    conn: sqlite3.Connection = Depends(get_db),
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
    rows = conn.execute(
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
    conn: sqlite3.Connection = Depends(get_db),
):
    clauses = ["ref_service_id = ?"]
    params: list = [ref_service_id]
    if active_only:
        clauses.append("is_active = 1")
    where = " AND ".join(clauses)
    rows = conn.execute(
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

    def eff_price(r) -> Optional[float]:
        return r["price_resident"] if r["price_resident"] is not None else r["price"]

    market = _market_stats([eff_price(r) for r in rows])
    median = market["median"]
    p75 = market["p75"]
    p25 = market["p25"]
    iqr = (p75 - p25) if (p75 is not None and p25 is not None) else 0
    outlier_threshold = (p75 + 1.5 * iqr) if p75 is not None else None

    partners = []
    for r in rows:
        price = eff_price(r)
        delta_pct = None
        is_outlier = False
        if price is not None and median:
            delta_pct = round((price - median) / median * 100, 1)
            if outlier_threshold is not None and price > outlier_threshold and market["count"] >= 4:
                is_outlier = True
        partners.append({**dict(r), "flags": _flags(r["flags"]), "delta_pct": delta_pct, "is_outlier": is_outlier})

    return {
        "service_id": ref_service_id,
        "service_name": rows[0]["service_name_norm"],
        "market": market,
        "partners": partners,
    }


@app.get(
    "/partners",
    response_model=list[PartnerSummary],
    tags=["Партнёры"],
    summary="Список партнёров",
    description="Клиники-партнёры с числом услуг. Фильтр по городу.",
)
def list_partners(city: Optional[str] = None, active_only: bool = True, conn: sqlite3.Connection = Depends(get_db)):
    clauses: list[str] = []
    params: list = []
    if city:
        clauses.append("city = ?")
        params.append(city)
    if active_only:
        clauses.append("is_active = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
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
def partner_services(partner_id: str = Path(examples=["clinic_4"]), active_only: bool = True, conn: sqlite3.Connection = Depends(get_db)):
    clauses = ["clinic_id = ?"]
    params: list = [partner_id]
    if active_only:
        clauses.append("is_active = 1")
    where = " AND ".join(clauses)
    rows = conn.execute(
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
def search(q: str = Query(examples=["прием кардиолога"]), limit: int = 100, conn: sqlite3.Connection = Depends(get_db)):
    like = f"%{q}%"
    rows = conn.execute(
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
def list_unmatched(limit: int = 200, conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
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
def match(body: MatchIn, conn: sqlite3.Connection = Depends(get_db)):
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


class RefEntry(BaseModel):
    id: int
    name: str
    specialty: Optional[str] = None
    category: Optional[str] = None


class RefCreateIn(BaseModel):
    name: str = Field(examples=["Озонотерапия лица"])
    category: Optional[str] = Field(default=None, examples=["procedures"])
    specialty: Optional[str] = None


class RefCreateResult(BaseModel):
    ref_service_id: int
    service_name_norm: str


class RefUploadResult(BaseModel):
    rows: int
    file: str


@app.get(
    "/reference/search",
    response_model=list[RefEntry],
    tags=["Сопоставление"],
    summary="Поиск по справочнику",
    description="Поиск услуг во всём справочнике — для ручной привязки к любой позиции, не только к кандидатам.",
)
def reference_search(q: str = Query(examples=["кардиолог"]), limit: int = 20):
    return [
        {"id": e["id"], "name": e["name"], "specialty": e.get("specialty"), "category": e.get("category")}
        for e in _ref_index().search(q, limit)
    ]


@app.post(
    "/reference",
    response_model=RefCreateResult,
    tags=["Сопоставление"],
    summary="Создать позицию справочника",
    description="Оператор добавляет новую услугу в справочник (когда подходящей нет среди кандидатов).",
)
def reference_create(body: RefCreateIn, conn: sqlite3.Connection = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="название не может быть пустым")
    ref_id = db.add_reference(conn, body.name, body.category or "", body.specialty or "")
    _invalidate_ref_index()
    return {"ref_service_id": ref_id, "service_name_norm": body.name.strip()}


@app.post(
    "/reference/upload",
    response_model=RefUploadResult,
    tags=["Загрузка"],
    summary="Загрузить справочник",
    description="Загрузка целевого справочника услуг в формате XLSX или JSON (заменяет текущий).",
)
async def reference_upload(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    if name.endswith(".json"):
        dest = REFERENCE_DIR / "services.json"
        dest.write_bytes(await file.read())
    elif name.endswith(".xlsx"):
        dest = REFERENCE_FILE
        dest.write_bytes(await file.read())
        json_path = REFERENCE_DIR / "services.json"
        if json_path.exists():
            json_path.unlink()  # xlsx becomes the active catalogue
    else:
        raise HTTPException(status_code=400, detail="ожидается файл .xlsx или .json")
    rows = len(load_reference_rows(dest))
    if rows == 0:
        raise HTTPException(status_code=400, detail="не удалось прочитать услуги из файла")
    _invalidate_ref_index()
    return {"rows": rows, "file": dest.name}


class DocumentItem(BaseModel):
    doc_id: str
    partner_id: Optional[str] = None
    file_name: str
    file_format: Optional[str] = None
    effective_date: Optional[str] = None
    parsed_at: Optional[str] = None
    parse_status: Optional[str] = None
    parse_log: Optional[str] = None
    chunks: Optional[int] = None


@app.get(
    "/documents",
    response_model=list[DocumentItem],
    tags=["Загрузка"],
    summary="Прайс-документы",
    description="Список обработанных прайс-документов со статусом разбора (pending/processing/done/error/needs_review).",
)
def documents(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        """
        SELECT doc_id, partner_id, file_name, file_format, effective_date,
               parsed_at, parse_status, parse_log, chunks
        FROM price_documents ORDER BY parsed_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


@app.get(
    "/documents/page",
    tags=["Верификация"],
    summary="Фрагмент документа (изображение)",
    description="Рендер страницы исходного PDF или изображение-источник — для очереди верификации.",
)
def document_page(file: str = Query(...), page: int = 1):
    path = UPLOADS_DIR / FsPath(file).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="исходный файл не сохранён")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pdf2image import convert_from_path

            images = convert_from_path(str(path), dpi=120, first_page=page, last_page=page)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"не удалось отрендерить страницу: {error}")
        if not images:
            raise HTTPException(status_code=404, detail="страница не найдена")
        buffer = BytesIO()
        images[0].save(buffer, format="PNG")
        return Response(content=buffer.getvalue(), media_type="image/png")
    if suffix in {".png", ".jpg", ".jpeg"}:
        return FileResponse(path)
    raise HTTPException(status_code=415, detail="превью доступно для PDF и изображений; используйте /documents/file")


@app.get(
    "/documents/file",
    tags=["Верификация"],
    summary="Скачать исходный документ",
    description="Отдаёт сохранённый оригинал файла-прайса (для DOCX/XLSX и аудита).",
)
def document_file(file: str = Query(...)):
    path = UPLOADS_DIR / FsPath(file).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="исходный файл не сохранён")
    return FileResponse(path, filename=path.name)


class BasketIn(BaseModel):
    service_ids: list[int] = Field(examples=[[42, 77, 10]])
    resident: bool = Field(default=True, description="True — цена резидента, False — нерезидента")
    city: Optional[str] = None


class BasketComboItem(BaseModel):
    ref_service_id: int
    service_name: Optional[str] = None
    partner_id: str
    partner_name: str
    price: float


class BasketClinic(BaseModel):
    partner_id: str
    partner_name: str
    city: Optional[str] = None
    covered: int
    total_requested: int
    total_price: float
    items: list[dict] = []
    missing: list[int] = []


class BasketResult(BaseModel):
    requested: list[int]
    cheapest_total: float
    cheapest_items: list[BasketComboItem]
    missing_anywhere: list[int]
    by_clinic: list[BasketClinic]


@app.post(
    "/basket/optimize",
    response_model=BasketResult,
    tags=["Аналитика"],
    summary="Оптимизатор корзины обследований",
    description="По набору услуг находит самую дешёвую комбинацию (по каждой услуге) и ранжирует клиники по покрытию и сумме.",
)
def basket_optimize(body: BasketIn, conn: sqlite3.Connection = Depends(get_db)):
    if not body.service_ids:
        raise HTTPException(status_code=400, detail="нужен хотя бы один service_id")
    placeholders = ",".join("?" for _ in body.service_ids)
    clauses = [f"ref_service_id IN ({placeholders})", "is_active = 1"]
    params: list = list(body.service_ids)
    if body.city:
        clauses.append("city = ?")
        params.append(body.city)
    price_col = "price_resident" if body.resident else "price_nonresident"
    rows = conn.execute(
        f"""
        SELECT clinic_id AS partner_id, clinic_name AS partner_name, city,
               ref_service_id, service_name_norm,
               COALESCE({price_col}, price, price_min) AS price
        FROM services
        WHERE {" AND ".join(clauses)} AND COALESCE({price_col}, price, price_min) IS NOT NULL
        """,
        params,
    ).fetchall()

    # cheapest price per (service) globally and per (clinic, service)
    cheapest_global: dict[int, dict] = {}
    per_clinic: dict[str, dict] = {}
    for r in rows:
        sid, price = r["ref_service_id"], r["price"]
        if sid not in cheapest_global or price < cheapest_global[sid]["price"]:
            cheapest_global[sid] = {
                "ref_service_id": sid, "service_name": r["service_name_norm"],
                "partner_id": r["partner_id"], "partner_name": r["partner_name"], "price": price,
            }
        clinic = per_clinic.setdefault(
            r["partner_id"],
            {"partner_id": r["partner_id"], "partner_name": r["partner_name"], "city": r["city"], "services": {}},
        )
        existing = clinic["services"].get(sid)
        if existing is None or price < existing["price"]:
            clinic["services"][sid] = {"ref_service_id": sid, "service_name": r["service_name_norm"], "price": price}

    cheapest_items = list(cheapest_global.values())
    cheapest_total = round(sum(item["price"] for item in cheapest_items), 2)
    missing_anywhere = [sid for sid in body.service_ids if sid not in cheapest_global]

    by_clinic = []
    for clinic in per_clinic.values():
        items = list(clinic["services"].values())
        covered = len(items)
        by_clinic.append({
            "partner_id": clinic["partner_id"],
            "partner_name": clinic["partner_name"],
            "city": clinic["city"],
            "covered": covered,
            "total_requested": len(body.service_ids),
            "total_price": round(sum(i["price"] for i in items), 2),
            "items": items,
            "missing": [sid for sid in body.service_ids if sid not in clinic["services"]],
        })
    by_clinic.sort(key=lambda c: (-c["covered"], c["total_price"]))

    return {
        "requested": body.service_ids,
        "cheapest_total": cheapest_total,
        "cheapest_items": cheapest_items,
        "missing_anywhere": missing_anywhere,
        "by_clinic": by_clinic,
    }


class GeoClinic(BaseModel):
    partner_id: str
    partner_name: str
    city: Optional[str] = None
    address: Optional[str] = None
    lat: float
    lon: float
    service_count: int


class GeocodeResult(BaseModel):
    geocoded: int
    remaining: int


@app.get(
    "/partners/geo",
    response_model=list[GeoClinic],
    tags=["Аналитика"],
    summary="Клиники на карте",
    description="Клиники с координатами и числом услуг — для гео-карты.",
)
def partners_geo(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        """
        SELECT c.clinic_id AS partner_id, c.clinic_name AS partner_name, c.city, c.address,
               c.lat, c.lon,
               (SELECT COUNT(*) FROM services s WHERE s.clinic_id = c.clinic_id AND s.is_active = 1) AS service_count
        FROM clinics c
        WHERE c.lat IS NOT NULL AND c.lon IS NOT NULL
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _geocode(query: str) -> Optional[tuple[float, float]]:
    import urllib.parse
    import urllib.request

    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 1}
    )
    request = urllib.request.Request(url, headers={"User-Agent": "MedRate/1.0 (hackathon)"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None
    return None


def _run_geocode() -> None:
    import time

    conn = db.connect(check_same_thread=False)
    try:
        rows = conn.execute(
            "SELECT clinic_id, clinic_name, city, address FROM clinics "
            "WHERE lat IS NULL AND (address IS NOT NULL OR city IS NOT NULL)"
        ).fetchall()
        for r in rows:
            query = ", ".join(v for v in (r["address"], r["city"], "Казахстан") if v)
            coords = _geocode(query)
            if coords:
                conn.execute(
                    "UPDATE clinics SET lat = ?, lon = ? WHERE clinic_id = ?",
                    (coords[0], coords[1], r["clinic_id"]),
                )
                conn.commit()
            time.sleep(1.1)  # Nominatim usage policy: ≤1 req/sec
    finally:
        conn.close()


@app.post(
    "/partners/geocode",
    response_model=GeocodeResult,
    tags=["Аналитика"],
    summary="Геокодировать клиники",
    description="Определяет координаты клиник по адресу/городу (OpenStreetMap Nominatim) в фоне.",
)
def partners_geocode(background: BackgroundTasks, conn: sqlite3.Connection = Depends(get_db)):
    remaining = conn.execute(
        "SELECT COUNT(*) FROM clinics WHERE lat IS NULL AND (address IS NOT NULL OR city IS NOT NULL)"
    ).fetchone()[0]
    geocoded = conn.execute("SELECT COUNT(*) FROM clinics WHERE lat IS NOT NULL").fetchone()[0]
    background.add_task(_run_geocode)
    return {"geocoded": geocoded, "remaining": remaining}


@app.get(
    "/report/quality",
    tags=["Аналитика"],
    summary="Отчёт о качестве (Markdown)",
    description="Генерирует отчёт о качестве обработки (документы, % нормализации, очереди, флаги) — deliverable ТЗ §7.",
)
def quality_report(conn: sqlite3.Connection = Depends(get_db)):
    total = conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    normalized = conn.execute("SELECT COUNT(*) FROM services WHERE service_name_norm IS NOT NULL").fetchone()[0]
    verified = conn.execute("SELECT COUNT(*) FROM services WHERE is_verified = 1").fetchone()[0]
    partners = conn.execute("SELECT COUNT(DISTINCT clinic_id) FROM services").fetchone()[0]
    unmatched = conn.execute("SELECT COUNT(*) FROM unmatched_queue").fetchone()[0]
    docs = conn.execute(
        "SELECT parse_status, COUNT(*) n FROM price_documents GROUP BY parse_status"
    ).fetchall()
    doc_total = sum(d["n"] for d in docs)

    flag_counts: dict[str, int] = {}
    for (value,) in conn.execute("SELECT flags FROM services WHERE flags IS NOT NULL AND flags != '[]'"):
        for flag in _flags(value):
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

    by_clinic = conn.execute(
        """
        SELECT clinic_name, COUNT(*) n, SUM(service_name_norm IS NOT NULL) norm
        FROM services GROUP BY clinic_id, clinic_name ORDER BY n DESC
        """
    ).fetchall()

    pct = round(100 * normalized / total, 1) if total else 0
    lines = [
        "# MedRate — отчёт о качестве обработки",
        "",
        f"_Сгенерировано: {db.now_iso()}_",
        "",
        "## Сводка",
        "",
        f"- Прайс-документов обработано: **{doc_total}**",
        f"- Позиций прайсов: **{total}**",
        f"- Нормализовано (привязано к справочнику): **{normalized}** (**{pct}%**)"
        + ("  ✅ цель MVP ≥70%" if pct >= 70 else "  ⚠️ цель MVP — 70%"),
        f"- Верифицировано оператором: **{verified}**",
        f"- В очереди сопоставления (unmatched): **{unmatched}**",
        f"- Клиник-партнёров: **{partners}**",
        "",
        "## Документы по статусу разбора",
        "",
        "| Статус | Документов |",
        "|---|---|",
        *[f"| {d['parse_status']} | {d['n']} |" for d in docs],
        "",
        "## Флаги качества",
        "",
        "| Флаг | Количество |",
        "|---|---|",
        *[f"| {flag} | {n} |" for flag, n in sorted(flag_counts.items(), key=lambda kv: -kv[1])],
        "",
        "## Покрытие по клиникам",
        "",
        "| Клиника | Позиций | Нормализовано |",
        "|---|---|---|",
        *[f"| {c['clinic_name']} | {c['n']} | {c['norm']} |" for c in by_clinic],
        "",
    ]
    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="medrate_quality_report.md"'},
    )


@app.get(
    "/stats",
    response_model=Stats,
    tags=["Сервис"],
    summary="Метрики обработки",
    description="Количество позиций, доля нормализованных, число партнёров и размер очереди.",
)
def stats(conn: sqlite3.Connection = Depends(get_db)):
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
def filters(conn: sqlite3.Connection = Depends(get_db)):
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
def service_history(ref_service_id: int = Path(examples=[42]), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
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
    conn: sqlite3.Connection = Depends(get_db),
):
    clauses = ["is_verified = 0"]
    params: list = []
    if flag:
        clauses.append("flags LIKE ?")
        params.append(f'%"{flag}"%')
    where = " AND ".join(clauses)
    rows = conn.execute(
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
def verify(body: VerifyIn, conn: sqlite3.Connection = Depends(get_db)):
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
