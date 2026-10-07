import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import EnrichmentConfig
from ..db.repositories import EmployerRepository, ContactRepository, EnrichmentLogRepository
from .sources.base import EnrichmentSource, EnrichmentResult
from .sources.hh_employer import HHEmployerSource
from .sources.website import WebsiteSource
from .resolver import ContactResolver
from ..api.rate_limiter import RateLimiter
from ..api.client import HHApiClient

logger = logging.getLogger(__name__)


class EnrichmentPipeline:
    def __init__(
        self,
        config: EnrichmentConfig,
        employer_repo: EmployerRepository,
        contact_repo: ContactRepository,
        db_conn: sqlite3.Connection,
    ):
        self._config = config
        self._employer_repo = employer_repo
        self._contact_repo = contact_repo
        self._log_repo = EnrichmentLogRepository(db_conn)
        self._resolver = ContactResolver()
        self._db_conn = db_conn

    def _build_sources(self) -> list[EnrichmentSource]:
        limiter = RateLimiter(per_minute=20, per_day=1500)
        api = HHApiClient(limiter)
        sources: list[EnrichmentSource] = [
            HHEmployerSource(api),
            WebsiteSource(timeout=self._config.request_timeout),
        ]
        sources.sort(key=lambda s: s.priority)
        return sources

    async def enrich_batch(
        self, limit: int = 100
    ) -> dict:
        start = time.monotonic()
        employers = self._employer_repo.get_needs_enrichment(limit=limit)

        result = {
            "total_processed": 0,
            "successful": 0,
            "failed": 0,
            "contacts_found": 0,
            "duration_seconds": 0.0,
        }

        sources = self._build_sources()

        for employer in employers:
            result["total_processed"] += 1
            try:
                enr_result = await self._enrich_with_sources(employer, sources)
                if enr_result["success"]:
                    result["successful"] += 1
                    result["contacts_found"] += len(enr_result.get("contacts", []))
                else:
                    result["failed"] += 1
            except Exception as e:
                logger.error("Failed to enrich employer %d: %s", employer["id"], e)
                result["failed"] += 1

        for s in sources:
            if hasattr(s, "close"):
                await s.close()

        result["duration_seconds"] = time.monotonic() - start
        return result

    async def enrich_single(self, employer_id: int) -> dict:
        employer = self._employer_repo.get_by_id(employer_id)
        if not employer:
            return {"success": False, "error": f"Employer {employer_id} not found"}

        sources = self._build_sources()
        try:
            result = await self._enrich_with_sources(employer, sources)
        finally:
            for s in sources:
                if hasattr(s, "close"):
                    await s.close()
        return result

    async def _enrich_with_sources(
        self, employer: dict, sources: list[EnrichmentSource]
    ) -> dict:
        all_contacts = []

        for source in sources:
            if not source.can_handle(employer):
                continue

            self._employer_repo.update_enrichment_status(employer["id"], "in_progress")
            self._log_repo.log(employer["id"], source.name, "started")

            try:
                result = await source.fetch(employer)
                if result.success:
                    all_contacts.extend(result.contacts)
                    self._log_repo.log(
                        employer["id"],
                        source.name,
                        "success",
                        f"contacts={len(result.contacts)}",
                    )
                else:
                    self._log_repo.log(
                        employer["id"], source.name, "failed", result.error
                    )
            except Exception as e:
                self._log_repo.log(employer["id"], source.name, "failed", str(e))

        resolved = self._resolver.resolve(all_contacts)
        signal_score = self._resolver.compute_signal_score(employer, resolved)

        contact_data = self._build_contact_dict(resolved)
        contact_data["contact_confidence"] = (
            max((c.confidence for c in resolved), default=0.0)
        )

        self._employer_repo.update_enriched_contacts(employer["id"], contact_data)
        self._employer_repo.update_signal_score(employer["id"], signal_score)

        ttl = datetime.now(timezone.utc) + timedelta(hours=self._config.ttl_hours)
        self._employer_repo.update_enrichment_status(
            employer["id"], "done", self._config.ttl_hours
        )

        for c in resolved:
            self._contact_repo.upsert(
                employer_id=employer["id"],
                contact_type=c.contact_type,
                value=c.value,
                source_url=c.source_url,
                source_type=c.source_type,
                confidence=c.confidence,
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

    def _build_contact_dict(self, resolved: list) -> dict:
        result: dict = {}
        for c in resolved:
            if c.contact_type == "website" and c.is_primary:
                result["official_website"] = c.value
                result["contact_source_url"] = c.source_url
            elif c.contact_type == "phone" and c.is_primary:
                result["official_phone"] = c.value
            elif c.contact_type == "email" and c.is_primary:
                result["official_email"] = c.value
            elif c.contact_type == "address" and c.is_primary:
                result["official_address"] = c.value

        facility_contacts = [c for c in resolved if c.is_facility]
        for c in facility_contacts:
            if c.contact_type == "phone":
                result["facility_contact_phone"] = c.value
            elif c.contact_type == "email":
                result["facility_contact_email"] = c.value

        return result
