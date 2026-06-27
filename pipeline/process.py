from pathlib import Path
from typing import Callable, Optional

from config import SAMPLES_DIR
from db import (
    add_unmatched,
    log_ingest,
    now_iso,
    store_raw,
    upsert_clinic,
    upsert_service,
)
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
    ref_index = build_ref_index()
    files = _collect_files(paths)
    stats = {"files": 0, "failed_files": 0, "services": 0, "unmatched": 0}
    queued: set[str] = set()

    for index, file_path in enumerate(files, start=1):
        if progress:
            progress(file_path.name, index, len(files))
        try:
            _process_file(conn, file_path, ref_index, queued, max_chunks)
            stats["files"] += 1
        except Exception as error:
            stats["failed_files"] += 1
            log_ingest(conn, file_path.name, "ingest", "error", f"{type(error).__name__}: {error}")
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


def _process_file(conn, file_path: Path, ref_index, queued: set, max_chunks: Optional[int] = None) -> None:
    meta = clinic_meta_from_filename(file_path)
    upsert_clinic(conn, {"clinic_id": meta["clinic_id"], "clinic_name": meta["clinic_name"]})

    docs = ingest(file_path)
    if not docs:
        log_ingest(conn, file_path.name, "extract", "empty", "no content extracted")
        return
    if max_chunks is not None:
        docs = docs[:max_chunks]

    from pipeline import llm

    seen_prices: dict[str, float] = {}
    for doc in docs:
        rows = llm.extract_rows(doc, conn=conn)
        store_raw(conn, doc.source_file, doc.source_page, rows)
        for row in rows:
            _store_row(conn, doc, row, ref_index, seen_prices, queued)
    log_ingest(conn, file_path.name, "extract", "ok", f"{len(docs)} chunks")
    conn.commit()


def _store_row(conn, doc: RawDoc, row: dict, ref_index, seen_prices: dict, queued: set) -> bool:
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
        "category": map_category(row.get("category_guess")),
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
