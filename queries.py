import sqlite3
from typing import Optional

import pandas as pd

from config import REFERENCE_FILE

SORT_OPTIONS = {
    "Цена ↑": "price_sort ASC",
    "Цена ↓": "price_sort DESC",
    "Сначала свежие": "parsed_at DESC",
    "По названию": "service_name_norm ASC",
    "Рейтинг ↓": "rating DESC",
    "Расстояние ↑": "price_sort ASC",
}

PRICE_SORT = "COALESCE(price, price_min, price_max)"


def distinct_values(conn: sqlite3.Connection, column: str) -> list[str]:
    rows = conn.execute(
        f"SELECT DISTINCT {column} FROM services WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}"
    ).fetchall()
    return [row[0] for row in rows]


def clinic_options(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT DISTINCT clinic_id, clinic_name FROM services ORDER BY clinic_name"
    ).fetchall()
    return {row["clinic_name"]: row["clinic_id"] for row in rows}


def price_bounds(conn: sqlite3.Connection) -> tuple[int, int]:
    row = conn.execute(
        f"SELECT MIN({PRICE_SORT}), MAX({PRICE_SORT}) FROM services WHERE {PRICE_SORT} IS NOT NULL"
    ).fetchone()
    low, high = row[0], row[1]
    if low is None or high is None:
        return 0, 0
    return int(low), int(high)


def autocomplete_terms(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT service_name_norm FROM services WHERE service_name_norm IS NOT NULL ORDER BY service_name_norm"
    ).fetchall()
    return [row[0] for row in rows]


def search_services(
    conn: sqlite3.Connection,
    query: str = "",
    city: Optional[str] = None,
    category: Optional[str] = None,
    clinic_id: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    only_active: bool = True,
    only_flagged: bool = False,
    min_rating: Optional[float] = None,
    online_booking: bool = False,
    sort: str = "Цена ↑",
    limit: int = 1000,
) -> pd.DataFrame:
    clauses, params = [], []
    if query:
        clauses.append(
            "(ulower(service_name_norm) LIKE ulower(?) "
            "OR ulower(service_name_raw) LIKE ulower(?) "
            "OR ulower(service_name_kz) LIKE ulower(?))"
        )
        params.extend([f"%{query}%"] * 3)
    if city:
        clauses.append("city = ?")
        params.append(city)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if clinic_id:
        clauses.append("clinic_id = ?")
        params.append(clinic_id)
    if price_min is not None:
        clauses.append(f"{PRICE_SORT} >= ?")
        params.append(price_min)
    if price_max is not None:
        clauses.append(f"{PRICE_SORT} <= ?")
        params.append(price_max)
    if only_active:
        clauses.append("is_active = 1")
    if only_flagged:
        clauses.append("flags IS NOT NULL AND flags != '[]'")
    if min_rating is not None:
        clauses.append("rating >= ?")
        params.append(min_rating)
    if online_booking:
        clauses.append("online_booking = 1")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = SORT_OPTIONS.get(sort, "price_sort ASC")
    sql = f"""
        SELECT clinic_name, service_name_norm, service_name_raw, service_name_kz, category,
               price, price_min, price_max, currency, unit, {PRICE_SORT} AS price_sort,
               parsed_at, source_year, confidence, flags, source_file, source_page,
               source_url, clinic_id, ref_service_id, is_active, city, address, phone,
               working_hours, lat, lon, rating, online_booking, doctor_name,
               reviews_count, experience_years
        FROM services
        {where}
        ORDER BY {order}
        LIMIT ?
    """
    return pd.read_sql_query(sql, conn, params=[*params, limit])


def clinic_info(conn: sqlite3.Connection, clinic_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM clinics WHERE clinic_id = ?", (clinic_id,)
    ).fetchone()
    return dict(row) if row else {}


def clinic_services(conn: sqlite3.Connection, clinic_id: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"""
        SELECT service_name_norm, service_name_raw, category, price, price_min, price_max,
               currency, unit, {PRICE_SORT} AS price_sort, parsed_at, source_year, confidence,
               flags, source_file, source_url, city, address, phone, working_hours,
               lat, lon, rating, online_booking, doctor_name, reviews_count,
               experience_years
        FROM services WHERE clinic_id = ? AND is_active = 1
        ORDER BY category, service_name_norm
        """,
        conn,
        params=[clinic_id],
    )


def compare_service(conn: sqlite3.Connection, service_name_norm: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"""
        SELECT clinic_name, service_name_raw, price, price_min, price_max, currency, unit,
               {PRICE_SORT} AS price_sort, parsed_at, source_year, confidence, flags,
               source_file, source_url, city, lat, lon, rating, online_booking
               , doctor_name, reviews_count, experience_years
        FROM services
        WHERE service_name_norm = ? AND is_active = 1
        ORDER BY price_sort ASC
        """,
        conn,
        params=[service_name_norm],
    )


def services_with_history(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        """
        SELECT clinic_id, clinic_name, service_name_norm
        FROM services
        WHERE service_name_norm IS NOT NULL
        GROUP BY clinic_id, service_name_norm
        HAVING COUNT(DISTINCT source_year) > 1
        ORDER BY clinic_name, service_name_norm
        """
    ).fetchall()
    return [(row["clinic_id"], row["clinic_name"], row["service_name_norm"]) for row in rows]


def price_history(conn: sqlite3.Connection, clinic_id: str, service_name_norm: str) -> pd.DataFrame:
    return pd.read_sql_query(
        f"""
        SELECT source_year, {PRICE_SORT} AS price, currency, source_file, parsed_at, is_active
        FROM services
        WHERE clinic_id = ? AND service_name_norm = ?
        ORDER BY source_year
        """,
        conn,
        params=[clinic_id, service_name_norm],
    )


def reference_terms() -> list[str]:
    df = pd.read_excel(REFERENCE_FILE)
    return sorted({str(name).strip() for name in df["Name_ru"].dropna()})


def export_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM services ORDER BY clinic_name, service_name_norm", conn)


def counts(conn: sqlite3.Connection) -> dict:
    return {
        "services": conn.execute("SELECT COUNT(*) FROM services").fetchone()[0],
        "active": conn.execute("SELECT COUNT(*) FROM services WHERE is_active = 1").fetchone()[0],
        "normalized": conn.execute(
            "SELECT COUNT(*) FROM services WHERE service_name_norm IS NOT NULL"
        ).fetchone()[0],
        "clinics": conn.execute("SELECT COUNT(DISTINCT clinic_id) FROM services").fetchone()[0],
        "unmatched": conn.execute("SELECT COUNT(*) FROM unmatched_queue").fetchone()[0],
    }


def ingest_log(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT source_file, stage, status, reason, created_at FROM ingest_log ORDER BY id DESC",
        conn,
    )
