"""Employer-level aggregation and research signal metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .employer_classifier import ClassificationResult, EmployerType
from .vacancy_relevance import VacancyMatch


@dataclass
class RelevantVacancyRecord:
    vacancy_id: str
    vacancy_name: str
    vacancy_url: str | None
    published_at: str | None
    salary_from: int | None
    salary_to: int | None
    currency: str | None
    schedule: str | None
    employment: str | None
    experience: str | None
    matched_terms: list[str]
    match_reason: str
    relevance_score: float


@dataclass
class EmployerRecord:
    snapshot_at: str
    employer_id: int
    employer_name: str
    employer_type: str
    employer_type_confidence: float
    classification_reason: str
    employer_hh_url: str | None
    employer_site_url: str | None
    area_id: int | None
    area_name: str | None
    industry: str | None
    total_open_vacancies: int
    relevant_open_vacancies: int
    relevant_vacancies: list[RelevantVacancyRecord] = field(default_factory=list)

    @property
    def relevant_vacancy_titles(self) -> list[str]:
        return [v.vacancy_name for v in self.relevant_vacancies]

    @property
    def relevant_vacancy_urls(self) -> list[str]:
        return [v.vacancy_url or "" for v in self.relevant_vacancies]

    @property
    def latest_relevant_vacancy_date(self) -> str | None:
        dates = [v.published_at for v in self.relevant_vacancies if v.published_at]
        return max(dates) if dates else None

    @property
    def oldest_current_relevant_vacancy_date(self) -> str | None:
        dates = [v.published_at for v in self.relevant_vacancies if v.published_at]
        return min(dates) if dates else None

    @property
    def days_since_latest(self) -> int | None:
        latest = self.latest_relevant_vacancy_date
        if not latest:
            return None
        try:
            dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).days
        except (ValueError, TypeError):
            return None


@dataclass
class SignalMetrics:
    active_relevant_count: int = 0
    days_since_latest: int | None = None
    unique_relevant_roles: int = 0
    fresh_signal: bool = False
    repeat_signal: bool = False
    multi_role_signal: bool = False
    research_signal_score: float = 0.0

    @property
    def score_explanation(self) -> str:
        parts = []
        if self.fresh_signal:
            parts.append("fresh(+2)")
        if self.multi_role_signal:
            parts.append("multi-role(+3)")
        if self.active_relevant_count > 1:
            parts.append(f"multi-vacancy(+{self.active_relevant_count - 1})")
        if self.repeat_signal:
            parts.append("repeat(+1)")
        return ", ".join(parts) if parts else "no signals"


def compute_signal_metrics(
    record: EmployerRecord,
    historical_relevant_count: int = 0,
) -> SignalMetrics:
    m = SignalMetrics()
    m.active_relevant_count = record.relevant_open_vacancies
    m.days_since_latest = record.days_since_latest

    unique_roles = set()
    for v in record.relevant_vacancies:
        unique_roles.add(v.vacancy_name.strip().lower())
    m.unique_relevant_roles = len(unique_roles)

    if m.days_since_latest is not None and m.days_since_latest <= 7:
        m.fresh_signal = True
    if m.active_relevant_count > 1:
        m.multi_role_signal = True
    if historical_relevant_count > 0 and record.relevant_open_vacancies > 0:
        m.repeat_signal = True

    score = 0.0
    if m.fresh_signal:
        score += 2.0
    if m.multi_role_signal:
        score += 3.0
    if m.active_relevant_count > 1:
        score += m.active_relevant_count - 1
    if m.repeat_signal:
        score += 1.0
    m.research_signal_score = score

    return m


def build_employer_record(
    snapshot_at: str,
    employer_id: int,
    employer_name: str,
    classification: ClassificationResult,
    employer_url: str | None,
    area_id: int | None,
    area_name: str | None,
    industry: str | None,
    total_vacancies: int,
    relevant_vacancy_data: list[tuple[dict, VacancyMatch]],
) -> EmployerRecord:
    rec = EmployerRecord(
        snapshot_at=snapshot_at,
        employer_id=employer_id,
        employer_name=employer_name,
        employer_type=classification.employer_type.value,
        employer_type_confidence=classification.confidence,
        classification_reason=classification.reason,
        employer_hh_url=employer_url,
        employer_site_url=None,
        area_id=area_id,
        area_name=area_name,
        industry=industry,
        total_open_vacancies=total_vacancies,
        relevant_open_vacancies=len(relevant_vacancy_data),
    )
    for vac, match in relevant_vacancy_data:
        salary = vac.get("salary") or {}
        rec.relevant_vacancies.append(RelevantVacancyRecord(
            vacancy_id=str(vac.get("id", "")),
            vacancy_name=vac.get("name", ""),
            vacancy_url=vac.get("url") or vac.get("alternate_url"),
            published_at=vac.get("published_at"),
            salary_from=salary.get("from"),
            salary_to=salary.get("to"),
            currency=salary.get("currency"),
            schedule=(vac.get("schedule") or {}).get("name"),
            employment=(vac.get("employment") or {}).get("name"),
            experience=(vac.get("experience") or {}).get("name"),
            matched_terms=match.matched_terms,
            match_reason=match.match_reason,
            relevance_score=match.relevance_score,
        ))
    return rec
