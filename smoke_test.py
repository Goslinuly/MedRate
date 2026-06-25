"""Headless end-to-end smoke test (no Streamlit). Run from the repo root:

    ANTHROPIC_API_KEY=... .venv/bin/python smoke_test.py
"""
import json

from pipeline import dedup, ingest
from pipeline import llm as llm_mod
from pipeline import normalize

client = llm_mod.get_client()
print("model:", llm_mod.get_model())

docs = ingest.ingest("data/samples")
print(f"ingested {len(docs)} doc(s):", [(d['source_file'], len(d['chunks']), d['error']) for d in docs])

records = []
for d in docs:
    if d["chunks"]:
        recs = llm_mod.extract_records(
            client, d["chunks"], clinic_name=d["clinic_name"], source_file=d["source_file"]
        )
        print(f"  {d['source_file']}: {len(recs)} records")
        records.extend(recs)

records = normalize.normalize_all(records)
names = [r.get("service_name_normalized") or r.get("service_name_raw") for r in records]
mapping = llm_mod.canonicalize_names(client, names)
for r in records:
    k = r.get("service_name_normalized") or r.get("service_name_raw")
    r["service_name_normalized"] = mapping.get(k, k)
records = dedup.deduplicate(records)

print(f"\nFINAL: {len(records)} unified records\n")
for r in records:
    print(json.dumps({
        "service": r["service_name_normalized"],
        "raw": r["service_name_raw"],
        "cat": r["category"],
        "price": r["price"], "min": r["price_min"], "max": r["price_max"],
        "cur": r["currency"], "conf": r["confidence"], "flags": r["flags"],
    }, ensure_ascii=False))
