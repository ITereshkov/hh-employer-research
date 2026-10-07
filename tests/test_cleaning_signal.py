"""Tests for cleaning-signal discovery, classification, aggregation, scoring, export."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hh_research.cleaning_signal.classifier import (
    EmployerCategory,
    EmployerCategoryResult,
    RoleCategory,
    classify_employer_category,
    classify_role,
    strip_html,
)
from hh_research.cleaning_signal.config import (
    CleaningProviderConfig,
    CleaningSignalConfig,
    ExclusionConfig,
    QueryTaxonomy,
    ScoringConfig,
)
from hh_research.cleaning_signal.discovery import DiscoveredVacancy
from hh_research.cleaning_signal.aggregation import (
    EmployerAggregate,
    VacancySummary,
    aggregate_employers,
    select_enrichment_cohort,
)
from hh_research.cleaning_signal.export import export_cleaning_xlsx


# ── Helpers ──────────────────────────────────────────────────────────


def _taxonomy() -> QueryTaxonomy:
    return QueryTaxonomy()


def _exclusions() -> ExclusionConfig:
    return ExclusionConfig()


def _scoring() -> ScoringConfig:
    return ScoringConfig()


def _vacancy(name: str, description: str = "", **kw) -> dict:
    v = {"id": kw.get("id", "1"), "name": name, "description": description}
    v.update(kw)
    return v


def _discovered(
    vacancy_id: str,
    name: str,
    employer_id: int,
    employer_name: str,
    role_cat: RoleCategory = RoleCategory.INDOOR_CLEANING,
    area_name: str = "Москва",
    published_at: str | None = None,
    is_relevant: bool = True,
) -> DiscoveredVacancy:
    from hh_research.cleaning_signal.classifier import RoleClassification
    return DiscoveredVacancy(
        vacancy_id=vacancy_id,
        name=name,
        url=f"https://hh.ru/vacancy/{vacancy_id}",
        employer_id=employer_id,
        employer_name=employer_name,
        area_id=1,
        area_name=area_name,
        published_at=published_at,
        salary_from=None,
        salary_to=None,
        currency=None,
        schedule=None,
        employment=None,
        experience=None,
        classification=RoleClassification(
            role_category=role_cat,
            relevance_score=0.8,
            matched_terms=["уборщик"],
            match_reason="test",
            is_relevant=is_relevant,
        ),
        matched_query="уборщик",
    )


# ── Role Classification ─────────────────────────────────────────────


class TestRoleClassification:
    def test_uborshik_positive(self):
        vac = _vacancy("Уборщик помещений")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert result.is_relevant
        assert result.role_category == RoleCategory.INDOOR_CLEANING

    def test_dvornik_positive(self):
        vac = _vacancy("Дворник")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert result.is_relevant
        assert result.role_category == RoleCategory.JANITORIAL

    def test_facility_maintenance(self):
        vac = _vacancy("Рабочий по комплексному обслуживанию зданий")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert result.is_relevant
        assert result.role_category == RoleCategory.FACILITY_MAINTENANCE

    def test_kitchen_worker_excluded(self):
        vac = _vacancy("Кухонный рабочий")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert not result.is_relevant
        assert result.excluded_by != ""

    def test_gruzchik_excluded(self):
        vac = _vacancy("Грузчик")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert not result.is_relevant

    def test_sanitar_excluded(self):
        vac = _vacancy("Санитар")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert not result.is_relevant

    def test_gornichnaya_excluded(self):
        vac = _vacancy("Горничная")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert not result.is_relevant

    def test_no_match_rejected(self):
        vac = _vacancy("Менеджер по продажам")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert not result.is_relevant
        assert result.role_category == RoleCategory.REJECTED

    def test_empty_vacancy_rejected(self):
        vac = _vacancy("")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert not result.is_relevant

    def test_config_exclusion_strict(self):
        vac = _vacancy(
            "Уборщик помещений",
            description="Требуется кухонный рабочий для помощи",
        )
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert not result.is_relevant
        assert result.excluded_by == "кухонный рабочий"

    def test_html_stripped(self):
        vac = _vacancy("Вакансия", description="<p>Требуется <b>уборщик</b></p>")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert result.is_relevant

    def test_mixed_category(self):
        vac = _vacancy("Уборщик и дворник")
        result = classify_role(vac, _taxonomy(), _exclusions())
        assert result.is_relevant
        assert result.role_category == RoleCategory.MIXED_CLEANING_MAINTENANCE


# ── Employer Category Classification ────────────────────────────────


class TestEmployerCategoryClassification:
    def test_school(self):
        r = classify_employer_category("МБОУ СОШ №42")
        assert r.category == EmployerCategory.EDUCATION
        assert r.confidence >= 0.8

    def test_hospital(self):
        r = classify_employer_category("ГКБ №1 им. Пирогова")
        assert r.category == EmployerCategory.HEALTHCARE

    def test_shopping_center(self):
        r = classify_employer_category("ТЦ Европейский")
        assert r.category == EmployerCategory.SHOPPING_CENTER

    def test_business_center(self):
        r = classify_employer_category("БЦ Москва-Сити")
        assert r.category == EmployerCategory.BUSINESS_CENTER

    def test_cleaning_provider_by_name(self):
        r = classify_employer_category("ООО КлинингСервис")
        assert r.category == EmployerCategory.CLEANING_COMPANY
        assert r.is_cleaning_provider

    def test_cleaning_provider_by_industry(self):
        r = classify_employer_category("ООО Ромашка", employer_industry="Клининг")
        assert r.is_cleaning_provider

    def test_facility_management(self):
        r = classify_employer_category(
            "ТехСервис", employer_industry="Управление объектами недвижимости",
        )
        assert r.category == EmployerCategory.FACILITY_MANAGEMENT

    def test_unknown(self):
        r = classify_employer_category("ООО Ромашка")
        assert r.category == EmployerCategory.OTHER

    def test_retail(self):
        r = classify_employer_category("Супермаркет Магнит")
        assert r.category == EmployerCategory.RETAIL

    def test_warehouse(self):
        r = classify_employer_category("Склад Юго-Запад")
        assert r.category == EmployerCategory.WAREHOUSE_LOGISTICS


# ── HTML Strip ───────────────────────────────────────────────────────


class TestHTMLStrip:
    def test_basic(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_empty(self):
        assert strip_html("") == ""

    def test_none(self):
        assert strip_html(None) == ""


# ── Aggregation & Scoring ───────────────────────────────────────────


class TestAggregation:
    def _fresh_date(self, days_ago: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    def test_single_employer_single_vacancy(self):
        vacs = [_discovered("v1", "Уборщик", 100, "Школа №1")]
        result = aggregate_employers(vacs, _scoring())
        assert 100 in result
        emp = result[100]
        assert emp.total_relevant == 1
        assert emp.signal_score > 0

    def test_multi_vacancy_higher_score(self):
        vacs = [
            _discovered("v1", "Уборщик", 100, "Школа №1"),
            _discovered("v2", "Уборщица", 100, "Школа №1"),
            _discovered("v3", "Дворник", 100, "Школа №1"),
        ]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert emp.total_relevant == 3
        assert emp.signal_score > 0

    def test_multi_location_signal(self):
        vacs = [
            _discovered("v1", "Уборщик", 100, "Школа №1", area_name="Москва"),
            _discovered("v2", "Уборщик", 100, "Школа №1", area_name="Санкт-Петербург"),
        ]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert emp.multi_location_signal
        assert emp.unique_location_count == 2

    def test_fresh_vacancy_7d(self):
        vacs = [
            _discovered(
                "v1", "Уборщик", 100, "Школа №1",
                published_at=self._fresh_date(2),
            ),
        ]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert emp.fresh_7d_count == 1
        assert emp.fresh_30d_count == 1

    def test_old_vacancy_not_fresh(self):
        vacs = [
            _discovered(
                "v1", "Уборщик", 100, "Школа №1",
                published_at=self._fresh_date(60),
            ),
        ]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert emp.fresh_7d_count == 0
        assert emp.fresh_30d_count == 0

    def test_signal_level_high(self):
        vacs = [
            _discovered(f"v{i}", f"Уборщик {i}", 100, "Школа №1",
                        area_name=f"Город {i}")
            for i in range(10)
        ]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert emp.signal_level == "HIGH"

    def test_signal_level_medium(self):
        vacs = [_discovered("v1", "Уборщик", 100, "Школа №1")]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert emp.signal_level == "MEDIUM"

    def test_cleaning_provider_detected(self):
        vacs = [
            _discovered("v1", "Уборщик", 200, "ООО КлинингПро"),
        ]
        result = aggregate_employers(vacs, _scoring(), CleaningProviderConfig())
        emp = result[200]
        assert emp.is_cleaning_provider
        assert emp.employer_category == EmployerCategory.CLEANING_COMPANY

    def test_rejected_vacancies_excluded(self):
        vacs = [
            _discovered("v1", "Уборщик", 100, "Школа №1", is_relevant=True),
            _discovered("v2", "Грузчик", 100, "Школа №1", is_relevant=False),
        ]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert emp.total_relevant == 1

    def test_multiple_employers(self):
        vacs = [
            _discovered("v1", "Уборщик", 100, "Школа №1"),
            _discovered("v2", "Уборщик", 200, "Больница №1"),
            _discovered("v3", "Дворник", 100, "Школа №1"),
        ]
        result = aggregate_employers(vacs, _scoring())
        assert len(result) == 2
        assert 100 in result
        assert 200 in result


# ── Cohort Selection ─────────────────────────────────────────────────


class TestCohortSelection:
    def _make_employers(self, scores: dict[int, float]) -> dict[int, EmployerAggregate]:
        result = {}
        for eid, score in scores.items():
            emp = EmployerAggregate(
                employer_id=eid,
                employer_name=f"Emp {eid}",
                employer_hh_url=None,
                signal_score=score,
            )
            if score >= 8.0:
                emp.signal_level = "HIGH"
            elif score >= 4.0:
                emp.signal_level = "MEDIUM"
            else:
                emp.signal_level = "LOW"
            result[eid] = emp
        return result

    def test_select_high_only(self):
        emps = self._make_employers({1: 10.0, 2: 5.0, 3: 2.0})
        cohort = select_enrichment_cohort(emps, ["HIGH"], max_employers=50)
        assert cohort == [1]

    def test_select_high_and_medium(self):
        emps = self._make_employers({1: 10.0, 2: 5.0, 3: 2.0})
        cohort = select_enrichment_cohort(emps, ["HIGH", "MEDIUM"], max_employers=50)
        assert set(cohort) == {1, 2}

    def test_max_employers_limit(self):
        emps = self._make_employers({i: 10.0 for i in range(100)})
        cohort = select_enrichment_cohort(emps, ["HIGH"], max_employers=10)
        assert len(cohort) == 10

    def test_min_score_filter(self):
        emps = self._make_employers({1: 10.0, 2: 3.0})
        emps[1].signal_level = "HIGH"
        emps[2].signal_level = "HIGH"
        cohort = select_enrichment_cohort(emps, ["HIGH"], max_employers=50, min_score=5.0)
        assert cohort == [1]

    def test_include_top_medium(self):
        emps = self._make_employers({1: 10.0, 2: 6.0, 3: 5.0})
        cohort = select_enrichment_cohort(
            emps, ["HIGH"], max_employers=3, include_top_medium=2,
        )
        assert 1 in cohort
        assert 2 in cohort


# ── Export ────────────────────────────────────────────────────────────


class TestCleaningExport:
    def _make_employers(self) -> list[EmployerAggregate]:
        vac = VacancySummary(
            vacancy_id="v1",
            name="Уборщик",
            url="https://hh.ru/vacancy/1",
            published_at="2026-01-01T00:00:00Z",
            role_category=RoleCategory.INDOOR_CLEANING,
            matched_terms=["уборщик"],
            relevance_score=0.8,
            area_id=1,
            area_name="Москва",
            salary_from=30000,
            salary_to=None,
            currency="RUR",
        )
        emp = EmployerAggregate(
            employer_id=1,
            employer_name="Школа №1",
            employer_hh_url="https://hh.ru/employer/1",
            employer_category=EmployerCategory.EDUCATION,
            employer_category_reason="keyword школа",
            employer_category_confidence=0.85,
            regions=["Москва"],
            relevant_vacancies=[vac],
            signal_score=10.0,
            signal_level="HIGH",
            fresh_7d_count=1,
            unique_roles={"уборщик"},
            unique_locations={"Москва"},
        )
        return [emp]

    def test_xlsx_export_creates_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            employers = self._make_employers()
            path = export_cleaning_xlsx(
                employers=employers,
                total_raw=10,
                total_relevant=5,
                total_rejected=2,
                export_dir=tmp,
            )
            assert Path(path).exists()
            assert path.endswith(".xlsx")

    def test_xlsx_export_with_enrichment(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            employers = self._make_employers()
            enriched = {
                1: {
                    "official_website": "https://school1.ru",
                    "official_phone": "+74951234567",
                    "enrichment_status": "done",
                },
            }
            path = export_cleaning_xlsx(
                employers=employers,
                total_raw=10,
                total_relevant=5,
                total_rejected=2,
                export_dir=tmp,
                enriched=enriched,
            )
            assert Path(path).exists()

    def test_xlsx_export_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = export_cleaning_xlsx(
                employers=[],
                total_raw=0,
                total_relevant=0,
                total_rejected=0,
                export_dir=tmp,
            )
            assert Path(path).exists()


# ── Config ────────────────────────────────────────────────────────────


class TestCleaningConfig:
    def test_default_config(self):
        cfg = CleaningSignalConfig.from_dict({})
        assert cfg.scoring.threshold_high == 8.0
        assert cfg.scoring.threshold_medium == 4.0
        assert len(cfg.query_taxonomy.all_terms) > 0

    def test_load_from_yaml(self):
        import tempfile
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            cfg_data = {
                "discovery": {"areas": [1, 2]},
                "scoring": {"threshold_high": 10.0},
            }
            p = Path(tmp) / "test.yaml"
            p.write_text(yaml.dump(cfg_data), encoding="utf-8")
            cfg = CleaningSignalConfig.load(p)
            assert cfg.discovery.areas == [1, 2]
            assert cfg.scoring.threshold_high == 10.0

    def test_taxonomy_all_terms(self):
        tax = QueryTaxonomy()
        assert "уборщик" in tax.all_terms
        assert "дворник" in tax.all_terms
        assert "рабочий по комплексному обслуживанию" in tax.all_terms

    def test_exclusion_config(self):
        exc = ExclusionConfig()
        assert "кухонный рабочий" in exc.terms
        assert "грузчик" in exc.terms


# ── Signal Score Components ──────────────────────────────────────────


class TestSignalScoreComponents:
    def test_score_components_transparent(self):
        vacs = [
            _discovered("v1", "Уборщик", 100, "Школа №1"),
            _discovered("v2", "Дворник", 100, "Школа №1"),
        ]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert "vacancy_count" in emp.signal_components
        assert "fresh_7d" in emp.signal_components
        assert "unique_roles" in emp.signal_components
        assert sum(emp.signal_components.values()) == pytest.approx(emp.signal_score)

    def test_multi_location_bonus(self):
        vacs = [
            _discovered("v1", "Уборщик", 100, "Школа №1", area_name="Москва"),
            _discovered("v2", "Уборщик", 100, "Школа №1", area_name="Казань"),
        ]
        result = aggregate_employers(vacs, _scoring())
        emp = result[100]
        assert emp.signal_components.get("multi_location", 0) > 0
