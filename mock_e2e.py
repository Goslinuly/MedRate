"""No-API end-to-end verification.

Stubs ONLY the two Claude calls (extraction + canonicalization) and runs every
other real code path: ingest, content-block building, normalize, dedup, SQLite
storage/query, and xlsx export. Proves the wiring without a network call.
"""
import types

from pipeline import dedup, ingest
from pipeline import llm as llm_mod
from pipeline import normalize

# --- 1. real ingest of the sample CSV -> chunks ---
docs = ingest.ingest("data/samples")
assert docs, "no docs ingested"
doc = docs[0]
assert doc["chunks"] and doc["chunks"][0]["kind"] == "text", doc
print(f"[ingest] {doc['source_file']} -> {len(doc['chunks'])} chunk(s); clinic={doc['clinic_name']}")

# --- 2. real content-block builder (what we'd send to Claude) ---
blocks = llm_mod._build_content(doc["chunks"])
assert blocks and blocks[0]["type"] == "text" and "DOCUMENT TEXT" in blocks[0]["text"]
print(f"[content] built {len(blocks)} block(s); first 60 chars: {blocks[0]['text'][:60]!r}")

# --- 3. stub the extraction call; run the REAL extract_records wrapper ---
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


def fake_extract(self, **kwargs):
    recs = [llm_mod.PriceRecord(**r) for r in fake_records]
    return types.SimpleNamespace(parsed_output=llm_mod.ExtractionResult(records=recs), stop_reason="end_turn")


class FakeMessages:
    parse = fake_extract


class FakeClient:
    messages = FakeMessages()


client = FakeClient()
records = llm_mod.extract_records(client, doc["chunks"], clinic_name=doc["clinic_name"], source_file=doc["source_file"])
assert len(records) == 3 and records[0]["clinic_id"] == "clinic-alpha", records
print(f"[extract] {len(records)} records; provenance clinic_id={records[0]['clinic_id']!r}")

# --- 4. real normalize ---
records = normalize.normalize_all(records)
uzi = next(r for r in records if "брюшной" in r["service_name_raw"])
assert uzi["price_min"] == 8000 and uzi["currency"] == "KZT" and "currency_assumed" in uzi["flags"]
print(f"[normalize] УЗИ -> min={uzi['price_min']} cur={uzi['currency']} flags={uzi['flags']}")

# --- 5. stub canonicalization; run the REAL wrapper ---
def fake_canon(self, **kwargs):
    return types.SimpleNamespace(
        parsed_output=llm_mod.CanonicalMap(mappings=[
            llm_mod.NameMapping(from_name="УЗИ брюшной полости", to_name="УЗИ органов брюшной полости"),
        ]),
        stop_reason="end_turn",
    )

FakeMessages.parse = fake_canon
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

print("\nALL STAGES PASSED (LLM calls stubbed).")
