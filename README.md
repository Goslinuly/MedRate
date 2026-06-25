# MedRate

**MedRate** is a platform that automatically processes price lists from partner clinics — regardless of format — and turns them into a single clean, searchable database of services and prices.

Clinics send their price lists in whatever format they have: an Excel sheet, a text PDF, a scanned document, a photo taken on a phone, a Word file. Column layouts differ, headers sit on random rows, languages mix (Russian and Kazakh), and some files are just images with no machine-readable text. Unifying all of that by hand takes hours per clinic and breaks the moment a price changes.

MedRate does it for you: **upload an archive → get a clean, unified, comparable table.**

---

## ✨ Features

- 📥 **Any format in** — `.xlsx`, `.xls`, `.csv`, `.pdf` (text & scanned), `.docx`, `.png`, `.jpg`, `.jpeg`
- 🧠 **LLM-powered extraction** — Google Gemini models read each document the way a human would: understanding table structure, abbreviations, and messy layouts
- 👁️ **Vision for scans & photos** — low-quality scans and phone photos are read via vision, not brittle OCR rules
- 🌐 **Bilingual** — handles mixed Russian / Kazakh text and preserves both
- 🔗 **Service normalization** — the same service named differently across clinics maps to one canonical name
- 💰 **Smart prices** — ranges and "from X" are split into `price_min` / `price_max`; numbers are cleaned, never invented
- 🚩 **Trust signals** — every row gets a `confidence` score and `flags`; unreadable values become `null`, never a guess
- 🔍 **Search & filter** — by service, category, clinic, or "show only problematic rows"
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
   Excel/CSV → table text                    │
   Text PDF  → page text                     ▼
   Scan PDF  → page images           ┌──────────────┐
   DOCX      → text                  │  Gemini LLM  │  extraction (text + vision)
   Images    → base64                └──────────────┘
                                            │  strict JSON, temperature 0
                                            ▼
                                   ┌──────────────────┐
                                   │   Normalize      │  prices, currency, categories
                                   │   Canonicalize   │  unify service names
                                   │   Deduplicate    │  merge & flag conflicts
                                   └──────────────────┘
                                            │
                                            ▼
                                  SQLite  →  Streamlit UI  →  Excel export
```

The core philosophy: **let the model do the hard part** — understanding a messy document and pulling out structured data — and build thin, reliable orchestration around it (a fixed JSON schema, vision for scans, name canonicalization, and honest `confidence` / `flags`). No per-format parsers, no per-clinic rules.

---

## 📦 Data schema

Each price line becomes one structured record:

| Field | Description |
|---|---|
| `clinic_name`, `clinic_id` | Clinic name and slug |
| `service_name_raw` | Exactly as written in the document |
| `service_name_normalized` | Canonical Russian name |
| `service_name_kz` | Kazakh name, if present |
| `category` | One of the fixed categories below |
| `price`, `price_min`, `price_max` | Number(s) in KZT |
| `currency`, `unit` | e.g. `KZT`, `per visit` |
| `source_file`, `source_page` | Provenance |
| `confidence` | 0.0–1.0 extraction certainty |
| `flags`, `notes` | Quality signals & comments |

**Categories:** consultation, lab tests, ultrasound, CT/MRI, x-ray/fluorography, dentistry, physiotherapy, surgery, procedures, vaccination, inpatient, other.

**Flags:** `low_quality_scan`, `ambiguous_price`, `name_uncertain`, `price_is_range`, `currency_assumed`, `multi_column_layout`, `non_price_row`.

---

## 🛠️ Tech stack

- **Python 3.9+**
- **Google Gemini models** via the `google-genai` SDK — text & vision extraction (free tier available)
- **pandas** + **openpyxl** — Excel / CSV
- **pdfplumber** — PDF text layer
- **pdf2image** (+ poppler) — render scanned pages
- **python-docx** — Word
- **Pillow** — image handling
- **SQLite** — storage
- **Streamlit** — web UI

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

# 4. API key — get a free one at https://aistudio.google.com
cp .env.example .env        # add your GEMINI_API_KEY

# 5. Run
streamlit run app.py
```

Then open the app, upload a `.zip` or folder of price lists, press **Process**, and explore the unified table.

---

## 📂 Project structure

```
MedRate/
├── app.py                  # Streamlit UI
├── pipeline/
│   ├── ingest.py           # unzip, walk folder, dispatch by file type
│   ├── extract_excel.py    # xlsx/csv/xls → table text
│   ├── extract_pdf.py      # text layer vs scan detection
│   ├── extract_docx.py     # docx → text
│   ├── extract_image.py    # images → base64
│   ├── llm.py              # Gemini calls, retries, robust JSON parsing
│   ├── normalize.py        # prices, currency, categories
│   └── dedup.py            # dedup & conflict handling
├── prompts/
│   ├── extraction.txt
│   └── normalization.txt
├── db.py                   # SQLite schema & queries
├── data/samples/           # sample price lists (all formats)
├── requirements.txt
└── .env.example
```

---

## ⚠️ Known limitations

- Built as a hackathon MVP — tuned for demo-scale archives (5–10 files).
- Extraction quality on very poor scans is intentionally conservative: unreadable values are returned as `null` with a flag rather than guessed.
- Category and canonical-name coverage grows as more documents are processed.

---

## 📄 License

Released under the [MIT License](LICENSE).
