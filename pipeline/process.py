import hashlib
import shutil
from pathlib import Path
from typing import Callable, Optional

from config import SAMPLES_DIR, UPLOADS_DIR
from db import (
    add_unmatched,
    log_ingest,
    now_iso,
    store_raw,
    upsert_clinic,
    upsert_document,
    upsert_service,
)

FILE_FORMAT = {
    ".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xls": "xls",
    ".csv": "csv", ".png": "image", ".jpg": "image", ".jpeg": "image",
}


def _doc_id(clinic_id: str, file_name: str) -> str:
    return hashlib.sha1(f"{clinic_id}:{file_name}".encode("utf-8")).hexdigest()[:16]


def _save_original(file_path: Path) -> None:
    try:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        destination = UPLOADS_DIR / file_path.name
        if destination.resolve() != file_path.resolve():
            shutil.copy2(file_path, destination)
    except Exception:
        pass  # provenance copy is best-effort, never blocks ingestion
from pipeline.dedup import finalize_active, make_dedup_key
from pipeline.ingest import ingest, unzip_or_walk
from pipeline.models import RawDoc, clinic_meta_from_filename
from pipeline.normalize import build_ref_index, canonicalize, map_category, parse_price
from pipeline.validate import finalize_anomalies, validate_record, verification_status

ProgressCallback = Callable[[str, int, int], None]


def process_samples(conn, progress: Optional[ProgressCallback] = None) -> dict:
    return process_paths([SAMPLES_DIR], conn, progress)


def process_paths(
    paths, conn, progress: Optional[ProgressCallback] = None, max_chunks: Optional[int] = None
) -> dict:
    ref_index = build_ref_index(conn)
    files = _collect_files(paths)
    stats = {"files": 0, "failed_files": 0, "services": 0, "unmatched": 0}
    queued: set[str] = set()

    for index, file_path in enumerate(files, start=1):
        if progress:
            progress(file_path.name, index, len(files))
        meta = clinic_meta_from_filename(file_path)
        doc_id = _doc_id(meta["clinic_id"], file_path.name)
        try:
            _process_file(conn, file_path, ref_index, queued, max_chunks, meta, doc_id)
            stats["files"] += 1
        except Exception as error:
            stats["failed_files"] += 1
            reason = f"{type(error).__name__}: {error}"
            log_ingest(conn, file_path.name, "ingest", "error", reason)
            upsert_document(conn, {
                "doc_id": doc_id,
                "partner_id": meta["clinic_id"],
                "file_name": file_path.name,
                "file_format": FILE_FORMAT.get(file_path.suffix.lower(), "other"),
                "effective_date": str(meta["source_year"]) if meta.get("source_year") else None,
                "parse_status": "error",
                "parse_log": reason,
                "chunks": 0,
            })
            conn.commit()

    finalize_active(conn)
    finalize_anomalies(conn)
    conn.commit()
    stats["services"] = conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    stats["unmatched"] = conn.execute("SELECT COUNT(*) FROM unmatched_queue").fetchone()[0]
    stats["normalized"] = conn.execute(
        "SELECT COUNT(*) FROM services WHERE service_name_norm IS NOT NULL"
    ).fetchone()[0]
    return stats


def _collect_files(paths) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        files.extend(unzip_or_walk(Path(path)))
    return files


def _process_file(
    conn, file_path: Path, ref_index, queued: set, max_chunks: Optional[int] = None,
    meta: Optional[dict] = None, doc_id: Optional[str] = None,
) -> None:
    meta = meta or clinic_meta_from_filename(file_path)
    doc_id = doc_id or _doc_id(meta["clinic_id"], file_path.name)
    effective_date = str(meta["source_year"]) if meta.get("source_year") else None
    file_format = FILE_FORMAT.get(file_path.suffix.lower(), "other")

    upsert_clinic(conn, {"clinic_id": meta["clinic_id"], "clinic_name": meta["clinic_name"]})
    _save_original(file_path)

    document = {
        "doc_id": doc_id,
        "partner_id": meta["clinic_id"],
        "file_name": file_path.name,
        "file_format": file_format,
        "effective_date": effective_date,
        "parse_status": "processing",
        "parse_log": "",
        "chunks": 0,
    }
    upsert_document(conn, document)

    docs = ingest(file_path)
    if not docs:
        log_ingest(conn, file_path.name, "extract", "empty", "no content extracted")
        upsert_document(conn, {**document, "parse_status": "error", "parse_log": "no content extracted"})
        conn.commit()
        return
    if max_chunks is not None:
        docs = docs[:max_chunks]
    if file_format == "pdf" and any(d.is_image for d in docs):
        document["file_format"] = "scan_pdf"

    from pipeline import llm

    seen_prices: dict[str, float] = {}
    contacts: dict[str, str] = {}
    stored = 0
    for doc in docs:
        rows = llm.extract_rows(doc, conn=conn)
        store_raw(conn, doc.source_file, doc.source_page, rows)
        for row in rows:
            _collect_contacts(contacts, row)
            if _store_row(conn, doc, row, ref_index, seen_prices, queued, effective_date):
                stored += 1

    if contacts:
        upsert_clinic(conn, {"clinic_id": meta["clinic_id"], "clinic_name": meta["clinic_name"], **contacts})
        conn.execute(
            """
            UPDATE services SET city = COALESCE(city, :city), address = COALESCE(address, :address),
                                phone = COALESCE(phone, :phone)
            WHERE clinic_id = :clinic_id
            """,
            {
                "city": contacts.get("city"),
                "address": contacts.get("address"),
                "phone": contacts.get("phone"),
                "clinic_id": meta["clinic_id"],
            },
        )
    log_ingest(conn, file_path.name, "extract", "ok", f"{len(docs)} chunks")
    upsert_document(conn, {
        **document,
        "parse_status": "needs_review" if stored == 0 else "done",
        "parse_log": f"{len(docs)} chunks, {stored} rows",
        "chunks": len(docs),
    })
    conn.commit()


_CONTACT_FIELDS = {
    "clinic_city": "city",
    "clinic_address": "address",
    "clinic_phone": "phone",
    "clinic_email": "contact_email",
    "clinic_bin": "bin",
}


def _collect_contacts(contacts: dict, row: dict) -> None:
    """First non-empty clinic contact value from the document wins."""
    for source, target in _CONTACT_FIELDS.items():
        value = row.get(source)
        if value and target not in contacts:
            contacts[target] = str(value).strip()


def _store_row(conn, doc: RawDoc, row: dict, ref_index, seen_prices: dict, queued: set,
               effective_date: Optional[str] = None) -> bool:
    flags = list(row.get("flags") or [])
    name_raw = (row.get("service_name_raw") or "").strip()
    if "non_price_row" in flags or not name_raw:
        return False

    price_info = parse_price(row.get("price_raw"), row.get("currency_raw"))
    nonresident_info = parse_price(row.get("price_nonresident_raw"), row.get("currency_raw"))
    canon = canonicalize(name_raw, ref_index, conn=conn)
    flags = sorted(set(flags + price_info["flags"] + canon["flags"]))

    dedup_key = make_dedup_key(
        doc.clinic_id, canon["ref_service_id"], canon["service_name_norm"], name_raw, row.get("unit")
    )
    main_price = price_info["price"] if price_info["price"] is not None else price_info["price_min"]
    if main_price is not None:
        previous = seen_prices.get(dedup_key)
        if previous is not None and previous != main_price:
            flags = sorted(set(flags + ["ambiguous_price"]))
        seen_prices[dedup_key] = main_price

    nonresident_price = nonresident_info["price"] if nonresident_info["price"] is not None else nonresident_info["price_min"]
    record = {
        "clinic_id": doc.clinic_id,
        "clinic_name": doc.clinic_name,
        "city": None,
        "address": None,
        "phone": None,
        "working_hours": None,
        "service_name_raw": name_raw,
        "service_name_norm": canon["service_name_norm"],
        "service_name_kz": row.get("service_name_kz"),
        "ref_service_id": canon["ref_service_id"],
        "service_code_source": row.get("service_code_source") or row.get("service_code"),
        "category": canon.get("category") or map_category(row.get("category_guess")),
        "price": price_info["price"],
        "price_min": price_info["price_min"],
        "price_max": price_info["price_max"],
        "price_resident": main_price,
        "price_nonresident": nonresident_price,
        "price_original": price_info["price_original"],
        "currency": price_info["currency"],
        "currency_original": price_info["currency_original"],
        "unit": row.get("unit"),
        "duration_days": row.get("duration_days"),
        "source_file": doc.source_file,
        "source_page": doc.source_page,
        "source_year": doc.source_year,
        "source_url": None,
        "effective_date": effective_date,
        "parsed_at": now_iso(),
        "is_active": 1,
        "confidence": _combine_confidence(row.get("confidence"), canon),
        "flags": flags,
        "notes": row.get("notes"),
        "dedup_key": dedup_key,
    }
    flags = sorted(set(flags + validate_record(record)))
    record["flags"] = flags
    record["is_verified"], record["verification_note"] = verification_status(record, flags)
    upsert_service(conn, record)
    if canon["ref_service_id"] is None and dedup_key not in queued:
        add_unmatched(conn, record, canon["candidates"])
        queued.add(dedup_key)
    return True


def _combine_confidence(extract_confidence, canon: dict) -> float:
    base = float(extract_confidence) if extract_confidence is not None else 0.6
    if canon["ref_service_id"] is not None:
        return round((base + canon["confidence"]) / 2, 2)
    return round(base * 0.7, 2)
