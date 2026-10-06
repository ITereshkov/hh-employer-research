"""Streamlit research dashboard for HH employer data with enrichment."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from hh_research.config import ResearchConfig
from hh_research.storage import Storage

st.set_page_config(page_title="HH Research Dashboard", layout="wide")


@st.cache_resource
def _get_storage(db_path: str) -> Storage:
    return Storage(db_path)


def _load_snapshot_data(storage: Storage, snapshot_id: int | None):
    sid = snapshot_id or storage.get_latest_snapshot_id()
    if not sid:
        return None, None, None, None
    return sid, storage.get_all_employers(sid), storage.get_relevant_vacancies(sid), storage.get_snapshot_info(sid)


def employers_page(storage: Storage):
    st.header("Работодатели")

    snapshot_id = storage.get_latest_snapshot_id()
    if not snapshot_id:
        st.info("Нет данных. Запустите `python -m hh_research collect`.")
        return

    all_emps = storage.get_all_employers(snapshot_id)
    if not all_emps:
        st.info("Нет работодателей в последнем снэпшоте.")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        type_filter = st.multiselect(
            "Тип",
            options=sorted({e.get("classification", "UNKNOWN") for e in all_emps}),
        )
    with col2:
        min_vacancies = st.number_input("Мин. релевантных вакансий", 0, 100, 0)
    with col3:
        min_score = st.slider("Мин. Signal Score", 0.0, 10.0, 0.0, 0.5)
    with col4:
        enrichment_filter = st.selectbox(
            "Обогащение", ["все", "done", "pending", "failed"],
        )

    filtered = all_emps
    if type_filter:
        filtered = [e for e in filtered if e.get("classification") in type_filter]
    if min_vacancies > 0:
        filtered = [e for e in filtered if e.get("relevant_open_vacancies", 0) >= min_vacancies]

    emp_by_id = {e["id"]: e for e in all_emps}
    vacs = storage.get_relevant_vacancies(snapshot_id)
    vac_by_emp: dict[int, list] = {}
    for v in vacs:
        vac_by_emp.setdefault(v["employer_id"], []).append(v)

    rows = []
    for e in filtered:
        score = 0.0
        if e.get("relevant_open_vacancies", 0) > 1:
            score += 3.0
        if e.get("enrichment_status") == "done":
            escore = e.get("signal_score", 0) or 0
            score += escore * 5
        if score < min_score:
            continue

        rows.append({
            "ID": e["id"],
            "Название": e["name"],
            "Тип": e.get("classification", "UNKNOWN"),
            "Уверенность": e.get("classification_confidence", 0),
            "Регион": e.get("area_name", ""),
            "Вакансий (всего)": e.get("total_open_vacancies", 0),
            "Релевантных": e.get("relevant_open_vacancies", 0),
            "Сайт": e.get("official_website") or "",
            "Телефон": e.get("official_phone") or "",
            "АХО телефон": e.get("facility_contact_phone") or "",
            "Обогащение": e.get("enrichment_status") or "pending",
        })

    if not rows:
        st.info("Нет работодателей по выбранным фильтрам.")
        return

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, height=500)
    st.metric("Найдено", len(rows))


def employer_detail_page(storage: Storage):
    st.header("Детали работодателя")

    snapshot_id = storage.get_latest_snapshot_id()
    if not snapshot_id:
        st.info("Нет данных.")
        return

    all_emps = storage.get_all_employers(snapshot_id)
    if not all_emps:
        st.info("Нет работодателей.")
        return

    names = {f"{e['id']} — {e['name']}": e["id"] for e in all_emps}
    selected = st.selectbox("Выберите работодателя", list(names.keys()))
    if not selected:
        return

    eid = names[selected]
    emp = next((e for e in all_emps if e["id"] == eid), None)
    if not emp:
        st.error("Не найдено.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(emp["name"])
        st.markdown(f"**ID:** {emp['id']}")
        st.markdown(f"**Тип:** {emp.get('classification', 'UNKNOWN')} (уверенность: {emp.get('classification_confidence', 0):.2f})")
        st.markdown(f"**Причина:** {emp.get('classification_reason', '')}")
        st.markdown(f"**Регион:** {emp.get('area_name', '—')}")
        st.markdown(f"**Индустрия:** {emp.get('industry', '—')}")
        st.markdown(f"**Вакансий всего:** {emp.get('total_open_vacancies', 0)}")
        st.markdown(f"**Релевантных:** {emp.get('relevant_open_vacancies', 0)}")
        hh_url = emp.get("url") or f"https://hh.ru/employer/{eid}"
        st.markdown(f"[HH.ru]({hh_url})")

    with col2:
        st.subheader("Контакты")
        st.markdown(f"**Сайт:** {emp.get('official_website') or '—'}")
        st.markdown(f"**Телефон:** {emp.get('official_phone') or '—'}")
        st.markdown(f"**Email:** {emp.get('official_email') or '—'}")
        st.markdown(f"**Адрес:** {emp.get('official_address') or '—'}")
        st.markdown(f"**Статус обогащения:** {emp.get('enrichment_status') or 'pending'}")
        if emp.get("facility_contact_phone"):
            st.markdown(f"**АХО телефон:** {emp['facility_contact_phone']}")
        if emp.get("facility_contact_email"):
            st.markdown(f"**АХО email:** {emp['facility_contact_email']}")

    contacts = storage.get_contacts(eid)
    if contacts:
        st.subheader("Все контакты")
        cdf = pd.DataFrame(contacts)
        display_cols = {
            "contact_type": "Тип",
            "value": "Значение",
            "source_type": "Источник",
            "confidence": "Уверенность",
            "is_primary": "Основной",
            "is_facility": "АХО",
            "retrieved_at": "Получено",
        }
        avail = {k: v for k, v in display_cols.items() if k in cdf.columns}
        st.dataframe(cdf[list(avail.keys())].rename(columns=avail), use_container_width=True)

    vacs = storage.get_relevant_vacancies(snapshot_id)
    emp_vacs = [v for v in vacs if v["employer_id"] == eid]
    if emp_vacs:
        st.subheader("Релевантные вакансии")
        vdf = pd.DataFrame(emp_vacs)
        vcols = {
            "name": "Название",
            "published_at": "Опубликовано",
            "salary_from": "ЗП от",
            "salary_to": "ЗП до",
            "relevance_score": "Score",
            "url": "URL",
        }
        avail = {k: v for k, v in vcols.items() if k in vdf.columns}
        st.dataframe(vdf[list(avail.keys())].rename(columns=avail), use_container_width=True)


def analytics_page(storage: Storage):
    st.header("Аналитика")

    stats = storage.get_enrichment_stats()
    if stats["employers_total"] == 0:
        st.info("Нет данных для аналитики.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Работодателей", stats["employers_total"])
    col2.metric("Обогащено", stats["enriched"])
    col3.metric("С сайтом", stats["with_website"])
    col4.metric("С контактом АХО", stats["with_facility_contact"])

    st.subheader("Покрытие контактов")
    total = stats["employers_total"]
    coverage = pd.DataFrame({
        "Метрика": ["Сайт", "Телефон", "Контакт АХО", "Контактов (всего)"],
        "Значение": [
            f"{stats['with_website']}/{total} ({stats['with_website']/total*100:.1f}%)",
            f"{stats['with_phone']}/{total} ({stats['with_phone']/total*100:.1f}%)",
            f"{stats['with_facility_contact']}/{total} ({stats['with_facility_contact']/total*100:.1f}%)",
            str(stats["contacts_total"]),
        ],
    })
    st.dataframe(coverage, use_container_width=True)

    snapshot_id = storage.get_latest_snapshot_id()
    if snapshot_id:
        all_emps = storage.get_all_employers(snapshot_id)

        st.subheader("Распределение по типу")
        by_type: dict[str, int] = {}
        for e in all_emps:
            t = e.get("classification", "UNKNOWN")
            by_type[t] = by_type.get(t, 0) + 1
        type_df = pd.DataFrame([{"Тип": k, "Количество": v} for k, v in sorted(by_type.items(), key=lambda x: -x[1])])
        st.dataframe(type_df, use_container_width=True)

        st.subheader("Распределение по региону")
        by_area: dict[str, int] = {}
        for e in all_emps:
            a = e.get("area_name") or "Unknown"
            by_area[a] = by_area.get(a, 0) + 1
        area_df = pd.DataFrame([{"Регион": k, "Количество": v} for k, v in sorted(by_area.items(), key=lambda x: -x[1])[:15]])
        st.dataframe(area_df, use_container_width=True)

        with_relevant = [e for e in all_emps if e.get("relevant_open_vacancies", 0) > 0]
        if with_relevant:
            st.subheader("Топ работодателей по релевантным вакансиям")
            top = sorted(with_relevant, key=lambda x: -x.get("relevant_open_vacancies", 0))[:10]
            top_df = pd.DataFrame([
                {"ID": e["id"], "Название": e["name"], "Тип": e.get("classification"),
                 "Релевантных": e.get("relevant_open_vacancies", 0)}
                for e in top
            ])
            st.dataframe(top_df, use_container_width=True)


def main():
    config = ResearchConfig.load()
    storage = _get_storage(config.storage.db_path)

    st.sidebar.title("HH Research")
    page = st.sidebar.radio("Навигация", ["Работодатели", "Детали", "Аналитика"])

    if page == "Работодатели":
        employers_page(storage)
    elif page == "Детали":
        employer_detail_page(storage)
    elif page == "Аналитика":
        analytics_page(storage)


if __name__ == "__main__":
    main()
