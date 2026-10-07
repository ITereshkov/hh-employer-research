"""Global vacancy discovery via HH /vacancies search endpoint."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..api_client import HHApiClient
from .classifier import RoleClassification, RoleCategory, classify_role
from .config import CleaningSignalConfig

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredVacancy:
    vacancy_id: str
    name: str
    url: str | None
    employer_id: int | None
    employer_name: str | None
    area_id: int | None
    area_name: str | None
    published_at: str | None
    salary_from: int | None
    salary_to: int | None
    currency: str | None
    schedule: str | None
    employment: str | None
    experience: str | None
    classification: RoleClassification
    matched_query: str = ""
    raw: dict = field(default_factory=dict)


class VacancyDiscovery:
    def __init__(self, client: HHApiClient, config: CleaningSignalConfig):
        self.client = client
        self.config = config

    def discover(self) -> list[DiscoveredVacancy]:
        taxonomy = self.config.query_taxonomy
        exclusions = self.config.exclusions
        areas = self.config.discovery.areas
        max_total = self.config.discovery.max_total_vacancies

        seen_ids: set[str] = set()
        results: list[DiscoveredVacancy] = []
        total_raw = 0

        for area_id in areas:
            for term in taxonomy.all_terms:
                if len(results) >= max_total:
                    logger.info("Reached max_total_vacancies=%d, stopping", max_total)
                    break

                query = term
                params = {
                    "text": query,
                    "area": area_id,
                    "per_page": self.config.discovery.per_page,
                    "search_field": "name",
                }

                logger.info(
                    "Searching vacancies: term=%r area=%s", term, area_id,
                )

                try:
                    items = self.client.paginate(
                        "/vacancies", params,
                        max_pages=self.config.discovery.max_pages_per_query,
                    )
                except Exception as e:
                    logger.warning(
                        "Vacancy search failed for %r in area %s: %s",
                        term, area_id, e,
                    )
                    continue

                total_raw += len(items)
                new_in_batch = 0

                for item in items:
                    vid = str(item.get("id", ""))
                    if vid in seen_ids:
                        continue
                    seen_ids.add(vid)

                    classification = classify_role(item, taxonomy, exclusions)

                    employer = item.get("employer") or {}
                    area = item.get("area") or {}
                    salary = item.get("salary") or {}

                    dv = DiscoveredVacancy(
                        vacancy_id=vid,
                        name=item.get("name", ""),
                        url=item.get("alternate_url") or item.get("url"),
                        employer_id=employer.get("id"),
                        employer_name=employer.get("name"),
                        area_id=area.get("id"),
                        area_name=area.get("name"),
                        published_at=item.get("published_at"),
                        salary_from=salary.get("from"),
                        salary_to=salary.get("to"),
                        currency=salary.get("currency"),
                        schedule=(item.get("schedule") or {}).get("name"),
                        employment=(item.get("employment") or {}).get("name"),
                        experience=(item.get("experience") or {}).get("name"),
                        classification=classification,
                        matched_query=term,
                        raw=item,
                    )

                    if classification.is_relevant:
                        results.append(dv)
                        new_in_batch += 1

                logger.info(
                    "Term %r area %s: %d raw, %d new relevant, %d total relevant",
                    term, area_id, len(items), new_in_batch, len(results),
                )

        logger.info(
            "Discovery complete: %d raw vacancies reviewed, %d relevant, %d unique",
            total_raw, len(results), len(seen_ids),
        )
        return results
