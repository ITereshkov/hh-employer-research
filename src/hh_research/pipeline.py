"""Pipeline orchestrator: ties discovery → classification → vacancy scan → storage → export."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from .aggregation import (
    EmployerRecord,
    SignalMetrics,
    build_employer_record,
    compute_signal_metrics,
)
from .api_client import HHApiClient
from .config import ResearchConfig
from .employer_classifier import classify_employer, is_target_employer
from .employer_discovery import DiscoveredEmployer, EmployerDiscovery
from .export import export_csv, export_json, export_xlsx
from .storage import Storage
from .vacancy_relevance import VacancyMatch, evaluate_vacancy

logger = logging.getLogger(__name__)


class ResearchPipeline:
    def __init__(self, config: ResearchConfig):
        self.config = config
        self.client = HHApiClient(config.api, config.storage)
        self.storage = Storage(config.storage.db_path)
        self.discovery = EmployerDiscovery(self.client)
        self.records: list[EmployerRecord] = []
        self.metrics: dict[int, SignalMetrics] = {}
        self.snapshot_id: int | None = None

    def run(self, areas: list[int] | None = None) -> dict:
        areas = areas or self.config.areas.ids
        snapshot_at = datetime.now(timezone.utc).isoformat()
        config_hash = hashlib.sha256(
            json.dumps(self.config.__dict__, default=str, sort_keys=True).encode()
        ).hexdigest()[:12]

        self.snapshot_id = self.storage.create_snapshot(
            config_hash=config_hash,
            areas=json.dumps(areas),
            note=f"Run with {len(areas)} area(s)",
        )
        logger.info("Snapshot %d created at %s", self.snapshot_id, snapshot_at)

        logger.info("=== Phase 1: Employer Discovery ===")
        discovered = self.discovery.discover(self.config.all_employer_terms, areas)
        logger.info("Discovered %d unique employers", len(discovered))

        logger.info("=== Phase 2: Employer Enrichment & Classification ===")
        target_employers: dict[int, DiscoveredEmployer] = {}
        for eid, emp in discovered.items():
            emp = self.discovery.enrich(emp)
            classification = classify_employer(emp)
            if is_target_employer(classification):
                target_employers[eid] = emp
                logger.debug(
                    "Employer %d %r → %s (%.2f)",
                    eid, emp.name, classification.employer_type.value, classification.confidence,
                )
            else:
                logger.debug(
                    "Employer %d %r → %s (not target: %s)",
                    eid, emp.name, classification.employer_type.value, classification.reason,
                )
        logger.info("Target employers: %d / %d", len(target_employers), len(discovered))

        logger.info("=== Phase 3: Vacancy Scan & Relevance ===")
        all_terms = self.config.all_vacancy_terms
        seen_vacancy_ids: set[str] = set()

        for eid, emp in target_employers.items():
            classification = classify_employer(emp)
            try:
                vacancies = self.client.get_employer_vacancies(eid)
            except Exception as e:
                logger.warning("Failed to fetch vacancies for employer %d: %s", eid, e)
                vacancies = []

            relevant_data: list[tuple[dict, VacancyMatch]] = []
            for vac in vacancies:
                vid = str(vac.get("id", ""))
                seen_vacancy_ids.add(vid)
                match = evaluate_vacancy(vac, all_terms, self.config.false_positives)
                self.storage.upsert_vacancy(vac, eid)
                self.storage.link_vacancy_snapshot(
                    self.snapshot_id, vid,
                    match.is_relevant, match.relevance_score,
                    match.matched_terms, match.match_reason,
                )
                if match.is_relevant:
                    relevant_data.append((vac, match))
                    self.storage.update_vacancy_status(self.snapshot_id, vid, eid)

            record = build_employer_record(
                snapshot_at=snapshot_at,
                employer_id=eid,
                employer_name=emp.name,
                classification=classification,
                employer_url=emp.url,
                area_id=emp.area_id,
                area_name=emp.area_name,
                industry=emp.industry,
                total_vacancies=len(vacancies),
                relevant_vacancy_data=relevant_data,
            )
            self.metrics[eid] = compute_signal_metrics(record)
            self.records.append(record)

            emp_dict = {
                "id": eid, "name": emp.name, "url": emp.url,
                "area_id": emp.area_id, "area_name": emp.area_name,
                "description": emp.description, "industry": emp.industry,
                "classification": classification.employer_type.value,
                "classification_reason": classification.reason,
                "classification_confidence": classification.confidence,
                "raw": emp.raw,
            }
            self.storage.upsert_employer(emp_dict)
            self.storage.link_employer_snapshot(
                self.snapshot_id, eid, len(vacancies), len(relevant_data),
            )

        self.storage.mark_disappeared_vacancies(self.snapshot_id, seen_vacancy_ids)
        self.storage.commit()

        relevant_employers = [r for r in self.records if r.relevant_open_vacancies > 0]
        total_relevant_vacs = sum(r.relevant_open_vacancies for r in self.records)

        summary = {
            "snapshot_id": self.snapshot_id,
            "snapshot_at": snapshot_at,
            "areas": areas,
            "employers_discovered": len(discovered),
            "target_employers": len(target_employers),
            "employers_with_relevant_vacancies": len(relevant_employers),
            "total_relevant_vacancies": total_relevant_vacs,
            "new_vacancies": self.storage.count_new_vacancies(self.snapshot_id),
        }
        logger.info("=== Run Summary ===")
        for k, v in summary.items():
            logger.info("  %s: %s", k, v)

        return summary

    def export_all(self, formats: list[str] | None = None, prefix: str = "research") -> dict:
        formats = formats or ["csv", "xlsx", "json"]
        paths = {}
        summary = {
            "snapshot_id": self.snapshot_id,
            "employers_total": len(self.records),
            "employers_with_relevant": sum(1 for r in self.records if r.relevant_open_vacancies > 0),
            "relevant_vacancies_total": sum(r.relevant_open_vacancies for r in self.records),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        if "csv" in formats:
            emp_path, vac_path = export_csv(
                self.records, self.metrics, self.config.export_dir, prefix,
            )
            paths["csv_employers"] = emp_path
            paths["csv_vacancies"] = vac_path
        if "xlsx" in formats:
            paths["xlsx"] = export_xlsx(
                self.records, self.metrics, self.config.export_dir, summary, prefix,
            )
        if "json" in formats:
            paths["json"] = export_json(
                self.records, self.metrics, self.config.export_dir, prefix,
            )
        return paths

    def close(self):
        self.storage.close()
