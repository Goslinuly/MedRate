import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

import db
import queries
from config import EXPORT_PATH
from pipeline.process import process_paths, process_samples

st.set_page_config(page_title="MedRate", page_icon="🩺", layout="wide")


@st.cache_resource
def get_conn():
    conn = db.connect(check_same_thread=False)
    db.init_db(conn)
    return conn


@st.cache_data
def reference_terms():
    return queries.reference_terms()


def format_price(row: pd.Series) -> str:
    if pd.notna(row.get("price")):
        return f"{int(row['price']):,}".replace(",", " ")
    low, high = row.get("price_min"), row.get("price_max")
    if pd.notna(low) and pd.notna(high):
        return f"{int(low):,}–{int(high):,}".replace(",", " ")
    if pd.notna(low):
        return f"от {int(low):,}".replace(",", " ")
    return "—"


def parse_flags(value) -> list[str]:
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def results_table(df: pd.DataFrame) -> pd.DataFrame:
    table = pd.DataFrame()
    table["Клиника"] = df["clinic_name"]
    table["Услуга"] = df["service_name_norm"].fillna(df["service_name_raw"])
    table["Цена, ₸"] = df.apply(format_price, axis=1)
    table["Ед."] = df["unit"].fillna("")
    table["Категория"] = df["category"].fillna("")
    table["Обновлено"] = pd.to_datetime(df["parsed_at"], errors="coerce").dt.strftime("%Y-%m-%d")
    table["Год"] = df["source_year"]
    table["Увер."] = df["confidence"]
    table["Флаги"] = df["flags"].apply(lambda v: ", ".join(parse_flags(v)))
    table["Источник"] = df["source_file"]
    return table


def sidebar_processing(conn):
    st.sidebar.header("Обработка данных")
    uploaded = st.sidebar.file_uploader(
        "Загрузите архив или файлы прайсов",
        type=["zip", "xlsx", "xls", "csv", "pdf", "docx", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )
    col1, col2 = st.sidebar.columns(2)
    if col1.button("Обработать загруженное", disabled=not uploaded, use_container_width=True):
        run_processing(conn, save_uploads(uploaded))
    if col2.button("Обработать data/samples/", use_container_width=True):
        run_processing(conn, None)


def save_uploads(uploaded) -> list[Path]:
    target = Path(tempfile.mkdtemp(prefix="medrate_upload_"))
    paths = []
    for file in uploaded:
        destination = target / file.name
        destination.write_bytes(file.getbuffer())
        paths.append(destination)
    return paths


def run_processing(conn, paths):
    db.clear_pipeline_tables(conn)
    progress = st.sidebar.progress(0.0)
    status = st.sidebar.empty()

    def report(name: str, index: int, total: int):
        progress.progress(index / total)
        status.write(f"{index}/{total}: {name}")

    with st.spinner("Извлечение и нормализация…"):
        stats = process_paths(paths, conn, report) if paths else process_samples(conn, report)
    progress.empty()
    status.empty()
    st.cache_data.clear()
    st.session_state["last_stats"] = stats


def show_stats(conn):
    stats = st.session_state.get("last_stats")
    if stats:
        st.sidebar.success(
            f"Файлов: {stats['files']}, услуг: {stats['services']}, "
            f"нормализовано: {stats.get('normalized', 0)}, ошибок: {stats['failed_files']}"
        )
    counts = queries.counts(conn)
    cols = st.columns(4)
    cols[0].metric("Услуги", counts["services"])
    cols[1].metric("Активные", counts["active"])
    cols[2].metric("Нормализовано", counts["normalized"])
    cols[3].metric("Клиники", counts["clinics"])


def search_tab(conn):
    terms = sorted(set(queries.autocomplete_terms(conn)) | set(reference_terms()))
    col1, col2 = st.columns([2, 1])
    typed = col1.text_input("Поиск услуги", placeholder="например, УЗИ органов брюшной полости")
    picked = col2.selectbox("Подсказки справочника", ["—", *terms[:2000]])
    query = typed.strip() or ("" if picked == "—" else picked)

    cities = queries.distinct_values(conn, "city")
    categories = queries.distinct_values(conn, "category")
    clinics = queries.clinic_options(conn)
    low, high = queries.price_bounds(conn)

    f1, f2, f3 = st.columns(3)
    city = f1.selectbox("Город", ["Все", *cities])
    category = f2.selectbox("Категория", ["Все", *categories])
    clinic_name = f3.selectbox("Клиника", ["Все", *clinics.keys()])

    f4, f5, f6 = st.columns([2, 1, 1])
    price_range = f4.slider("Цена, ₸", low, max(high, low + 1), (low, max(high, low + 1))) if high > low else None
    sort = f5.selectbox("Сортировка", list(queries.SORT_OPTIONS.keys()))
    only_active = f6.checkbox("Только актуальные", value=True)
    only_flagged = f6.checkbox("Только проблемные", value=False)

    df = queries.search_services(
        conn,
        query=query,
        city=None if city == "Все" else city,
        category=None if category == "Все" else category,
        clinic_id=None if clinic_name == "Все" else clinics[clinic_name],
        price_min=price_range[0] if price_range else None,
        price_max=price_range[1] if price_range else None,
        only_active=only_active,
        only_flagged=only_flagged,
        sort=sort,
    )
    st.caption(f"Найдено: {len(df)}")
    st.dataframe(results_table(df), use_container_width=True, hide_index=True)


def compare_tab(conn):
    terms = queries.autocomplete_terms(conn)
    if not terms:
        st.info("Сначала обработайте прайсы.")
        return
    service = st.selectbox("Услуга для сравнения", terms)
    df = queries.compare_service(conn, service)
    if df.empty:
        return
    table = pd.DataFrame()
    table["Клиника"] = df["clinic_name"]
    table["Цена, ₸"] = df.apply(format_price, axis=1)
    table["Ед."] = df["unit"].fillna("")
    table["Год"] = df["source_year"]
    table["Источник"] = df["source_file"]
    cheapest = df["price_sort"].min()
    st.metric("Минимальная цена", f"{int(cheapest):,}".replace(",", " ") if pd.notna(cheapest) else "—")
    st.dataframe(
        table.style.apply(
            lambda r: ["background-color: #1b5e20" if df.loc[r.name, "price_sort"] == cheapest else "" for _ in r],
            axis=1,
        ),
        use_container_width=True,
        hide_index=True,
    )


def clinic_tab(conn):
    clinics = queries.clinic_options(conn)
    if not clinics:
        st.info("Сначала обработайте прайсы.")
        return
    clinic_name = st.selectbox("Клиника", list(clinics.keys()))
    clinic_id = clinics[clinic_name]
    info = queries.clinic_info(conn, clinic_id)
    meta = [info.get("city"), info.get("address"), info.get("phone"), info.get("working_hours")]
    shown = " · ".join(value for value in meta if value)
    st.caption(shown or "Контактные данные не указаны в прайсе")
    df = queries.clinic_services(conn, clinic_id)
    st.caption(f"Услуг: {len(df)}")
    st.dataframe(results_table_for_clinic(df), use_container_width=True, hide_index=True)


def results_table_for_clinic(df: pd.DataFrame) -> pd.DataFrame:
    table = pd.DataFrame()
    table["Услуга"] = df["service_name_norm"].fillna(df["service_name_raw"])
    table["Цена, ₸"] = df.apply(format_price, axis=1)
    table["Ед."] = df["unit"].fillna("")
    table["Категория"] = df["category"].fillna("")
    table["Флаги"] = df["flags"].apply(lambda v: ", ".join(parse_flags(v)))
    table["Источник"] = df["source_file"]
    return table


def history_tab(conn):
    items = queries.services_with_history(conn)
    if not items:
        st.info("Нет услуг с ценами за несколько лет.")
        return
    labels = {f"{name} — {clinic}": (clinic_id, name) for clinic_id, clinic, name in items}
    choice = st.selectbox("Услуга с историей цен", list(labels.keys()))
    clinic_id, name = labels[choice]
    df = queries.price_history(conn, clinic_id, name)
    df = df.dropna(subset=["source_year"]).set_index("source_year")
    st.line_chart(df["price"])
    st.dataframe(df.reset_index(), use_container_width=True, hide_index=True)


def export_tab(conn):
    df = queries.export_dataframe(conn)
    st.caption(f"Записей в экспорте: {len(df)}")
    if st.button("Сформировать output.xlsx", disabled=df.empty):
        df.to_excel(EXPORT_PATH, index=False)
        st.session_state["export_ready"] = True
    if st.session_state.get("export_ready") and EXPORT_PATH.exists():
        st.download_button(
            "Скачать output.xlsx",
            EXPORT_PATH.read_bytes(),
            file_name="output.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def main():
    conn = get_conn()
    st.title("MedRate — сравнение цен на медицинские услуги")
    sidebar_processing(conn)
    show_stats(conn)

    log = queries.ingest_log(conn)
    if not log.empty:
        with st.sidebar.expander("Журнал обработки"):
            st.dataframe(log, use_container_width=True, hide_index=True)

    tabs = st.tabs(["Поиск", "Сравнение", "Карточка клиники", "История цен", "Экспорт"])
    with tabs[0]:
        search_tab(conn)
    with tabs[1]:
        compare_tab(conn)
    with tabs[2]:
        clinic_tab(conn)
    with tabs[3]:
        history_tab(conn)
    with tabs[4]:
        export_tab(conn)


if __name__ == "__main__":
    main()
