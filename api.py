import json
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import db

app = FastAPI(
    title="MedPartners API",
    version="1.0",
    description="Поиск медицинских услуг партнёрских клиник, нормализованных по справочнику.",
)

PRICE = "COALESCE(price, price_min, price_max)"


def _conn():
    return db.connect(check_same_thread=False)


def _flags(value) -> list[str]:
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


@app.get("/services")
def list_services(category: Optional[str] = None, q: Optional[str] = None, limit: int = 200):
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


@app.get("/services/{ref_service_id}/partners")
def service_partners(ref_service_id: int, active_only: bool = True):
    clauses = ["ref_service_id = ?"]
    params: list = [ref_service_id]
    if active_only:
        clauses.append("is_active = 1")
    where = " AND ".join(clauses)
    rows = _conn().execute(
        f"""
        SELECT clinic_id AS partner_id, clinic_name AS partner_name, city,
               service_name_raw, {PRICE} AS price, price_min, price_max, currency, unit,
               source_file, source_year, parsed_at, confidence, flags
        FROM services WHERE {where}
        ORDER BY {PRICE} ASC
        """,
        params,
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="service not found or has no partners")
    name = rows[0]["service_name_raw"]
    return {
        "service_id": ref_service_id,
        "partners": [{**dict(r), "flags": _flags(r["flags"])} for r in rows],
    }


@app.get("/partners")
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


@app.get("/partners/{partner_id}/services")
def partner_services(partner_id: str, active_only: bool = True):
    clauses = ["clinic_id = ?"]
    params: list = [partner_id]
    if active_only:
        clauses.append("is_active = 1")
    where = " AND ".join(clauses)
    rows = _conn().execute(
        f"""
        SELECT service_name_norm, service_name_raw, category,
               {PRICE} AS price, price_min, price_max, currency, unit,
               source_file, source_year, parsed_at, flags
        FROM services WHERE {where}
        ORDER BY category, service_name_norm
        """,
        params,
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="partner not found")
    return {"partner_id": partner_id, "services": [{**dict(r), "flags": _flags(r["flags"])} for r in rows]}


@app.get("/search")
def search(q: str, limit: int = 100):
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


@app.get("/unmatched")
def list_unmatched(limit: int = 200):
    rows = _conn().execute(
        "SELECT id, service_name_raw, clinic_id, source_file, candidates FROM unmatched_queue ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    return [{**dict(r), "candidates": _flags(r["candidates"])} for r in rows]


class MatchIn(BaseModel):
    record_id: int
    ref_service_id: int
    service_name_norm: str


@app.post("/match")
def match(body: MatchIn):
    conn = _conn()
    cur = conn.execute(
        "UPDATE services SET ref_service_id = ?, service_name_norm = ? WHERE record_id = ?",
        (body.ref_service_id, body.service_name_norm, body.record_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="price item not found")
    conn.commit()
    return {"record_id": body.record_id, "ref_service_id": body.ref_service_id, "matched": True}


@app.get("/stats")
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
