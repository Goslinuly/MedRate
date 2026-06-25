"""No-API end-to-end verification.

Stubs ONLY the Gemini call (pipeline.llm._generate) and runs every other real
code path: ingest, content-part building, normalize, dedup, SQLite
storage/query, and xlsx export. Proves the wiring without a network call.
"""
from pipeline import dedup, ingest
from pipeline import llm as llm_mod
from pipeline import normalize

# --- 1. real ingest of the sample CSV -> chunks ---
docs = ingest.ingest("data/samples")
assert docs, "no docs ingested"
doc = docs[0]
assert doc["chunks"] and doc["chunks"][0]["kind"] == "text", doc
print(f"[ingest] {doc['source_file']} -> {len(doc['chunks'])} chunk(s); clinic={doc['clinic_name']}")

# --- 2. real content-part builder (what we'd send to Gemini) ---
parts = llm_mod._build_contents(doc["chunks"])
assert parts and getattr(parts[0], "text", "").startswith("DOCUMENT TEXT")
print(f"[content] built {len(parts)} part(s); first 60 chars: {parts[0].text[:60]!r}")

# --- 3. stub _generate; run the REAL extract_records + canonicalize wrappers ---
fake_records = [
    dict(service_name_raw="Консультация терапевта", service_name_normalized="Консультация терапевта",
         service_name_kz=None, category="consultation", price=5000, price_min=None, price_max=None,
         currency=None, unit=None, confidence=0.95, flags=[], notes=None),
    dict(service_name_raw="УЗИ органов брюшной полости", service_name_normalized="УЗИ брюшной полости",
         service_name_kz=None, category="ultrasound", price=None, price_min=8000, price_max=None,
         currency=None, unit=None, confidence=0.9, flags=["price_is_range"], notes=None),
    dict(service_name_raw="ВСЕГО ПО ПРАЙСУ", service_name_normalized=None, service_name_kz=None,
         category="other", price=None, price_min=None, price_max=None, currency=None, unit=None,
         confidence=0.4, flags=["non_price_row"], notes="section header"),
]


def fake_generate(client, *, model, system, contents, schema, max_output_tokens, retries=2):
    if schema is llm_mod.ExtractionResult:
        return llm_mod.ExtractionResult(records=[llm_mod.PriceRecord(**r) for r in fake_records])
    if schema is llm_mod.CanonicalMap:
        return llm_mod.CanonicalMap(mappings=[
            llm_mod.NameMapping(from_name="УЗИ брюшной полости", to_name="УЗИ органов брюшной полости"),
        ])
    raise AssertionError(schema)


llm_mod._generate = fake_generate
client = object()  # never actually used once _generate is stubbed

records = llm_mod.extract_records(client, doc["chunks"], clinic_name=doc["clinic_name"], source_file=doc["source_file"])
assert len(records) == 3 and records[0]["clinic_id"] == "clinic-alpha", records
print(f"[extract] {len(records)} records; provenance clinic_id={records[0]['clinic_id']!r}")

# --- 4. real normalize ---
records = normalize.normalize_all(records)
uzi = next(r for r in records if "брюшной" in r["service_name_raw"])
assert uzi["price_min"] == 8000 and uzi["currency"] == "KZT" and "currency_assumed" in uzi["flags"]
print(f"[normalize] УЗИ -> min={uzi['price_min']} cur={uzi['currency']} flags={uzi['flags']}")

# --- 5. real canonicalize wrapper (stubbed _generate) ---
names = [r.get("service_name_normalized") or r.get("service_name_raw") for r in records]
mapping = llm_mod.canonicalize_names(client, names)
for r in records:
    k = r.get("service_name_normalized") or r.get("service_name_raw")
    r["service_name_normalized"] = mapping.get(k, k)
print(f"[canonicalize] mapping applied: {mapping}")

# --- 6. real dedup ---
records = dedup.deduplicate(records)
print(f"[dedup] {len(records)} unified records")

# --- 7. real SQLite store + query ---
import db as dbmod  # noqa: E402
conn = dbmod.connect(":memory:")
dbmod.init_db(conn)
n = dbmod.insert_records(conn, records)
problem = dbmod.query(conn, problematic_only=True)
ultra = dbmod.query(conn, category="ultrasound")
print(f"[db] inserted={n} problematic={len(problem)} ultrasound={len(ultra)}")

# --- 8. real xlsx export ---
import app as appmod  # noqa: E402
xlsx = appmod.export_xlsx(appmod.to_dataframe(records))
assert xlsx[:2] == b"PK", "xlsx is not a valid zip/xlsx"
print(f"[export] output.xlsx = {len(xlsx)} bytes, valid")

print("\nALL STAGES PASSED (Gemini call stubbed).")
