# MedRate

**MedRate** is a platform that automatically processes price lists from partner clinics — regardless of format — and turns them into a single clean, searchable database of services and prices.

Clinics send their price lists in whatever format they have: an Excel sheet, a text PDF, a scanned document, a photo taken on a phone, a Word file. Column layouts differ, headers sit on random rows, languages mix (Russian and Kazakh), and some files are just images with no machine-readable text. Unifying all of that by hand takes hours per clinic and breaks the moment a price changes.

MedRate does it for you: **upload an archive → get a clean, unified, comparable table.**

---

## ✨ Features

- 📥 **Any format in** — `.xlsx`, `.xls`, `.csv`, `.pdf` (text & scanned), `.docx`, `.png`, `.jpg`, `.jpeg`
- 🧠 **Model-powered extraction** — Google Gemini reads each document the way a human would: understanding table structure, abbreviations, and messy layouts
- 👁️ **Vision for scans & photos** — low-quality scans and phone photos are read via vision, not brittle OCR rules
- 🌐 **Bilingual** — handles mixed Russian / Kazakh text and preserves both
- 🔗 **Service normalization** — the same service named differently across clinics maps to one canonical name from the reference catalogue
- 💰 **Smart prices** — ranges and "from X" are split into `price_min` / `price_max`; numbers are cleaned, never invented
- 🚩 **Trust signals** — every row gets a `confidence` score and `flags`; unreadable values become `null`, never a guess
- 🔍 **Search & filter** — by service, city, category, clinic, price range, verification state, and quality flags
- 📊 **Market comparison** — clinic-by-clinic price comparison, market median, outlier detection, resident/non-resident prices
- 🧾 **Operator workflow** — archive upload, processing status, source-document preview, verification queue, and unmatched-service matching
- 🗺️ **Geo & analytics** — clinic map data, optional geocoding, basket optimization, price history, and quality report export

---

## 🏗️ How it works

```
Archive (.zip / folder)
        │
        ▼
   ┌─────────┐   detect type & preprocess
   │ Ingest  │──────────────────────────────┐
   └─────────┘                               │
   Excel/CSV → table text (header detection) │
   Text PDF  → page text                     ▼
   Scan PDF  → page images           ┌──────────────┐
   DOCX      → text                  │    Gemini    │  extraction (text + vision)
   Images    → base64                └──────────────┘
                                            │  strict JSON, temperature 0
                                            ▼
                                   ┌──────────────────┐
                                   │   Normalize      │  prices, currency, categories
                                   │   Canonicalize   │  exact → fuzzy → model tie-break
                                   │   Deduplicate    │  merge, history, flag conflicts
                                   └──────────────────┘
                                            │
                                            ▼
                                  SQLite
                                     │
                                     ├── FastAPI REST API → Next.js web UI
                                     └── Streamlit legacy UI
```

The core idea: let the model do the hard part — understanding a messy document and pulling out structured data — and build thin, reliable orchestration around it (a fixed JSON schema, vision for scans, three-tier name canonicalization, response caching, and honest `confidence` / `flags`). No per-format parsers, no per-clinic rules, no hard-coded header rows.

---

## 📦 Data schema

Each price line becomes one structured record in the `services` table:

| Field | Description |
|---|---|
| `clinic_id`, `clinic_name` | Clinic slug and name |
| `city`, `address`, `phone`, `working_hours` | Clinic details when present in the file, else `null` |
| `service_name_raw` | Exactly as written in the document |
| `service_name_norm` | Canonical Russian name from the reference catalogue (`null` if unmatched) |
| `service_name_kz` | Kazakh name, if present |
| `ref_service_id` | Reference catalogue id, `null` if unmatched |
| `category` | One of the fixed categories below |
| `price`, `price_min`, `price_max` | Main price or range in KZT |
| `price_resident`, `price_nonresident` | Resident / non-resident prices when a clinic publishes separate tariffs |
| `price_original`, `currency_original`, `currency` | Original amount/currency and normalized KZT currency |
| `unit`, `duration_days` | e.g. `прием`, `анализ`, analysis turnaround |
| `source_file`, `source_page`, `source_year`, `source_url`, `effective_date` | Provenance and source validity |
| `parsed_at`, `is_active`, `is_verified`, `verification_note` | Import time, freshness, and operator verification state |
| `confidence`, `flags`, `notes` | Quality signals & comments |

**Categories:** `consultation`, `lab_tests`, `ultrasound`, `ct_mri`, `xray`, `dentistry`, `physiotherapy`, `surgery`, `procedures`, `vaccination`, `inpatient`, `other`.

**Flags:** `low_quality_scan`, `ambiguous_price`, `name_uncertain`, `price_is_range`, `currency_assumed`, `multi_column_layout`, `non_price_row`, `unmatched_service`, `kzt_converted_from_usd`, `kzt_converted_from_rub`, `invalid_price`, `nonresident_below_resident`, `future_date`, `price_anomaly`.

Supporting tables:

- `clinics` — partner profile, contacts, BIN/email/phone fields, optional `lat`/`lon`
- `price_documents` — uploaded source documents, parse status, parse log, chunk count
- `unmatched_queue` — services that need manual matching to the reference catalogue
- `reference_extra` — operator-created reference terms
- `raw_extractions`, `ingest_log`, `llm_cache` — audit trail, processing log, and model cache

---

## 🛠️ Tech stack

- **Python 3.9+**
- **Google Gemini** via the `google-genai` SDK — text & vision extraction
- **pandas** + **openpyxl** + **xlrd** — Excel / CSV (including legacy `.xls`)
- **pdfplumber** — PDF text layer
- **pdf2image** (+ poppler) — render scanned pages
- **python-docx** — Word
- **Pillow** — image handling
- **rapidfuzz** — fuzzy reference matching
- **SQLite** — storage
- **FastAPI** (+ Scalar) — REST API with OpenAPI docs
- **Next.js 16** (React 19, TypeScript, Tailwind) — product web UI (`web/`)
- **Streamlit** — legacy/analyst UI (`app.py`, kept as a fallback)

---

## 🚀 Getting started

```bash
# 1. Clone
git clone https://github.com/Goslinuly/MedRate.git
cd MedRate

# 2. Environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. System dependency for scanned PDFs
#    macOS:  brew install poppler
#    Linux:  apt-get install poppler-utils

# 4. API key
cp .env.example .env        # add your GOOGLE_API_KEY
```

### Web product UI (recommended)

The product experience is a Next.js frontend on top of the FastAPI backend, split into a
public search and an operator panel.

```bash
# Terminal 1 — backend API (http://localhost:8000, docs at /docs and /reference)
uvicorn api:app --port 8000

# Terminal 2 — frontend (http://localhost:3000)
cd web
npm install
npm run dev
```

Open **http://localhost:3000**:
- **Public search** (`/`) — service catalogue with category/city filters and price ranges.
- **Service page** (`/service/[id]`) — partners for one normalized service, cheapest options, market median, outliers, and price history.
- **Clinic page** (`/clinic/[id]`) — full active price list for one partner.
- **Partners** (`/partners`) — clinic list.
- **Map** (`/map`) — partners with coordinates from the API.
- **Basket** (`/basket`) — optimize a set of services across clinics.
- **Operator panel** (`/admin`) — dashboard with normalization %, flags, ingest log, verification and matching status.
- **Upload** (`/admin/upload`) — upload price archives/files and upload/extend the reference catalogue.
- **Verification queue** (`/admin/verify`) — approve, correct, or reject extracted rows with source-document preview.
- **Unmatched queue** (`/admin/unmatched`) — match unknown service names to the reference catalogue or create a new reference term.

> The frontend expects the API at `http://localhost:8000` (`web/.env.local` → `NEXT_PUBLIC_API_BASE`). CORS is enabled for `localhost:3000`.

### Legacy Streamlit UI

```bash
streamlit run app.py
```

Upload a `.zip` or files in the sidebar and press **Обработать загруженное**, or press **Обработать data/samples/** to process the bundled sample archive. Then search, filter, compare clinics, view price history, and export.

### Headless processing

```bash
python run_pipeline.py                 # process data/samples/
python run_pipeline.py path/to/archive.zip --reset
```

### API surface

FastAPI exposes OpenAPI docs at **http://localhost:8000/docs** and Scalar docs at **http://localhost:8000/reference**.

Main endpoints:

| Area | Endpoints |
|---|---|
| Services | `GET /services`, `GET /services/{ref_service_id}/partners`, `GET /services/{ref_service_id}/history` |
| Partners | `GET /partners`, `GET /partners/{partner_id}/services`, `GET /partners/geo`, `POST /partners/geocode` |
| Search and filters | `GET /search`, `GET /filters`, `GET /stats` |
| Upload and documents | `POST /ingest`, `GET /ingest/status/{job_id}`, `GET /documents`, `GET /documents/page`, `GET /documents/file` |
| Matching and verification | `GET /unmatched`, `POST /match`, `GET /verification`, `POST /verify` |
| Reference catalogue | `GET /reference/search`, `POST /reference`, `POST /reference/upload` |
| Analytics | `POST /basket/optimize`, `GET /report/quality` |

---

## 📂 Project structure

```
MedRate/
├── api.py                  # FastAPI REST API (OpenAPI docs, CORS, ingest, verification)
├── web/                    # Next.js product UI (public search + operator panel)
│   ├── app/                # routes: /, /service/[id], /clinic/[id], /partners, /admin/*
│   │                        # also /map and /basket
│   ├── components/         # PriceCell (рез/нерез), VerifiedBadge, FlagTag, HistoryChart…
│   └── lib/api.ts          # typed client for the FastAPI backend
├── app.py                  # legacy Streamlit UI
├── run_pipeline.py         # headless pipeline runner
├── config.py               # env, models, paths, categories, flags
├── db.py                   # SQLite schema, upserts, cache, logging
├── queries.py              # read queries for the UI
├── pipeline/
│   ├── models.py           # RawDoc and clinic metadata
│   ├── ingest.py           # unzip, walk folder, dispatch by file type
│   ├── extract_excel.py    # xlsx/xls/csv → table text + header detection
│   ├── extract_pdf.py      # text layer vs scan detection
│   ├── extract_docx.py     # docx paragraphs & tables → text
│   ├── extract_image.py    # images → base64
│   ├── llm.py              # Gemini calls, caching, retries, JSON parsing
│   ├── normalize.py        # prices, currency, categories, canonicalization
│   ├── dedup.py            # dedup keys & active-version selection
│   ├── validate.py         # data quality checks and verification flags
│   └── process.py          # end-to-end orchestration
├── prompts/
│   ├── extraction.txt
│   └── normalization.txt
├── data/
│   ├── samples/            # sample price lists (8 clinics, all formats)
│   └── reference/services.xlsx
├── requirements.txt
└── .env.example
```

---

## ⚙️ Configuration

`.env` keys (see `.env.example`):

| Key | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | — | required |
| `MEDRATE_EXTRACT_MODEL` | `gemini-2.5-flash` | text extraction |
| `MEDRATE_VISION_MODEL` | `gemini-2.5-flash` | scanned pages & images |
| `MEDRATE_NORMALIZE_MODEL` | `gemini-2.5-flash` | canonicalization tie-break |
| `MEDRATE_LLM_TIEBREAK` | `1` | enable the model tie-break (`0` to use exact+fuzzy only) |
| `USD_KZT_RATE` | `470` | USD → KZT conversion |
| `RUB_KZT_RATE` | `5.5` | RUB → KZT conversion |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000` | frontend API base URL, set in `web/.env.local` if needed |

---

## ⚠️ Notes & limitations

- MVP scope: it consumes uploaded/public clinic price-list files and does not collect patient data.
- Geocoding is optional and uses OpenStreetMap Nominatim through `POST /partners/geocode`; respect its usage policy and avoid bulk abuse.
- Extraction is conservative by design: unreadable prices or names become `null` with a flag rather than a guess.
- Model responses are cached in SQLite, so re-processing the same archive is fast and cheap, and re-runs are idempotent (no duplicate rows).
- Canonical-name coverage grows as more documents are processed.

---

## 📄 License

Released under the [MIT License](LICENSE).
