from datetime import datetime, timezone

PRICE_ANOMALY_RATIO = 0.5
HIGH_CONFIDENCE = 0.9

CRITICAL_FLAGS = {
    "invalid_price",
    "nonresident_below_resident",
    "future_date",
    "price_anomaly",
    "ambiguous_price",
}


def validate_record(record: dict) -> list[str]:
    flags: list[str] = []
    resident = record.get("price_resident")
    nonresident = record.get("price_nonresident")

    if resident is not None and resident <= 0:
        flags.append("invalid_price")
    if resident is not None and nonresident is not None and nonresident < resident:
        flags.append("nonresident_below_resident")

    year = record.get("source_year")
    if year and year > datetime.now(timezone.utc).year:
        flags.append("future_date")

    return flags


def verification_status(record: dict, flags: list[str]) -> tuple[int, str]:
    if record.get("ref_service_id") is None:
        return 0, "не сопоставлено со справочником"
    critical = [f for f in flags if f in CRITICAL_FLAGS]
    if critical:
        return 0, "требует ревью: " + ", ".join(sorted(set(critical)))
    if (record.get("confidence") or 0) >= HIGH_CONFIDENCE:
        return 1, ""
    return 0, "низкая уверенность сопоставления"


def finalize_anomalies(conn) -> None:
    rows = conn.execute(
        """
        SELECT record_id, clinic_id, dedup_key, source_year,
               COALESCE(price, price_min, price_max) AS value, flags
        FROM services
        WHERE COALESCE(price, price_min, price_max) IS NOT NULL
        ORDER BY clinic_id, dedup_key, source_year
        """
    ).fetchall()

    groups: dict[tuple, list] = {}
    for row in rows:
        groups.setdefault((row["clinic_id"], row["dedup_key"]), []).append(row)

    import json

    for series in groups.values():
        if len(series) < 2:
            continue
        for previous, current in zip(series, series[1:]):
            base = previous["value"]
            if not base:
                continue
            if abs(current["value"] - base) / base > PRICE_ANOMALY_RATIO:
                flags = set(json.loads(current["flags"] or "[]"))
                flags.add("price_anomaly")
                conn.execute(
                    "UPDATE services SET flags = ?, is_verified = 0, verification_note = ? WHERE record_id = ?",
                    (json.dumps(sorted(flags), ensure_ascii=False), "аномалия цены > 50%", current["record_id"]),
                )
    conn.commit()
