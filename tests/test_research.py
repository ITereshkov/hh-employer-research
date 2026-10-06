"""Tests for employer deduplication, classification, vacancy matching, storage, exports."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from hh_research.aggregation import (
    EmployerRecord,
    RelevantVacancyRecord,
    SignalMetrics,
    build_employer_record,
    compute_signal_metrics,
)
from hh_research.config import FalsePositiveConfig, ResearchConfig
from hh_research.employer_classifier import (
    ClassificationResult,
    EmployerType,
    classify_employer,
    is_target_employer,
)
from hh_research.employer_discovery import DiscoveredEmployer
from hh_research.storage import Storage
from hh_research.vacancy_relevance import evaluate_vacancy, strip_html


# ── Employer Classification ──────────────────────────────────────────


class TestEmployerClassification:
    def test_school_by_name(self):
        emp = DiscoveredEmployer(employer_id=1, name="МБОУ СОШ №42")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.SCHOOL
        assert result.confidence >= 0.8

    def test_gymnasium(self):
        emp = DiscoveredEmployer(employer_id=2, name="Гимназия №1")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.GYMNASIUM_LYCEUM

    def test_lyceum(self):
        emp = DiscoveredEmployer(employer_id=3, name="Лицей при МГУ")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.GYMNASIUM_LYCEUM

    def test_hospital_gkb(self):
        emp = DiscoveredEmployer(employer_id=4, name="ГКБ №1 им. Пирогова")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.HOSPITAL
        assert result.confidence >= 0.9

    def test_polyclinic(self):
        emp = DiscoveredEmployer(employer_id=5, name="Городская поликлиника №7")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.POLYCLINIC

    def test_maternity(self):
        emp = DiscoveredEmployer(employer_id=6, name="Роддом №2")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.MATERNITY

    def test_medical_center(self):
        emp = DiscoveredEmployer(employer_id=7, name="Диагностический центр Здоровье")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.MEDICAL_CENTER

    def test_college(self):
        emp = DiscoveredEmployer(employer_id=8, name="Педагогический колледж №3")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.COLLEGE

    def test_unknown_no_match(self):
        emp = DiscoveredEmployer(employer_id=9, name="ООО Ромашка")
        result = classify_employer(emp)
        assert result.employer_type == EmployerType.UNKNOWN
        assert result.confidence == 0.0

    def test_unknown_not_target(self):
        emp = DiscoveredEmployer(employer_id=10, name="ИП Иванов")
        result = classify_employer(emp)
        assert not is_target_employer(result)

    def test_target_school(self):
        emp = DiscoveredEmployer(employer_id=11, name="МБОУ школа №5")
        result = classify_employer(emp)
        assert is_target_employer(result)

    def test_classification_uses_description(self):
        emp = DiscoveredEmployer(
            employer_id=12, name="Организация Х",
            description="Государственное бюджетное учреждение здравоохранения",
        )
        result = classify_employer(emp)
        assert result.employer_type in (
            EmployerType.OTHER_MEDICAL, EmployerType.HOSPITAL,
            EmployerType.POLYCLINIC, EmployerType.MEDICAL_CENTER,
        )

    def test_classification_reason_stored(self):
        emp = DiscoveredEmployer(employer_id=13, name="Школа развития")
        result = classify_employer(emp)
        assert result.reason != ""


# ── Vacancy Relevance ────────────────────────────────────────────────


class TestVacancyRelevance:
    @pytest.fixture
    def fp_config(self):
        return FalsePositiveConfig(
            exclude_terms=["кухонный рабочий", "медицинская сестра", "врач", "преподаватель"],
            threshold=0.3,
        )

    @pytest.fixture
    def terms(self):
        return [
            "уборщик", "уборщица", "уборщик помещений",
            "дворник", "рабочий по комплексному обслуживанию зданий",
            "подсобный рабочий", "хозяйственный рабочий",
        ]

    def test_positive_match_uborshik(self, fp_config, terms):
        vac = {"id": "1", "name": "Уборщик помещений", "description": "Требуется уборщик"}
        m = evaluate_vacancy(vac, terms, fp_config)
        assert m.is_relevant
        assert "уборщик" in m.matched_terms

    def test_positive_match_dvornik(self, fp_config, terms):
        vac = {"id": "2", "name": "Дворник", "description": "Уборка территории"}
        m = evaluate_vacancy(vac, terms, fp_config)
        assert m.is_relevant

    def test_positive_match_complex(self, fp_config, terms):
        vac = {
            "id": "3",
            "name": "Рабочий по комплексному обслуживанию зданий",
            "description": "Обслуживание зданий",
        }
        m = evaluate_vacancy(vac, terms, fp_config)
        assert m.is_relevant
        assert m.relevance_score > 0

    def test_false_positive_kitchen(self, fp_config, terms):
        vac = {"id": "4", "name": "Кухонный рабочий", "description": "Работа на кухне"}
        m = evaluate_vacancy(vac, terms, fp_config)
        assert not m.is_relevant
        assert m.excluded_by != ""

    def test_false_positive_doctor(self, fp_config, terms):
        vac = {"id": "5", "name": "Врач-терапевт", "description": "Лечение пациентов"}
        m = evaluate_vacancy(vac, terms, fp_config)
        assert not m.is_relevant

    def test_false_positive_teacher(self, fp_config, terms):
        vac = {"id": "6", "name": "Преподаватель математики", "description": ""}
        m = evaluate_vacancy(vac, terms, fp_config)
        assert not m.is_relevant

    def test_no_match_relevant(self, fp_config, terms):
        vac = {"id": "7", "name": "Менеджер по продажам", "description": "Продажи B2B"}
        m = evaluate_vacancy(vac, terms, fp_config)
        assert not m.is_relevant
        assert m.matched_terms == []

    def test_html_stripped_in_description(self, fp_config, terms):
        vac = {
            "id": "8",
            "name": "Вакансия",
            "description": "<p>Требуется <b>уборщик</b> помещений</p>",
        }
        m = evaluate_vacancy(vac, terms, fp_config)
        assert m.is_relevant

    def test_empty_vacancy(self, fp_config, terms):
        vac = {"id": "9", "name": "", "description": ""}
        m = evaluate_vacancy(vac, terms, fp_config)
        assert not m.is_relevant


# ── HTML Strip ────────────────────────────────────────────────────────


class TestHTMLStrip:
    def test_basic(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_empty(self):
        assert strip_html("") == ""

    def test_none(self):
        assert strip_html(None) == ""


# ── Employer Deduplication ───────────────────────────────────────────


class TestEmployerDeduplication:
    def test_dedup_by_id(self):
        found = {}
        for eid, name in [(1, "Школа А"), (1, "Школа А duplicate"), (2, "Школа Б")]:
            if eid not in found:
                found[eid] = DiscoveredEmployer(employer_id=eid, name=name)
        assert len(found) == 2
        assert found[1].name == "Школа А"


# ── Signal Metrics ───────────────────────────────────────────────────


class TestSignalMetrics:
    def _make_record(self, relevant_count=0, days_old=None):
        vacs = []
        for i in range(relevant_count):
            vacs.append(RelevantVacancyRecord(
                vacancy_id=str(i), vacancy_name=f"Уборщик {i}",
                vacancy_url=None, published_at=None,
                salary_from=None, salary_to=None, currency=None,
                schedule=None, employment=None, experience=None,
                matched_terms=["уборщик"], match_reason="test", relevance_score=0.8,
            ))
        return EmployerRecord(
            snapshot_at="2026-01-01T00:00:00Z",
            employer_id=1, employer_name="Test",
            employer_type="SCHOOL", employer_type_confidence=0.9,
            classification_reason="test", employer_hh_url=None,
            employer_site_url=None, area_id=1, area_name="Москва",
            industry=None, total_open_vacancies=relevant_count + 5,
            relevant_open_vacancies=relevant_count,
            relevant_vacancies=vacs,
        )

    def test_no_signal(self):
        rec = self._make_record(0)
        m = compute_signal_metrics(rec)
        assert m.research_signal_score == 0.0
        assert not m.fresh_signal

    def test_multi_vacancy_signal(self):
        rec = self._make_record(3)
        m = compute_signal_metrics(rec)
        assert m.multi_role_signal
        assert m.research_signal_score > 0

    def test_fresh_signal(self):
        from datetime import datetime, timezone, timedelta
        vacs = [RelevantVacancyRecord(
            vacancy_id="1", vacancy_name="Уборщик",
            vacancy_url=None,
            published_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            salary_from=None, salary_to=None, currency=None,
            schedule=None, employment=None, experience=None,
            matched_terms=["уборщик"], match_reason="test", relevance_score=0.8,
        )]
        rec = EmployerRecord(
            snapshot_at="now", employer_id=1, employer_name="T",
            employer_type="SCHOOL", employer_type_confidence=0.9,
            classification_reason="t", employer_hh_url=None,
            employer_site_url=None, area_id=1, area_name="M",
            industry=None, total_open_vacancies=1, relevant_open_vacancies=1,
            relevant_vacancies=vacs,
        )
        m = compute_signal_metrics(rec)
        assert m.fresh_signal


# ── Storage ──────────────────────────────────────────────────────────


class TestStorage:
    @pytest.fixture
    def db(self, tmp_path):
        s = Storage(str(tmp_path / "test.db"))
        yield s
        s.close()

    def test_create_snapshot(self, db):
        sid = db.create_snapshot(note="test")
        assert sid is not None
        assert sid > 0

    def test_upsert_employer(self, db):
        sid = db.create_snapshot()
        db.upsert_employer({
            "id": 100, "name": "Test School",
            "classification": "SCHOOL",
            "classification_reason": "keyword",
            "classification_confidence": 0.9,
            "raw": {},
        })
        db.link_employer_snapshot(sid, 100, 10, 2)
        db.commit()
        emps = db.get_all_employers(sid)
        assert len(emps) == 1
        assert emps[0]["name"] == "Test School"

    def test_upsert_vacancy_and_relevant(self, db):
        sid = db.create_snapshot()
        db.upsert_employer({
            "id": 200, "name": "Hospital",
            "classification": "HOSPITAL",
            "classification_reason": "kw",
            "classification_confidence": 0.9,
            "raw": {},
        })
        db.upsert_vacancy({"id": "v1", "name": "Уборщик"}, 200)
        db.link_vacancy_snapshot(sid, "v1", True, 0.8, ["уборщик"], "match")
        db.update_vacancy_status(sid, "v1", 200)
        db.link_employer_snapshot(sid, 200, 5, 1)
        db.commit()
        vacs = db.get_relevant_vacancies(sid)
        assert len(vacs) == 1
        assert vacs[0]["name"] == "Уборщик"

    def test_disappeared_vacancy(self, db):
        sid1 = db.create_snapshot(note="run1")
        db.upsert_employer({"id": 300, "name": "E", "raw": {}})
        db.upsert_vacancy({"id": "v_old", "name": "Old"}, 300)
        db.update_vacancy_status(sid1, "v_old", 300)
        db.commit()

        sid2 = db.create_snapshot(note="run2")
        db.upsert_vacancy({"id": "v_new", "name": "New"}, 300)
        db.update_vacancy_status(sid2, "v_new", 300)
        db.mark_disappeared_vacancies(sid2, {"v_new"})
        db.commit()

        disappeared = db.count_disappeared_vacancies(sid2)
        assert disappeared >= 1

    def test_same_vacancy_across_runs(self, db):
        sid1 = db.create_snapshot()
        db.upsert_employer({"id": 400, "name": "E", "raw": {}})
        db.upsert_vacancy({"id": "v_same", "name": "Same"}, 400)
        db.update_vacancy_status(sid1, "v_same", 400)
        db.commit()

        sid2 = db.create_snapshot()
        db.upsert_vacancy({"id": "v_same", "name": "Same"}, 400)
        db.update_vacancy_status(sid2, "v_same", 400)
        db.commit()

        new_count = db.count_new_vacancies(sid2)
        assert new_count == 0


# ── Export ────────────────────────────────────────────────────────────


class TestExport:
    def _make_records(self):
        vacs = [RelevantVacancyRecord(
            vacancy_id="v1", vacancy_name="Уборщик",
            vacancy_url="https://hh.ru/vacancy/1",
            published_at="2026-01-01T00:00:00Z",
            salary_from=30000, salary_to=None, currency="RUR",
            schedule=None, employment=None, experience=None,
            matched_terms=["уборщик"], match_reason="match", relevance_score=0.8,
        )]
        rec = EmployerRecord(
            snapshot_at="2026-01-01", employer_id=1, employer_name="Школа №1",
            employer_type="SCHOOL", employer_type_confidence=0.9,
            classification_reason="keyword школа", employer_hh_url="https://hh.ru/employer/1",
            employer_site_url=None, area_id=1, area_name="Москва",
            industry="Education", total_open_vacancies=5, relevant_open_vacancies=1,
            relevant_vacancies=vacs,
        )
        return [rec], {1: compute_signal_metrics(rec)}

    def test_csv_export(self, tmp_path):
        from hh_research.export import export_csv
        records, metrics = self._make_records()
        emp_path, vac_path = export_csv(records, metrics, str(tmp_path))
        assert Path(emp_path).exists()
        assert Path(vac_path).exists()

    def test_json_export(self, tmp_path):
        from hh_research.export import export_json
        records, metrics = self._make_records()
        path = export_json(records, metrics, str(tmp_path))
        assert Path(path).exists()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["employer_name"] == "Школа №1"

    def test_xlsx_export(self, tmp_path):
        from hh_research.export import export_xlsx
        records, metrics = self._make_records()
        path = export_xlsx(records, metrics, str(tmp_path))
        assert Path(path).exists()
        assert path.endswith(".xlsx")


# ── Config ───────────────────────────────────────────────────────────


class TestConfig:
    def test_default_config(self):
        cfg = ResearchConfig.from_dict({})
        assert cfg.api.base_url == "https://api.hh.ru"
        assert len(cfg.all_employer_terms) > 0
        assert len(cfg.all_vacancy_terms) > 0

    def test_load_from_yaml(self, tmp_path):
        import yaml
        cfg_data = {
            "areas": [1, 2],
            "api": {"delay": 0.5},
        }
        p = tmp_path / "test.yaml"
        p.write_text(yaml.dump(cfg_data), encoding="utf-8")
        cfg = ResearchConfig.load(p)
        assert cfg.areas.ids == [1, 2]
        assert cfg.api.delay == 0.5

    def test_area_filtering(self):
        cfg = ResearchConfig.from_dict({"areas": [1, 2, 3]})
        assert cfg.areas.ids == [1, 2, 3]
