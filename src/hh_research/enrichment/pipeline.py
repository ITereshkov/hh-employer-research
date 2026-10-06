"""Enrichment pipeline: orchestrates sources, resolver, storage."""

from __future__ import annotations

import logging
import time

from .resolver import ContactResolver, ResolvedContact
from .sources.base import EnrichmentResult, EnrichmentSource
from .sources.hh_employer import HHEmployerSource
from .sources.website import WebsiteSource
from ..api_client import HHApiClient
from ..storage import Storage

logger = logging.getLogger(__name__)


class EnrichmentPipeline:
    def __init__(self, api_client: HHApiClient, storage: Storage,
                 website_timeout: float = 15.0, ttl_hours: float = 24.0):
        self._api = api_client
        self._storage = storage
        self._resolver = ContactResolver()
        self._ttl_hours = ttl_hours
        self._website_timeout = website_timeout

    def _build_sources(self) -> list[EnrichmentSource]:
        sources: list[EnrichmentSource] = [
            HHEmployerSource(self._api),
            WebsiteSource(timeout=self._website_timeout),
        ]
        sources.sort(key=lambda s: s.priority)
        return sources

    def enrich_batch(self, limit: int = 100) -> dict:
        start = time.monotonic()
        employers = self._storage.get_employers_needing_enrichment(limit=limit)

        result = {
            "total_processed": 0,
            "successful": 0,
            "failed": 0,
            "contacts_found": 0,
            "duration_seconds": 0.0,
        }

        sources = self._build_sources()

        for emp in employers:
            result["total_processed"] += 1
            try:
                enr = self._enrich_one(emp, sources)
                if enr["success"]:
                    result["successful"] += 1
                    result["contacts_found"] += len(enr.get("contacts", []))
                else:
                    result["failed"] += 1
            except Exception as e:
                logger.error("Failed to enrich employer %d: %s", emp["id"], e)
                result["failed"] += 1

        self._storage.commit()
        result["duration_seconds"] = time.monotonic() - start
        logger.info(
            "Enrichment batch: %d processed, %d ok, %d failed, %d contacts in %.1fs",
            result["total_processed"], result["successful"],
            result["failed"], result["contacts_found"],
            result["duration_seconds"],
        )
        return result

    def enrich_single(self, employer_id: int) -> dict:
        rows = self._storage.conn.execute(
            "SELECT * FROM employers WHERE id = ?", (employer_id,)
        ).fetchall()
        if not rows:
            return {"success": False, "error": f"Employer {employer_id} not found"}
        emp = dict(rows[0])
        sources = self._build_sources()
        return self._enrich_one(emp, sources)

    def _enrich_one(self, employer: dict, sources: list[EnrichmentSource]) -> dict:
        eid = employer["id"]
        all_contacts: list = []

        for source in sources:
            if not source.can_handle(employer):
                continue

            self._storage.update_employer_enrichment(eid, "in_progress")
            self._storage.log_enrichment(eid, source.name, "started")

            try:
                result = source.fetch(employer)
                if result.success:
                    all_contacts.extend(result.contacts)
                    self._storage.log_enrichment(
                        eid, source.name, "success",
                        f"contacts={len(result.contacts)}",
                    )
                else:
                    self._storage.log_enrichment(eid, source.name, "failed", result.error)
            except Exception as e:
                self._storage.log_enrichment(eid, source.name, "failed", str(e))

        resolved = self._resolver.resolve(all_contacts)
        signal_score = self._resolver.compute_signal_score(employer, resolved)
        contact_dict = self._build_contact_dict(resolved)

        self._storage.update_employer_enrichment(
            eid, "done", ttl_hours=self._ttl_hours,
            signal_score=signal_score, contacts=contact_dict,
        )

        for c in resolved:
            self._storage.upsert_contact(
                employer_id=eid,
                contact_type=c.contact_type,
                value=c.value,
                source_url=c.source_url,
                source_type=c.source_type,
                confidence=c.confidence,
                is_primary=c.is_primary,
                is_facility=c.is_facility,
            )

        return {
            "success": True,
            "contacts": [
                {
                    "contact_type": c.contact_type,
                    "value": c.value,
                    "source_type": c.source_type,
                    "confidence": c.confidence,
                }
                for c in resolved
            ],
            "signal_score": signal_score,
        }

    @staticmethod
    def _build_contact_dict(resolved: list[ResolvedContact]) -> dict:
        result: dict = {}
        for c in resolved:
            if c.contact_type == "website" and c.is_primary:
                result["official_website"] = c.value
            elif c.contact_type == "phone" and c.is_primary:
                result["official_phone"] = c.value
            elif c.contact_type == "email" and c.is_primary:
                result["official_email"] = c.value
            elif c.contact_type == "address" and c.is_primary:
                result["official_address"] = c.value

        for c in resolved:
            if not c.is_facility:
                continue
            if c.contact_type == "phone" and "facility_contact_phone" not in result:
                result["facility_contact_phone"] = c.value
            elif c.contact_type == "email" and "facility_contact_email" not in result:
                result["facility_contact_email"] = c.value

        return result
