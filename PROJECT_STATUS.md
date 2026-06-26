# MedRate — Project Status

A complete snapshot of what's built, how to run it, and what's verified.

- **Repo:** https://github.com/Goslinuly/MedRate
- **Working branch:** `build/pipeline` (not yet merged to `main`)
- **LLM provider:** Google Gemini (free tier) via the `google-genai` SDK
- **Default model:** `gemini-2.5-flash` (override with the `MODEL` env var)

---

## What it does

Upload a `.zip` / folder of clinic price lists in any format (Excel, CSV, PDF,
Word, scanned images/photos, Russian + Kazakh) → get one clean, searchable,
exportable table of services and prices.

Flow: **ingest → per-format extract → LLM extraction (text + vision) → normalize
→ canonicalize names → deduplicate → SQLite → Streamlit UI → `output.xlsx`.**

---

## File-by-file

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI: upload → process → search/filter → export |
| `db.py` | SQLite schema + search/filter queries |
| `pipeline/ingest.py` | Unzip / walk folder, dispatch each file by type |
| `pipeline/extract_excel.py` | `.xlsx` / `.xls` / `.csv` → table text |
| `pipeline/extract_pdf.py` | PDF: text layer vs scanned-page detection → text or rendered images |
| `pipeline/extract_docx.py` | Word → text (paragraphs + tables) |
| `pipeline/extract_image.py` | Images → base64 for vision |
| `pipeline/llm.py` | Gemini calls: structured-JSON extraction (text + vision) + name canonicalization |
| `pipeline/normalize.py` | Price/currency/category cleaning, flags, confidence |
| `pipeline/dedup.py` | Merge duplicates, flag price conflicts |
| `prompts/extraction.txt` | Extraction system prompt |
| `prompts/normalization.txt` | Name-canonicalization system prompt |
| `data/samples/clinic_alpha.csv` | Sample Russian price list for testing |
| `smoke_test.py` | Headless live end-to-end test (needs a real key) |
| `mock_e2e.py` | Headless end-to-end test with the Gemini call stubbed (no key) |

---

## Data model (one row per service)

`clinic_name`, `clinic_id`, `service_name_raw`, `service_name_normalized`,
`service_name_kz`, `category`, `price`, `price_min`, `price_max`, `currency`,
`unit`, `source_file`, `source_page`, `confidence`, `flags`, `notes`.

- **Categories:** consultation, lab tests, ultrasound, CT/MRI,
  x-ray/fluorography, dentistry, physiotherapy, surgery, procedures,
  vaccination, inpatient, other.
- **Flags:** `low_quality_scan`, `ambiguous_price`, `name_uncertain`,
  `price_is_range`, `currency_assumed`, `multi_column_layout`, `non_price_row`.

---

## How to run

```bash
# 1. Get the code
git clone https://github.com/Goslinuly/MedRate.git
cd MedRate
git checkout build/pipeline

# 2. Environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
#    (only for scanned PDFs) macOS: brew install poppler  |  Linux: apt-get install poppler-utils

# 3. Free API key
cp .env.example .env
#    edit .env -> GEMINI_API_KEY=...   (get it at https://aistudio.google.com -> "Get API key")

# 4a. Headless test (prints the unified table)
python smoke_test.py

# 4b. Full UI
streamlit run app.py
```

### Get a free Gemini key
1. Go to **https://aistudio.google.com**
2. Click **Get API key** (top-right) → **Create API key**
3. Copy it into `.env` as `GEMINI_API_KEY=...`
4. Free tier — no billing card required.

---

## Verification status

| Stage | Status |
|---|---|
| All modules compile / import | ✅ verified |
| Dependencies install (`google-genai`, pandas, pdfplumber, streamlit, …) | ✅ verified in a venv |
| Price parser & normalizer (ranges, "от X", KZT default, flags) | ✅ unit-tested |
| Full pipeline wiring (ingest → … → xlsx) with Gemini **stubbed** | ✅ end-to-end pass |
| **Live Gemini extraction quality** | ❌ **not yet run** — needs your key |

> The only unverified piece is the real Gemini API call. Run `smoke_test.py`
> with your key to confirm extraction quality.

---

## Known limitations

- Hackathon-MVP scale: tuned for ~5–10 files per archive.
- `gemini-2.5-flash` is strong on text formats (Excel/CSV/Word) and clean scans;
  on **low-quality phone photos** expect lower accuracy and more
  `low_quality_scan` / `name_uncertain` flags. Try `MODEL=gemini-2.5-pro` if
  scan quality matters.
- One LLM request per file with `max_output_tokens=16000`; very long price lists
  could be truncated (raise the cap or split if needed).
- Scanned-PDF rendering needs the system `poppler` package; without it, scanned
  PDFs are skipped (text PDFs/images still work).

---

## Next steps

- [ ] Run `smoke_test.py` with a real key → confirm live extraction
- [ ] Open a PR `build/pipeline` → `main`
- [ ] Add more sample files (real Excel/PDF/scans) to `data/samples/`
- [ ] Tune prompts on real data; consider per-page batching for large PDFs

---

## Key links

- Repo: https://github.com/Goslinuly/MedRate
- Branch: https://github.com/Goslinuly/MedRate/tree/build/pipeline
- Open a PR: https://github.com/Goslinuly/MedRate/pull/new/build/pipeline
- Free Gemini key: https://aistudio.google.com
- Gemini docs: https://ai.google.dev/gemini-api/docs
