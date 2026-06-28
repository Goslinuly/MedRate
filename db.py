import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS clinics (
    clinic_id     TEXT PRIMARY KEY,
    clinic_name   TEXT,
    city          TEXT,
    address       TEXT,
    phone         TEXT,
    working_hours TEXT,
    bin           TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    lat           REAL,
    lon           REAL,
    is_active     INTEGER DEFAULT 1,
    created_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS price_documents (
    doc_id      TEXT PRIMARY KEY,
    partner_id  TEXT,
    file_name   TEXT,
    file_format TEXT,
    effective_date TEXT,
    parsed_at   TEXT,
    parse_status TEXT,
    parse_log   TEXT,
    chunks      INTEGER
);

CREATE TABLE IF NOT EXISTS services (
    record_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    clinic_id         TEXT,
    clinic_name       TEXT,
    city              TEXT,
    address           TEXT,
    phone             TEXT,
    working_hours     TEXT,
    service_name_raw  TEXT,
    service_name_norm TEXT,
    service_name_kz   TEXT,
    ref_service_id    INTEGER,
    category          TEXT,
    price             REAL,
    price_min         REAL,
    price_max         REAL,
    price_resident    REAL,
    price_nonresident REAL,
    price_original    REAL,
    currency          TEXT,
    currency_original TEXT,
    unit              TEXT,
    duration_days     INTEGER,
    source_file       TEXT,
    source_page       INTEGER,
    source_year       INTEGER,
    source_url        TEXT,
    parsed_at         TEXT,
    is_active         INTEGER DEFAULT 1,
    is_verified       INTEGER DEFAULT 0,
    verification_note TEXT,
    confidence        REAL,
    flags             TEXT,
    notes             TEXT,
    dedup_key         TEXT,
    UNIQUE(dedup_key, source_file)
);

CREATE TABLE IF NOT EXISTS unmatched_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name_raw TEXT,
    clinic_id        TEXT,
    source_file      TEXT,
    source_page      INTEGER,
    candidates       TEXT,
    created_at       TEXT,
    UNIQUE(clinic_id, service_name_raw)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT,
    stage       TEXT,
    status      TEXT,
    reason      TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS raw_extractions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file  TEXT,
    page         INTEGER,
    payload_json TEXT,
    parsed_at    TEXT
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key  TEXT PRIMARY KEY,
    payload    TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS reference_extra (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE,
    category   TEXT,
    specialty  TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_services_norm ON services(service_name_norm);
CREATE INDEX IF NOT EXISTS idx_services_clinic ON services(clinic_id);
CREATE INDEX IF NOT EXISTS idx_services_category ON services(category);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path = DB_PATH, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.create_function("ulower", 1, lambda value: value.lower() if value else value)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


ADDED_SERVICE_COLUMNS = {
    "price_resident": "REAL",
    "price_nonresident": "REAL",
    "price_original": "REAL",
    "currency_original": "TEXT",
    "is_verified": "INTEGER DEFAULT 0",
    "verification_note": "TEXT",
    "service_code_source": "TEXT",
    "effective_date": "TEXT",
}

ADDED_CLINIC_COLUMNS = {
    "bin": "TEXT",
    "contact_email": "TEXT",
    "contact_phone": "TEXT",
    "lat": "REAL",
    "lon": "REAL",
    "is_active": "INTEGER DEFAULT 1",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    _add_columns(conn, "services", ADDED_SERVICE_COLUMNS)
    _add_columns(conn, "clinics", ADDED_CLINIC_COLUMNS)


def _add_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column, decl in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def upsert_clinic(conn: sqlite3.Connection, clinic: dict[str, Any]) -> None:
    now = now_iso()
    conn.execute(
        """
        INSERT INTO clinics (clinic_id, clinic_name, city, address, phone, working_hours,
                             bin, contact_email, contact_phone, is_active, created_at, updated_at)
        VALUES (:clinic_id, :clinic_name, :city, :address, :phone, :working_hours,
                :bin, :contact_email, :contact_phone, 1, :now, :now)
        ON CONFLICT(clinic_id) DO UPDATE SET
            clinic_name=COALESCE(excluded.clinic_name, clinic_name),
            city=COALESCE(excluded.city, city),
            address=COALESCE(excluded.address, address),
            phone=COALESCE(excluded.phone, phone),
            working_hours=COALESCE(excluded.working_hours, working_hours),
            bin=COALESCE(excluded.bin, bin),
            contact_email=COALESCE(excluded.contact_email, contact_email),
            contact_phone=COALESCE(excluded.contact_phone, contact_phone),
            updated_at=excluded.updated_at
        """,
        {
            "clinic_id": clinic.get("clinic_id"),
            "clinic_name": clinic.get("clinic_name"),
            "city": clinic.get("city"),
            "address": clinic.get("address"),
            "phone": clinic.get("phone"),
            "working_hours": clinic.get("working_hours"),
            "bin": clinic.get("bin"),
            "contact_email": clinic.get("contact_email"),
            "contact_phone": clinic.get("contact_phone"),
            "now": now,
        },
    )


def upsert_document(conn: sqlite3.Connection, doc: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO price_documents
            (doc_id, partner_id, file_name, file_format, effective_date, parsed_at, parse_status, parse_log, chunks)
        VALUES (:doc_id, :partner_id, :file_name, :file_format, :effective_date, :parsed_at, :parse_status, :parse_log, :chunks)
        ON CONFLICT(doc_id) DO UPDATE SET
            parse_status=excluded.parse_status,
            parse_log=excluded.parse_log,
            parsed_at=excluded.parsed_at,
            chunks=excluded.chunks
        """,
        {
            "doc_id": doc.get("doc_id"),
            "partner_id": doc.get("partner_id"),
            "file_name": doc.get("file_name"),
            "file_format": doc.get("file_format"),
            "effective_date": doc.get("effective_date"),
            "parsed_at": doc.get("parsed_at") or now_iso(),
            "parse_status": doc.get("parse_status"),
            "parse_log": doc.get("parse_log"),
            "chunks": doc.get("chunks"),
        },
    )


SERVICE_COLUMNS = [
    "clinic_id", "clinic_name", "city", "address", "phone", "working_hours",
    "service_name_raw", "service_name_norm", "service_name_kz", "ref_service_id",
    "service_code_source", "category", "price", "price_min", "price_max",
    "price_resident", "price_nonresident",
    "price_original", "currency", "currency_original", "unit",
    "duration_days", "source_file", "source_page", "source_year", "source_url",
    "effective_date", "parsed_at", "is_active", "is_verified", "verification_note",
    "confidence", "flags", "notes", "dedup_key",
]


def upsert_service(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    values = {col: row.get(col) for col in SERVICE_COLUMNS}
    if isinstance(values["flags"], (list, dict)):
        values["flags"] = json.dumps(values["flags"], ensure_ascii=False)
    placeholders = ", ".join(f":{col}" for col in SERVICE_COLUMNS)
    columns = ", ".join(SERVICE_COLUMNS)
    updates = ", ".join(
        f"{col}=excluded.{col}" for col in SERVICE_COLUMNS if col not in ("dedup_key", "source_file")
    )
    conn.execute(
        f"""
        INSERT INTO services ({columns}) VALUES ({placeholders})
        ON CONFLICT(dedup_key, source_file) DO UPDATE SET {updates}
        """,
        values,
    )


def add_unmatched(conn: sqlite3.Connection, row: dict[str, Any], candidates: list[dict]) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO unmatched_queue
            (service_name_raw, clinic_id, source_file, source_page, candidates, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("service_name_raw"),
            row.get("clinic_id"),
            row.get("source_file"),
            row.get("source_page"),
            json.dumps(candidates, ensure_ascii=False),
            now_iso(),
        ),
    )


def log_ingest(conn: sqlite3.Connection, source_file: str, stage: str, status: str, reason: str = "") -> None:
    conn.execute(
        "INSERT INTO ingest_log (source_file, stage, status, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (source_file, stage, status, reason, now_iso()),
    )


def store_raw(conn: sqlite3.Connection, source_file: str, page: Optional[int], payload: Any) -> None:
    conn.execute(
        "INSERT INTO raw_extractions (source_file, page, payload_json, parsed_at) VALUES (?, ?, ?, ?)",
        (source_file, page, json.dumps(payload, ensure_ascii=False), now_iso()),
    )


def cache_get(conn: sqlite3.Connection, cache_key: str) -> Optional[Any]:
    row = conn.execute("SELECT payload FROM llm_cache WHERE cache_key = ?", (cache_key,)).fetchone()
    return json.loads(row["payload"]) if row else None


def cache_set(conn: sqlite3.Connection, cache_key: str, payload: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO llm_cache (cache_key, payload, created_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(payload, ensure_ascii=False), now_iso()),
    )
    conn.commit()


REFERENCE_EXTRA_ID_OFFSET = 1_000_000


def add_reference(conn: sqlite3.Connection, name: str, category: str = "", specialty: str = "") -> int:
    """Create an operator-defined catalogue entry; returns a stable ref_service_id."""
    cur = conn.execute(
        """
        INSERT INTO reference_extra (name, category, specialty, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET category=excluded.category, specialty=excluded.specialty
        """,
        (name.strip(), category, specialty, now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM reference_extra WHERE name = ?", (name.strip(),)).fetchone()
    return REFERENCE_EXTRA_ID_OFFSET + (row["id"] if row else cur.lastrowid)


def reference_extra_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, category, specialty FROM reference_extra").fetchall()
    return [
        {
            "id": REFERENCE_EXTRA_ID_OFFSET + r["id"],
            "name": r["name"],
            "category": r["category"] or "",
            "specialty": r["specialty"] or "",
            "synonyms": [],
        }
        for r in rows
    ]


def clear_pipeline_tables(conn: sqlite3.Connection) -> None:
    for table in ("services", "clinics", "unmatched_queue", "ingest_log", "raw_extractions", "price_documents"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def fetch_rows(conn: sqlite3.Connection, query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return conn.execute(query, tuple(params)).fetchall()
