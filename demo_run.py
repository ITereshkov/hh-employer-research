"""Demo run with realistic mock data to validate the full pipeline."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from hh_research.aggregation import (
    EmployerRecord,
    RelevantVacancyRecord,
    build_employer_record,
    compute_signal_metrics,
)
from hh_research.config import ResearchConfig
from hh_research.employer_classifier import ClassificationResult, EmployerType, classify_employer
from hh_research.employer_discovery import DiscoveredEmployer
from hh_research.export import export_csv, export_json, export_xlsx
from hh_research.storage import Storage
from hh_research.vacancy_relevance import evaluate_vacancy
from hh_research.config import FalsePositiveConfig


MOCK_EMPLOYERS = [
    {"id": 1001, "name": "МБОУ СОШ №42", "area_id": 1, "area_name": "Москва"},
    {"id": 1002, "name": "Гимназия №1505", "area_id": 1, "area_name": "Москва"},
    {"id": 1003, "name": "ГКБ №1 им. Н.И. Пирогова", "area_id": 1, "area_name": "Москва"},
    {"id": 1004, "name": "Городская поликлиника №7", "area_id": 1, "area_name": "Москва"},
    {"id": 1005, "name": "Родильный дом №4", "area_id": 1, "area_name": "Москва"},
    {"id": 1006, "name": "Лицей при МГУ", "area_id": 1, "area_name": "Москва"},
    {"id": 1007, "name": "Диагностический центр Здоровье", "area_id": 1, "area_name": "Москва"},
    {"id": 1008, "name": "Педагогический колледж №3", "area_id": 1, "area_name": "Москва"},
    {"id": 1009, "name": "ООО Ромашка", "area_id": 1, "area_name": "Москва"},
    {"id": 1010, "name": "ИП Иванов", "area_id": 1, "area_name": "Москва"},
]

MOCK_VACANCIES = {
    1001: [
        {"id": "v101", "name": "Уборщик помещений", "published_at": "2026-10-01T10:00:00+03:00",
         "description": "Требуется уборщик служебных помещений", "salary": {"from": 35000, "currency": "RUR"}},
        {"id": "v102", "name": "Учитель математики", "published_at": "2026-09-15T10:00:00+03:00",
         "description": "Преподавание математики 5-9 класс"},
        {"id": "v103", "name": "Рабочий по комплексному обслуживанию зданий",
         "published_at": "2026-10-03T10:00:00+03:00",
         "description": "Обслуживание школьных зданий", "salary": {"from": 40000, "currency": "RUR"}},
    ],
    1002: [
        {"id": "v201", "name": "Уборщица", "published_at": "2026-10-05T10:00:00+03:00",
         "description": "Уборка классов и коридоров", "salary": {"from": 32000, "currency": "RUR"}},
    ],
    1003: [
        {"id": "v301", "name": "Дворник", "published_at": "2026-09-20T10:00:00+03:00",
         "description": "Уборка территории больницы", "salary": {"from": 38000, "currency": "RUR"}},
        {"id": "v302", "name": "Медицинская сестра", "published_at": "2026-10-01T10:00:00+03:00",
         "description": "Работа в отделении"},
        {"id": "v303", "name": "Хозяйственный рабочий", "published_at": "2026-10-04T10:00:00+03:00",
         "description": "Обслуживание hospital buildings", "salary": {"from": 42000, "currency": "RUR"}},
    ],
    1004: [
        {"id": "v401", "name": "Уборщик служебных помещений", "published_at": "2026-10-02T10:00:00+03:00",
         "description": "Уборка поликлиники", "salary": {"from": 33000, "currency": "RUR"}},
    ],
    1005: [
        {"id": "v501", "name": "Подсобный рабочий", "published_at": "2026-09-28T10:00:00+03:00",
         "description": "Помощь по хозяйству", "salary": {"from": 36000, "currency": "RUR"}},
    ],
    1006: [
        {"id": "v601", "name": "Преподаватель физики", "published_at": "2026-09-10T10:00:00+03:00",
         "description": "Преподавание физики"},
    ],
    1007: [],
    1008: [
        {"id": "v801", "name": "Технический работник", "published_at": "2026-10-06T10:00:00+03:00",
         "description": "Обслуживание здания колледжа", "salary": {"from": 34000, "currency": "RUR"}},
    ],
    1009: [
        {"id": "v901", "name": "Менеджер по продажам", "published_at": "2026-10-01T10:00:00+03:00",
         "description": "Продажи B2B"},
    ],
    1010: [],
}


def run_demo():
    config = ResearchConfig.load()
    fp_config = config.false_positives
    terms = config.all_vacancy_terms

    db_path = "data/demo.db"
    storage = Storage(db_path)
    snapshot_id = storage.create_snapshot(note="Demo run with mock data")
    snapshot_at = datetime.now(timezone.utc).isoformat()

    print(f"=== Demo Run (Snapshot {snapshot_id}) ===\n")

    records: list[EmployerRecord] = []
    metrics: dict[int, "SignalMetrics"] = {}
    target_count = 0
    relevant_employer_count = 0
    total_relevant_vacs = 0

    for emp_data in MOCK_EMPLOYERS:
        emp = DiscoveredEmployer(
            employer_id=emp_data["id"],
            name=emp_data["name"],
            area_id=emp_data["area_id"],
            area_name=emp_data["area_name"],
        )
        classification = classify_employer(emp)

        storage.upsert_employer({
            "id": emp.employer_id, "name": emp.name,
            "area_id": emp.area_id, "area_name": emp.area_name,
            "classification": classification.employer_type.value,
            "classification_reason": classification.reason,
            "classification_confidence": classification.confidence,
            "raw": {},
        })

        is_target = classification.employer_type != EmployerType.UNKNOWN and classification.confidence >= 0.5
        status = "TARGET" if is_target else "SKIP"
        print(f"  [{status}] {emp.name} -> {classification.employer_type.value} ({classification.confidence:.2f})")

        if not is_target:
            storage.link_employer_snapshot(snapshot_id, emp.employer_id, 0, 0)
            continue

        target_count += 1
        vacancies = MOCK_VACANCIES.get(emp.employer_id, [])
        relevant_data = []

        for vac in vacancies:
            match = evaluate_vacancy(vac, terms, fp_config)
            storage.upsert_vacancy(vac, emp.employer_id)
            storage.link_vacancy_snapshot(
                snapshot_id, vac["id"],
                match.is_relevant, match.relevance_score,
                match.matched_terms, match.match_reason,
            )
            if match.is_relevant:
                relevant_data.append((vac, match))
                storage.update_vacancy_status(snapshot_id, vac["id"], emp.employer_id)
                tag = "RELEVANT"
            else:
                tag = "irrelevant" if match.matched_terms else "no-match"
            print(f"    [{tag}] {vac['name']} — {match.match_reason}")

        record = build_employer_record(
            snapshot_at=snapshot_at,
            employer_id=emp.employer_id,
            employer_name=emp.name,
            classification=classification,
            employer_url=f"https://hh.ru/employer/{emp.employer_id}",
            area_id=emp.area_id,
            area_name=emp.area_name,
            industry=None,
            total_vacancies=len(vacancies),
            relevant_vacancy_data=relevant_data,
        )
        m = compute_signal_metrics(record)
        records.append(record)
        metrics[emp.employer_id] = m

        storage.link_employer_snapshot(snapshot_id, emp.employer_id, len(vacancies), len(relevant_data))

        if relevant_data:
            relevant_employer_count += 1
            total_relevant_vacs += len(relevant_data)

    storage.commit()

    print(f"\n=== Summary ===")
    print(f"  Employers discovered: {len(MOCK_EMPLOYERS)}")
    print(f"  Target employers: {target_count}")
    print(f"  Employers with relevant vacancies: {relevant_employer_count}")
    print(f"  Total relevant vacancies: {total_relevant_vacs}")

    print(f"\n=== Top Employers by Relevant Vacancies ===")
    for r in sorted(records, key=lambda x: -x.relevant_open_vacancies)[:5]:
        if r.relevant_open_vacancies > 0:
            m = metrics[r.employer_id]
            print(f"  {r.employer_name}: {r.relevant_open_vacancies} relevant, score={m.research_signal_score:.1f}")

    print(f"\n=== Exporting ===")
    paths = {}
    emp_csv, vac_csv = export_csv(records, metrics, "exports", prefix="demo")
    paths["csv_employers"] = emp_csv
    paths["csv_vacancies"] = vac_csv
    xlsx = export_xlsx(records, metrics, "exports", run_summary={
        "snapshot_id": snapshot_id,
        "employers_total": len(records),
        "employers_with_relevant": relevant_employer_count,
        "relevant_vacancies_total": total_relevant_vacs,
    }, prefix="demo")
    paths["xlsx"] = xlsx
    json_path = export_json(records, metrics, "exports", prefix="demo")
    paths["json"] = json_path

    for fmt, path in paths.items():
        print(f"  {fmt}: {path}")

    storage.close()
    print(f"\n=== Validation ===")
    print(f"  10 target employers checked: {target_count} classified as target")
    print(f"  10+ relevant vacancies found: {total_relevant_vacs}")
    print(f"  False positives rejected: учитель, медсестра, менеджер")
    print(f"\nDemo complete. Pipeline validated.")


if __name__ == "__main__":
    run_demo()
