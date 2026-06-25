"""MedRate — Streamlit UI.

Upload a .zip / folder of clinic price lists -> Process -> explore a unified,
searchable table -> export to output.xlsx.

Run:  streamlit run app.py
"""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

import db
from pipeline import dedup, ingest
from pipeline import llm as llm_mod
from pipeline import normalize

# Load .env if present (no hard dependency on python-dotenv).
_ENV = Path(__file__).resolve().parent / ".env"
if _ENV.exists():
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

DISPLAY_COLUMNS = [
    "clinic_name", "service_name_normalized", "service_name_raw", "service_name_kz",
    "category", "price", "price_min", "price_max", "currency", "unit",
    "confidence", "flags", "notes", "source_file",
]


def run_pipeline(input_path: str) -> list[dict]:
    """ingest -> extract (LLM) -> normalize -> canonicalize -> dedup."""
    client = llm_mod.get_client()
    docs = ingest.ingest(input_path)
    if not docs:
        st.warning("No supported files found in the upload.")
        return []

    all_records: list[dict] = []
    progress = st.progress(0.0)
    status = st.empty()

    for i, doc in enumerate(docs, start=1):
        status.write(f"Extracting **{doc['source_file']}** ({doc['clinic_name']})…")
        if doc["error"]:
            st.error(f"{doc['source_file']}: {doc['error']}")
        elif not doc["chunks"]:
            st.info(f"{doc['source_file']}: nothing extractable (empty or unreadable).")
        else:
            try:
                records = llm_mod.extract_records(
                    client, doc["chunks"],
                    clinic_name=doc["clinic_name"], source_file=doc["source_file"],
                )
                all_records.extend(records)
            except Exception as exc:  # noqa: BLE001
                st.error(f"{doc['source_file']}: extraction failed — {exc}")
        progress.progress(i / len(docs))

    if not all_records:
        return []

    status.write("Normalizing prices and categories…")
    all_records = normalize.normalize_all(all_records)

    status.write("Canonicalizing service names…")
    names = [r.get("service_name_normalized") or r.get("service_name_raw") or "" for r in all_records]
    mapping = llm_mod.canonicalize_names(client, names)
    for rec in all_records:
        key = rec.get("service_name_normalized") or rec.get("service_name_raw") or ""
        if key in mapping:
            rec["service_name_normalized"] = mapping[key]

    status.write("Deduplicating and flagging conflicts…")
    all_records = dedup.deduplicate(all_records)

    progress.empty()
    status.empty()
    return all_records


def to_dataframe(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    for col in DISPLAY_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["flags"] = df["flags"].apply(lambda f: ", ".join(f) if isinstance(f, list) else (f or ""))
    return df[DISPLAY_COLUMNS]


def export_xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="prices")
    return buf.getvalue()


# ------------------------------------------------------------------ UI

st.set_page_config(page_title="MedRate", page_icon="🏥", layout="wide")
st.title("🏥 MedRate")
st.caption("Upload clinic price lists in any format → one clean, comparable table.")

if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
    st.warning("Set `GEMINI_API_KEY` (e.g. in a `.env` file) before processing. "
               "Get a free key at https://aistudio.google.com.")

uploaded = st.file_uploader(
    "Upload a .zip archive or individual price lists",
    type=[e.lstrip(".") for e in ingest.SUPPORTED_EXTENSIONS] + ["zip"],
    accept_multiple_files=True,
)

if st.button("Process", type="primary", disabled=not uploaded):
    with tempfile.TemporaryDirectory(prefix="medrate_upload_") as tmp:
        tmp_path = Path(tmp)
        saved = []
        for uf in uploaded:
            dest = tmp_path / uf.name
            dest.write_bytes(uf.getbuffer())
            saved.append(dest)

        # If exactly one zip was uploaded, ingest it directly; otherwise the folder.
        target = str(saved[0]) if len(saved) == 1 and saved[0].suffix.lower() == ".zip" else str(tmp_path)

        with st.spinner("Processing…"):
            records = run_pipeline(target)

        if records:
            conn = db.connect()
            db.init_db(conn)
            db.clear(conn)
            n = db.insert_records(conn, records)
            conn.close()
            st.success(f"Processed {n} records.")
            st.session_state["has_data"] = True

# ------------------------------------------------------------------ Explore

if st.session_state.get("has_data"):
    conn = db.connect()
    db.init_db(conn)

    st.subheader("Unified table")
    col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
    with col1:
        search = st.text_input("Search service")
    with col2:
        clinics = db.distinct_clinics(conn)
        clinic_choice = st.selectbox(
            "Clinic", options=[("", "All clinics")] + clinics,
            format_func=lambda c: c[1],
        )
    with col3:
        category = st.selectbox("Category", options=[""] + normalize.CATEGORIES,
                                format_func=lambda c: c or "All categories")
    with col4:
        problematic = st.checkbox("Only problematic rows")

    rows = db.query(
        conn,
        search=search or None,
        clinic_id=clinic_choice[0] or None if clinic_choice else None,
        category=category or None,
        problematic_only=problematic,
    )
    conn.close()

    st.write(f"**{len(rows)}** rows")
    if rows:
        df = to_dataframe(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Export to output.xlsx",
            data=export_xlsx(df),
            file_name="output.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
