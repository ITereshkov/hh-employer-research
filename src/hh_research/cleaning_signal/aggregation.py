"""Employer-level aggregation, signal scoring, and cohort selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .classifier import (
    EmployerCategory,
    EmployerCategoryResult,
    RoleCategory,
    classify_employer_category,
)
from .config import CleaningProviderConfig, ScoringConfig
from .discovery import DiscoveredVacancy

logger = logging.getLogger(__name__)


@dataclass
class VacancySummary:
    vacancy_id: str
    name: str
    url: str | None
    published_at: str | None
    role_category: RoleCategory
    matched_terms: list[str]
    relevance_score: float
    area_id: int | None
    area_name: str | None
    salary_from: int | None
    salary_to: int | None
    currency: str | None


@dataclass
class EmployerAggregate:
    employer_id: int
    employer_name: str
    employer_hh_url: str | None
    employer_site_url: str | None = None
    employer_category: EmployerCategory = EmployerCategory.OTHER
    employer_category_reason: str = ""
    employer_category_confidence: float = 0.0
    is_cleaning_provider: bool = False

    regions: list[str] = field(default_factory=list)
    areas: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)

    total_hh_vacancies: int = 0
    relevant_vacancies: list[VacancySummary] = field(default_factory=list)

    cleaning_count: int = 0
    facility_count: int = 0
    janitorial_count: int = 0
    mixed_count: int = 0
    other_relevant_count: int = 0

    unique_roles: set[str] = field(default_factory=set)
    unique_locations: set[str] = field(default_factory=set)
    unique_areas: set[str] = field(default_factory=set)

    latest_relevant_publication: str | None = None
    oldest_relevant_publication: str | None = None
    days_since_latest: int | None = None

    fresh_7d_count: int = 0
    fresh_30d_count: int = 0

    multi_location_signal: bool = False
    repeat_signal: bool = False

    signal_score: float = 0.0
    signal_components: dict[str, float] = field(default_factory=dict)
    signal_level: str = "LOW"

    raw_employer_data: dict = field(default_factory=dict)

    @property
    def total_relevant(self) -> int:
        return len(self.relevant_vacancies)

    @property
    def unique_role_count(self) -> int:
        return len(self.unique_roles)

    @property
    def unique_location_count(self) -> int:
        return len(self.unique_locations)

    @property
    def signal_reason(self) -> str:
        parts = []
        if self.total_relevant:
            parts.append(f"{self.total_relevant} active relevant vacancies")
        if self.fresh_7d_count:
            parts.append(f"{self.fresh_7d_count} posted in last 7d")
        if self.unique_role_count > 1:
            parts.append(f"{self.unique_role_count} role types")
        if self.multi_location_signal:
            parts.append(f"{self.unique_location_count} locations")
        if self.repeat_signal:
            parts.append("repeat signal")
        return "; ".join(parts) if parts else "no signal"


def aggregate_employers(
    vacancies: list[DiscoveredVacancy],
    scoring: ScoringConfig,
    cp_config: CleaningProviderConfig | None = None,
    historical_relevant_ids: set[str] | None = None,
) -> dict[int, EmployerAggregate]:
    employers: dict[int, EmployerAggregate] = {}

    for v in vacancies:
        if not v.classification.is_relevant:
            continue
        eid = v.employer_id
        if eid is None:
            continue

        if eid not in employers:
            employers[eid] = EmployerAggregate(
                employer_id=eid,
                employer_name=v.employer_name or "",
                employer_hh_url=f"https://hh.ru/employer/{eid}",
            )

        emp = employers[eid]
        summary = VacancySummary(
            vacancy_id=v.vacancy_id,
            name=v.name,
            url=v.url,
            published_at=v.published_at,
            role_category=v.classification.role_category,
            matched_terms=v.classification.matched_terms,
            relevance_score=v.classification.relevance_score,
            area_id=v.area_id,
            area_name=v.area_name,
            salary_from=v.salary_from,
            salary_to=v.salary_to,
            currency=v.currency,
        )
        emp.relevant_vacancies.append(summary)
        emp.unique_roles.add(v.name.strip().lower())

        if v.area_name:
            emp.unique_areas.add(v.area_name)
            emp.unique_locations.add(v.area_name)
        if v.area_name and v.area_name not in emp.regions:
            emp.regions.append(v.area_name)
            emp.areas.append(v.area_name)

        cat = v.classification.role_category
        if cat == RoleCategory.INDOOR_CLEANING:
            emp.cleaning_count += 1
        elif cat == RoleCategory.JANITORIAL:
            emp.janitorial_count += 1
        elif cat == RoleCategory.FACILITY_MAINTENANCE:
            emp.facility_count += 1
        elif cat == RoleCategory.MIXED_CLEANING_MAINTENANCE:
            emp.mixed_count += 1
        else:
            emp.other_relevant_count += 1

        if v.published_at:
            if emp.latest_relevant_publication is None or v.published_at > emp.latest_relevant_publication:
                emp.latest_relevant_publication = v.published_at
            if emp.oldest_relevant_publication is None or v.published_at < emp.oldest_relevant_publication:
                emp.oldest_relevant_publication = v.published_at

    now = datetime.now(timezone.utc)
    for emp in employers.values():
        if emp.latest_relevant_publication:
            try:
                dt = datetime.fromisoformat(
                    emp.latest_relevant_publication.replace("Z", "+00:00")
                )
                emp.days_since_latest = (now - dt).days
            except (ValueError, TypeError):
                pass

        for v in emp.relevant_vacancies:
            if v.published_at:
                try:
                    dt = datetime.fromisoformat(v.published_at.replace("Z", "+00:00"))
                    age = (now - dt).days
                    if age <= 7:
                        emp.fresh_7d_count += 1
                    if age <= 30:
                        emp.fresh_30d_count += 1
                except (ValueError, TypeError):
                    pass

        emp.multi_location_signal = len(emp.unique_locations) > 1

        if historical_relevant_ids:
            emp_vacancy_ids = {v.vacancy_id for v in emp.relevant_vacancies}
            if emp_vacancy_ids & historical_relevant_ids:
                emp.repeat_signal = True

        _classify_employer(emp, cp_config)
        _compute_score(emp, scoring)

    return employers


def _classify_employer(emp: EmployerAggregate, cp_config: CleaningProviderConfig | None):
    result = classify_employer_category(
        emp.employer_name,
        employer_industry=", ".join(emp.industries) if emp.industries else None,
        cleaning_provider_config=cp_config,
    )
    emp.employer_category = result.category
    emp.employer_category_reason = result.reason
    emp.employer_category_confidence = result.confidence
    emp.is_cleaning_provider = result.is_cleaning_provider


def _compute_score(emp: EmployerAggregate, scoring: ScoringConfig):
    components: dict[str, float] = {}

    c = emp.total_relevant * scoring.weight_per_vacancy
    components["vacancy_count"] = round(c, 2)

    c = emp.fresh_7d_count * scoring.weight_fresh_7d
    components["fresh_7d"] = round(c, 2)

    c = emp.fresh_30d_count * scoring.weight_fresh_30d
    components["fresh_30d"] = round(c, 2)

    c = emp.unique_role_count * scoring.weight_unique_role
    components["unique_roles"] = round(c, 2)

    c = emp.unique_location_count * scoring.weight_unique_location
    components["unique_locations"] = round(c, 2)

    if emp.multi_location_signal:
        c = scoring.weight_multi_location
    else:
        c = 0.0
    components["multi_location"] = round(c, 2)

    if emp.repeat_signal:
        c = scoring.weight_repeat_signal
    else:
        c = 0.0
    components["repeat_signal"] = round(c, 2)

    emp.signal_score = round(sum(components.values()), 2)
    emp.signal_components = components

    if emp.signal_score >= scoring.threshold_high:
        emp.signal_level = "HIGH"
    elif emp.signal_score >= scoring.threshold_medium:
        emp.signal_level = "MEDIUM"
    else:
        emp.signal_level = "LOW"


def select_enrichment_cohort(
    employers: dict[int, EmployerAggregate],
    signal_levels: list[str],
    max_employers: int,
    min_score: float = 0.0,
    include_top_medium: int = 0,
) -> list[int]:
    candidates = [
        emp for emp in employers.values()
        if emp.signal_level in signal_levels and emp.signal_score >= min_score
    ]
    candidates.sort(key=lambda e: e.signal_score, reverse=True)

    selected = [e.employer_id for e in candidates[:max_employers]]

    if include_top_medium > 0 and len(selected) < max_employers:
        medium = [
            emp for emp in employers.values()
            if emp.signal_level == "MEDIUM" and emp.employer_id not in selected
        ]
        medium.sort(key=lambda e: e.signal_score, reverse=True)
        remaining = max_employers - len(selected)
        for emp in medium[:min(include_top_medium, remaining)]:
            selected.append(emp.employer_id)

    return selected
