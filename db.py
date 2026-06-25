"""SQLite storage for unified price records, plus search/filter queries."""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

DEFAULT_DB = "medrate.db"

_COLUMNS = [
    "clinic_name",
    "clinic_id",
    "service_name_raw",
    "service_name_normalized",
    "service_name_kz",
    "category",
    "price",
    "price_min",
    "price_max",
    "currency",
    "unit",
    "source_file",
    "source_page",
    "confidence",
    "flags",
    "notes",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_name TEXT,
    clinic_id TEXT,
    service_name_raw TEXT,
    service_name_normalized TEXT,
    service_name_kz TEXT,
    category TEXT,
    price REAL,
    price_min REAL,
    price_max REAL,
    currency TEXT,
    unit TEXT,
    source_file TEXT,
    source_page TEXT,
    confidence REAL,
    flags TEXT,   -- JSON array
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_clinic ON records(clinic_id);
CREATE INDEX IF NOT EXISTS idx_records_category ON records(category);
"""


def connect(path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def clear(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM records")
    conn.commit()


def insert_records(conn: sqlite3.Connection, records: list[dict]) -> int:
    rows = []
    for rec in records:
        row = []
        for col in _COLUMNS:
            value = rec.get(col)
            if col == "flags":
                value = json.dumps(value or [], ensure_ascii=False)
            elif col == "source_page" and value is not None:
                value = str(value)
            row.append(value)
        rows.append(row)

    placeholders = ", ".join("?" for _ in _COLUMNS)
    conn.executemany(
        f"INSERT INTO records ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
        rows,
    )
    conn.commit()
    return len(rows)


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["flags"] = json.loads(d.get("flags") or "[]")
    except (TypeError, ValueError):
        d["flags"] = []
    return d


def query(
    conn: sqlite3.Connection,
    *,
    search: Optional[str] = None,
    clinic_id: Optional[str] = None,
    category: Optional[str] = None,
    problematic_only: bool = False,
) -> list[dict]:
    """Filter records by free-text service search, clinic, category, or quality."""
    where: list[str] = []
    params: list = []

    if search:
        where.append(
            "(service_name_raw LIKE ? OR service_name_normalized LIKE ? OR service_name_kz LIKE ?)"
        )
        like = f"%{search}%"
        params += [like, like, like]
    if clinic_id:
        where.append("clinic_id = ?")
        params.append(clinic_id)
    if category:
        where.append("category = ?")
        params.append(category)
    if problematic_only:
        # Problematic = has any flag, missing price, or low confidence.
        where.append("(flags != '[]' OR price IS NULL OR confidence < 0.5)")

    sql = "SELECT * FROM records"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY clinic_name, service_name_normalized"

    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def distinct_clinics(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT DISTINCT clinic_id, clinic_name FROM records ORDER BY clinic_name"
    ).fetchall()
    return [(r["clinic_id"], r["clinic_name"]) for r in rows]
