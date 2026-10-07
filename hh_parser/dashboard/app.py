import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from hh_parser.config import AppConfig
from hh_parser.db.connection import DatabaseConnection
from hh_parser.db.schema import run_migrations
from hh_parser.db.repositories import (
    EmployerRepository,
    VacancyRepository,
    EmployerFilters,
)

st.set_page_config(page_title="HH Research Dashboard", layout="wide", page_icon="🔍")


@st.cache_resource
def get_components():
    config = AppConfig.load()
    db = DatabaseConnection(config.database.path)
    conn = db.connect()
    run_migrations(conn)
    return conn, config


def employers_page(employer_repo: EmployerRepository):
    st.header("Работодатели")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        min_score = st.slider("Мин. Signal Score", 0.0, 1.0, 0.0, 0.05)
    with col2:
        min_vacancies = st.number_input("Мин. вакансий", 0, 100, 0)
    with col3:
        enrichment_status = st.selectbox(
            "Статус обогащения",
            ["все", "pending", "done", "failed"],
        )
    with col4:
        has_phone = st.checkbox("С телефоном", False)

    filters = EmployerFilters(
        min_signal_score=min_score if min_score > 0 else None,
        min_vacancy_count=min_vacancies if min_vacancies > 0 else None,
        enrichment_status=enrichment_status if enrichment_status != "все" else None,
        has_phone=has_phone or None,
    )

    employers = employer_repo.get_all(filters)

    if not employers:
        st.info("Нет работодателей. Запустите `hh-parser search` для начала.")
        return

    df = pd.DataFrame(employers)
    display_cols = {
        "id": "ID",
        "name": "Название",
        "area_name": "Регион",
        "industry_name": "Индустрия",
        "vacancy_count": "Вакансий",
        "signal_score": "Score",
        "official_website": "Сайт",
        "official_phone": "Телефон",
        "enrichment_status": "Статус",
    }

    available_cols = {k: v for k, v in display_cols.items() if k in df.columns}
    st.dataframe(
        df[list(available_cols.keys())].rename(columns=available_cols),
        use_container_width=True,
        height=600,
    )

    st.metric("Всего найдено", len(employers))


def employer_detail_page(employer_repo: EmployerRepository, vacancy_repo: VacancyRepository):
    st.header("Детали работодателя")

    all_employers = employer_repo.get_all()
    if not all_employers:
        st.info("Нет данных.")
        return

    names = {f"{e['id']} — {e['name']}": e["id"] for e in all_employers}
    selected = st.selectbox("Выберите работодателя", list(names.keys()))
    if not selected:
        return

    eid = names[selected]
    employer = employer_repo.get_by_id(eid)
    if not employer:
        st.error("Не найдено.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(employer["name"])
        st.markdown(f"**ID:** {employer['id']}")
        st.markdown(f"**Регион:** {employer.get('area_name', '—')}")
        st.markdown(f"**Индустрия:** {employer.get('industry_name', '—')}")
        st.markdown(f"**Вакансий:** {employer.get('vacancy_count', 0)}")
        st.markdown(f"**Signal Score:** {employer.get('signal_score', 0):.2f}")
        hh_url = employer.get("alternate_url") or f"https://hh.ru/employer/{eid}"
        st.markdown(f"[HH.ru]({hh_url})")

    with col2:
        st.subheader("Контакты")
        st.markdown(f"**Сайт:** {employer.get('official_website') or '—'}")
        st.markdown(f"**Телефон:** {employer.get('official_phone') or '—'}")
        st.markdown(f"**Email:** {employer.get('official_email') or '—'}")
        st.markdown(f"**Адрес:** {employer.get('official_address') or '—'}")
        st.markdown(f"**Статус:** {employer.get('enrichment_status', '—')}")
        if employer.get("facility_contact_phone"):
            st.markdown(f"**АХО телефон:** {employer['facility_contact_phone']}")
            st.markdown(f"**АХО роль:** {employer.get('facility_contact_role') or '—'}")

    vacancies = vacancy_repo.get_by_employer(eid)
    if vacancies:
        st.subheader("Релевантные вакансии")
        vac_df = pd.DataFrame(vacancies)
        vac_display = {
            "name": "Название",
            "area_name": "Регион",
            "category": "Категория",
            "published_at": "Опубликовано",
            "alternate_url": "URL",
        }
        available = {k: v for k, v in vac_display.items() if k in vac_df.columns}
        st.dataframe(
            vac_df[list(available.keys())].rename(columns=available),
            use_container_width=True,
        )


def analytics_page(employer_repo: EmployerRepository, vacancy_repo: VacancyRepository):
    st.header("Аналитика")

    employers = employer_repo.get_all()
    total = len(employers)

    if total == 0:
        st.info("Нет данных для аналитики.")
        return

    col1, col2, col3, col4 = st.columns(4)
    enriched = sum(1 for e in employers if e.get("enrichment_status") == "done")
    with_site = sum(1 for e in employers if e.get("official_website"))
    with_phone = sum(1 for e in employers if e.get("official_phone"))
    with_facility = sum(1 for e in employers if e.get("facility_contact_phone"))

    col1.metric("Работодателей", total)
    col2.metric("Обогащено", enriched)
    col3.metric("С сайтом", with_site)
    col4.metric("С контактом АХО", with_facility)

    st.subheader("Покрытие контактов")
    coverage_data = {
        "Метрика": [
            "Сайт",
            "Телефон",
            "Email",
            "Адрес",
            "Контакт АХО",
        ],
        "Покрытие (%)": [
            round(with_site / total * 100, 1),
            round(with_phone / total * 100, 1),
            round(sum(1 for e in employers if e.get("official_email")) / total * 100, 1),
            round(sum(1 for e in employers if e.get("official_address")) / total * 100, 1),
            round(with_facility / total * 100, 1),
        ],
    }
    st.dataframe(pd.DataFrame(coverage_data), use_container_width=True)

    st.subheader("Распределение по вакансиям")
    vac_counts = {}
    for e in employers:
        c = e.get("vacancy_count", 0)
        bucket = "1" if c == 1 else ("2" if c == 2 else ("3-5" if c <= 5 else "6+"))
        vac_counts[bucket] = vac_counts.get(bucket, 0) + 1
    vac_df = pd.DataFrame(
        [{"Вакансий": k, "Работодателей": v} for k, v in sorted(vac_counts.items())]
    )
    st.bar_chart(vac_df.set_index("Вакансий"))

    st.subheader("Категории вакансий")
    categories = vacancy_repo.count_by_category()
    if categories:
        cat_df = pd.DataFrame(
            [{"Категория": k, "Количество": v} for k, v in categories.items()]
        )
        st.dataframe(cat_df, use_container_width=True)

    st.subheader("Свежесть вакансий")
    fresh_7 = vacancy_repo.count_fresh(7)
    fresh_30 = vacancy_repo.count_fresh(30)
    total_active = vacancy_repo.count_active()
    st.dataframe(
        pd.DataFrame(
            {
                "Период": ["7 дней", "30 дней", "Всего активных"],
                "Вакансий": [fresh_7, fresh_30, total_active],
                "Доля": [
                    f"{fresh_7/total_active*100:.1f}%" if total_active else "0%",
                    f"{fresh_30/total_active*100:.1f}%" if total_active else "0%",
                    "100%",
                ],
            }
        ),
        use_container_width=True,
    )


def main():
    conn, config = get_components()
    employer_repo = EmployerRepository(conn)
    vacancy_repo = VacancyRepository(conn)

    st.sidebar.title("HH Research")
    page = st.sidebar.radio(
        "Навигация", ["Работодатели", "Детали", "Аналитика"]
    )

    if page == "Работодатели":
        employers_page(employer_repo)
    elif page == "Детали":
        employer_detail_page(employer_repo, vacancy_repo)
    elif page == "Аналитика":
        analytics_page(employer_repo, vacancy_repo)


if __name__ == "__main__":
    main()
