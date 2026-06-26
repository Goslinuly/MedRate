from typing import Optional


def make_dedup_key(
    clinic_id: str,
    ref_service_id: Optional[int],
    service_name_norm: Optional[str],
    service_name_raw: str,
    unit: Optional[str],
) -> str:
    if ref_service_id is not None:
        service_part = f"ref:{ref_service_id}"
    elif service_name_norm:
        service_part = f"norm:{service_name_norm.lower()}"
    else:
        service_part = f"raw:{(service_name_raw or '').lower().strip()}"
    return f"{clinic_id}|{service_part}|{(unit or '').lower().strip()}"


def finalize_active(conn) -> None:
    rows = conn.execute(
        "SELECT record_id, clinic_id, dedup_key, source_year FROM services"
    ).fetchall()
    groups: dict[tuple, list[tuple[int, int]]] = {}
    for row in rows:
        key = (row["clinic_id"], row["dedup_key"])
        groups.setdefault(key, []).append((row["record_id"], row["source_year"] or 0))
    for members in groups.values():
        latest = max(year for _, year in members)
        for record_id, year in members:
            conn.execute(
                "UPDATE services SET is_active = ? WHERE record_id = ?",
                (1 if year == latest else 0, record_id),
            )
    conn.commit()
