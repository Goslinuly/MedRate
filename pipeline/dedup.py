"""Deduplicate & flag conflicts.

The same service can appear multiple times for one clinic (repeated rows, the
same item across sheets). Merge rows that share (clinic, canonical service,
category). When merged rows disagree on price, keep the highest-confidence row
and record the conflict in `notes` + an `ambiguous_price` flag.
"""
from __future__ import annotations

from collections import defaultdict


def _key(record: dict) -> tuple:
    name = (record.get("service_name_normalized") or record.get("service_name_raw") or "").strip().lower()
    return (record.get("clinic_id"), name, record.get("category"))


def _prices_conflict(a: dict, b: dict) -> bool:
    pa, pb = a.get("price"), b.get("price")
    if pa is None or pb is None:
        return False
    # Treat <1% apart as the same price.
    return abs(pa - pb) > max(1.0, 0.01 * max(pa, pb))


def deduplicate(records: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in records:
        groups[_key(rec)].append(rec)

    merged: list[dict] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue

        # Keep the most confident row as the winner.
        group = sorted(group, key=lambda r: r.get("confidence") or 0.0, reverse=True)
        winner = dict(group[0])
        flags = list(winner.get("flags") or [])

        conflicting_prices = []
        for other in group[1:]:
            if _prices_conflict(winner, other) and other.get("price") is not None:
                conflicting_prices.append(other["price"])

        if conflicting_prices:
            if "ambiguous_price" not in flags:
                flags.append("ambiguous_price")
            note = winner.get("notes") or ""
            conflict_txt = "price conflict across rows: " + ", ".join(
                f"{p:g}" for p in sorted(set(conflicting_prices))
            )
            winner["notes"] = (note + "; " if note else "") + conflict_txt

        # Merged rows came from possibly several source files.
        sources = {r.get("source_file") for r in group if r.get("source_file")}
        if len(sources) > 1:
            winner["source_file"] = ", ".join(sorted(sources))

        winner["flags"] = flags
        merged.append(winner)

    return merged
