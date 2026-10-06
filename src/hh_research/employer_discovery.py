"""Employer discovery: search by taxonomy terms, deduplicate by employer_id."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .api_client import HHApiClient

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredEmployer:
    employer_id: int
    name: str
    url: str | None = None
    area_id: int | None = None
    area_name: str | None = None
    description: str | None = None
    industry: str | None = None
    discovered_via_term: str = ""
    raw: dict = field(default_factory=dict)


class EmployerDiscovery:
    def __init__(self, client: HHApiClient):
        self.client = client

    def discover(self, terms: list[str], area_ids: list[int]) -> dict[int, DiscoveredEmployer]:
        found: dict[int, DiscoveredEmployer] = {}
        for area_id in area_ids:
            for term in terms:
                logger.info("Searching employers: term=%r area=%s", term, area_id)
                try:
                    results = self.client.search_employers(term, area_id=area_id)
                except Exception as e:
                    logger.warning("Employer search failed for %r in area %s: %s", term, area_id, e)
                    continue
                for item in results:
                    eid = item.get("id")
                    if eid is None:
                        continue
                    if eid in found:
                        continue
                    area = item.get("area") or {}
                    found[eid] = DiscoveredEmployer(
                        employer_id=int(eid),
                        name=item.get("name", ""),
                        url=item.get("url") or item.get("alternate_url"),
                        area_id=area.get("id"),
                        area_name=area.get("name"),
                        discovered_via_term=term,
                        raw=item,
                    )
                logger.info(
                    "Term %r area %s: %d results, %d unique so far",
                    term, area_id, len(results), len(found),
                )
        logger.info("Employer discovery complete: %d unique employers", len(found))
        return found

    def enrich(self, employer: DiscoveredEmployer) -> DiscoveredEmployer:
        try:
            detail = self.client.get_employer(employer.employer_id)
        except Exception as e:
            logger.warning("Failed to enrich employer %d: %s", employer.employer_id, e)
            return employer
        employer.description = detail.get("description")
        employer.url = detail.get("url") or detail.get("alternate_url") or employer.url
        area = detail.get("area") or {}
        if area:
            employer.area_id = area.get("id")
            employer.area_name = area.get("name")
        industries = detail.get("industries") or []
        if industries:
            employer.industry = industries[0].get("name")
        employer.raw = detail
        return employer
