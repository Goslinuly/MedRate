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
- 🔍 **Search & filter** — by service, city, category, clinic, price range, "only problematic", "only active"
- 📊 **Compare & history** — clinic-by-clinic price comparison and multi-year price history
- 📤 **One-click export** — to `output.xlsx`

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
                                  SQLite  →  Streamlit UI  →  Excel export
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
| `price`, `price_min`, `price_max` | Number(s) in KZT |
| `currency`, `unit`, `duration_days` | e.g. `KZT`, `прием`, analysis turnaround |
| `source_file`, `source_page`, `source_year` | Provenance |
| `parsed_at`, `is_active` | Import time and freshness flag |
| `confidence`, `flags`, `notes` | Quality signals & comments |

**Categories:** `consultation`, `lab_tests`, `ultrasound`, `ct_mri`, `xray`, `dentistry`, `physiotherapy`, `surgery`, `procedures`, `vaccination`, `inpatient`, `other`.

**Flags:** `low_quality_scan`, `ambiguous_price`, `name_uncertain`, `price_is_range`, `currency_assumed`, `multi_column_layout`, `non_price_row`, `unmatched_service`, `kzt_converted_from_usd`.

Unmatched services land in a separate `unmatched_queue` for manual review; raw model output is kept in `raw_extractions`; every file processed is logged to `ingest_log`.

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
- **Public** — search a service → clinics with **resident / non-resident** prices, cheapest highlighted, price history; clinic cards with full price lists.
- **Operator panel** (`/admin`) — dashboard (normalization %, flags, ingest log), **upload an archive** (drag-drop → background processing), **verification queue** (approve / correct / reject), and the **unmatched** matching queue.

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

---

## 📂 Project structure

```
MedRate/
├── api.py                  # FastAPI REST API (OpenAPI docs, CORS, ingest, verification)
├── web/                    # Next.js product UI (public search + operator panel)
│   ├── app/                # routes: /, /service/[id], /clinic/[id], /partners, /admin/*
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

---

## ⚠️ Notes & limitations

- MVP scope: it consumes the supplied archive of clinic price lists; it does not crawl clinic websites. No patient or personal data is collected.
- Extraction is conservative by design: unreadable prices or names become `null` with a flag rather than a guess.
- Model responses are cached in SQLite, so re-processing the same archive is fast and cheap, and re-runs are idempotent (no duplicate rows).
- Canonical-name coverage grows as more documents are processed.

---

## 📄 License

Released under the [MIT License](LICENSE).
