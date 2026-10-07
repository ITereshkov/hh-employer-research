"""Cleaning-signal pipeline: discovery → aggregate → score → enrich → export."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from ..api_client import HHApiClient
from ..enrichment.pipeline import EnrichmentPipeline
from ..storage import Storage
from .aggregation import EmployerAggregate, aggregate_employers, select_enrichment_cohort
from .config import CleaningSignalConfig
from .discovery import VacancyDiscovery
from .export import export_cleaning_xlsx

logger = logging.getLogger(__name__)


class CleaningSignalPipeline:
    def __init__(self, config: CleaningSignalConfig):
        self.config = config
        self.client = HHApiClient(config.api, config.storage)
        self.storage = Storage(config.storage.db_path)
        self.enrichment = EnrichmentPipeline(self.client, self.storage)
        self.employers: dict[int, EmployerAggregate] = {}
        self.vacancies_discovered: list = []
        self.snapshot_id: int | None = None
        self.total_raw = 0
        self.total_relevant = 0
        self.total_rejected = 0
        self.enriched: dict[int, dict] = {}

    def run_discovery(self) -> int:
        logger.info("=== Phase 1: Vacancy Discovery ===")
        discovery = VacancyDiscovery(self.client, self.config)
        self.vacancies_discovered = discovery.discover()

        relevant = [v for v in self.vacancies_discovered if v.classification.is_relevant]
        self.total_relevant = len(relevant)

        self.total_raw = len(self.vacancies_discovered)

        logger.info(
            "Discovery complete: %d relevant vacancies found",
            self.total_relevant,
        )
        return self.total_relevant

    def run_aggregation(self) -> dict[int, EmployerAggregate]:
        logger.info("=== Phase 2: Employer Aggregation ===")
        self.employers = aggregate_employers(
            self.vacancies_discovered,
            self.config.scoring,
            self.config.cleaning_provider,
        )

        high = sum(1 for e in self.employers.values() if e.signal_level == "HIGH")
        medium = sum(1 for e in self.employers.values() if e.signal_level == "MEDIUM")
        low = sum(1 for e in self.employers.values() if e.signal_level == "LOW")

        logger.info(
            "Aggregation: %d employers (HIGH=%d, MEDIUM=%d, LOW=%d)",
            len(self.employers), high, medium, low,
        )
        return self.employers

    def save_to_storage(self):
        config_hash = hashlib.sha256(
            json.dumps(self.config.__dict__, default=str, sort_keys=True).encode()
        ).hexdigest()[:12]
        areas = json.dumps(self.config.discovery.areas)

        self.snapshot_id = self.storage.create_snapshot(
            config_hash=config_hash,
            areas=areas,
            note=f"Cleaning signal: {len(self.employers)} employers, {self.total_relevant} relevant vacancies",
        )

        seen_vacancy_ids: set[str] = set()

        for emp in self.employers.values():
            emp_dict = {
                "id": emp.employer_id,
                "name": emp.employer_name,
                "url": emp.employer_hh_url,
                "area_id": None,
                "area_name": " | ".join(emp.regions) if emp.regions else None,
                "description": None,
                "industry": ", ".join(emp.industries) if emp.industries else None,
                "classification": emp.employer_category.value,
                "classification_reason": emp.employer_category_reason,
                "classification_confidence": emp.employer_category_confidence,
                "raw": emp.raw_employer_data,
            }
            self.storage.upsert_employer(emp_dict)
            self.storage.link_employer_snapshot(
                self.snapshot_id, emp.employer_id,
                emp.total_hh_vacancies, emp.total_relevant,
            )
            self.storage.update_employer_enrichment(
                emp.employer_id, "pending",
                signal_score=emp.signal_score,
            )

            for v in emp.relevant_vacancies:
                vid = v.vacancy_id
                seen_vacancy_ids.add(vid)
                vac_dict = {
                    "id": vid,
                    "name": v.name,
                    "url": v.url,
                    "published_at": v.published_at,
                    "salary_from": v.salary_from,
                    "salary_to": v.salary_to,
                    "currency": v.currency,
                    "schedule": None,
                    "employment": None,
                    "experience": None,
                    "area_id": v.area_id,
                    "area_name": v.area_name,
                }
                self.storage.upsert_vacancy(vac_dict, emp.employer_id)
                self.storage.link_vacancy_snapshot(
                    self.snapshot_id, vid,
                    True, v.relevance_score,
                    v.matched_terms,
                    f"{v.role_category.value}: {', '.join(v.matched_terms[:3])}",
                )
                self.storage.update_vacancy_status(self.snapshot_id, vid, emp.employer_id)

        self.storage.mark_disappeared_vacancies(self.snapshot_id, seen_vacancy_ids)
        self.storage.commit()
        logger.info("Snapshot %d saved with %d employers", self.snapshot_id, len(self.employers))

    def run_enrichment(self) -> dict:
        logger.info("=== Phase 3: Enrichment ===")
        cohort_config = self.config.enrichment_cohort
        cohort_ids = select_enrichment_cohort(
            self.employers,
            cohort_config.signal_levels,
            cohort_config.max_employers,
            cohort_config.min_signal_score,
            cohort_config.include_top_medium,
        )

        logger.info("Enrichment cohort: %d employers", len(cohort_ids))

        result = {
            "cohort_size": len(cohort_ids),
            "successful": 0,
            "failed": 0,
            "contacts_found": 0,
        }

        for eid in cohort_ids:
            try:
                enr = self.enrichment.enrich_single(eid)
                if enr.get("success"):
                    result["successful"] += 1
                    contacts = enr.get("contacts", [])
                    result["contacts_found"] += len(contacts)

                    contact_dict: dict = {}
                    for c in contacts:
                        ct = c.get("contact_type", "")
                        val = c.get("value", "")
                        if ct == "website":
                            contact_dict["official_website"] = val
                        elif ct == "phone":
                            if "facility_contact_phone" not in contact_dict:
                                contact_dict["official_phone"] = val
                        elif ct == "email":
                            if "facility_contact_email" not in contact_dict:
                                contact_dict["official_email"] = val
                        elif ct == "address":
                            contact_dict["official_address"] = val

                    all_contacts = self.storage.get_contacts(eid)
                    for c in all_contacts:
                        if c.get("is_facility"):
                            if c["contact_type"] == "phone":
                                contact_dict["facility_contact_phone"] = c["value"]
                            elif c["contact_type"] == "email":
                                contact_dict["facility_contact_email"] = c["value"]

                    max_conf = max(
                        (c.get("confidence", 0) for c in all_contacts),
                        default=0.0,
                    )
                    contact_dict["contact_confidence"] = max_conf
                    contact_dict["enrichment_status"] = "done"

                    self.enriched[eid] = contact_dict
                else:
                    result["failed"] += 1
                    self.enriched[eid] = {"enrichment_status": "failed"}
            except Exception as e:
                logger.warning("Enrichment failed for employer %d: %s", eid, e)
                result["failed"] += 1
                self.enriched[eid] = {"enrichment_status": "failed", "error": str(e)}

        self.storage.commit()
        logger.info(
            "Enrichment done: %d ok, %d failed, %d contacts",
            result["successful"], result["failed"], result["contacts_found"],
        )
        return result

    def run_export(self) -> str:
        logger.info("=== Phase 4: Export ===")
        path = export_cleaning_xlsx(
            employers=list(self.employers.values()),
            total_raw=self.total_raw,
            total_relevant=self.total_relevant,
            total_rejected=self.total_rejected,
            export_dir=self.config.export_dir,
            enriched=self.enriched,
        )
        logger.info("Export: %s", path)
        return path

    def run(self) -> dict:
        self.run_discovery()
        self.run_aggregation()
        self.save_to_storage()
        self.run_enrichment()
        export_path = self.run_export()

        summary = self.build_summary()
        summary["export_path"] = export_path

        logger.info("=== Cleaning Signal Run Complete ===")
        for k, v in summary.items():
            logger.info("  %s: %s", k, v)

        return summary

    def build_summary(self) -> dict:
        high = [e for e in self.employers.values() if e.signal_level == "HIGH"]
        medium = [e for e in self.employers.values() if e.signal_level == "MEDIUM"]
        low = [e for e in self.employers.values() if e.signal_level == "LOW"]
        providers = [e for e in self.employers.values() if e.is_cleaning_provider]
        end_customers = [e for e in self.employers.values() if not e.is_cleaning_provider]

        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "areas": self.config.discovery.areas,
            "total_raw_vacancies": self.total_raw,
            "total_relevant_vacancies": self.total_relevant,
            "total_rejected_vacancies": self.total_rejected,
            "unique_employers": len(self.employers),
            "end_customer_candidates": len(end_customers),
            "cleaning_providers": len(providers),
            "high_signal": len(high),
            "medium_signal": len(medium),
            "low_signal": len(low),
            "enriched_employers": len(self.enriched),
            "top_employers": [
                {
                    "employer_id": e.employer_id,
                    "employer_name": e.employer_name,
                    "signal_score": e.signal_score,
                    "signal_level": e.signal_level,
                    "relevant_count": e.total_relevant,
                    "regions": e.regions,
                }
                for e in sorted(self.employers.values(), key=lambda x: x.signal_score, reverse=True)[:20]
            ],
        }

    def close(self):
        self.storage.close()
