"""Vacancy relevance detection with false-positive control."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .config import FalsePositiveConfig


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str):
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html(html: str) -> str:
    if not html:
        return ""
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


@dataclass
class VacancyMatch:
    is_relevant: bool
    relevance_score: float
    matched_terms: list[str] = field(default_factory=list)
    match_reason: str = ""
    excluded_by: str = ""


def _vacancy_text(vacancy: dict) -> str:
    parts = [vacancy.get("name", "")]
    desc = vacancy.get("description") or ""
    parts.append(strip_html(desc))
    code = vacancy.get("code") or ""
    if code:
        parts.append(code)
    prof = vacancy.get("professional_roles") or []
    for r in prof:
        parts.append(r.get("name", ""))
    return " ".join(parts).lower()


def _score_vacancy(text: str, terms: list[str]) -> tuple[float, list[str]]:
    matched = []
    score = 0.0
    for term in terms:
        t = term.lower()
        if t in text:
            matched.append(term)
            score += 1.0
            if len(t) > 15:
                score += 0.5
    if not matched:
        return 0.0, []
    norm = min(score / max(len(terms) * 0.3, 1), 1.0)
    return norm, matched


def _check_false_positive(text: str, exclude_terms: list[str]) -> str:
    for ex in exclude_terms:
        if ex.lower() in text:
            return ex
    return ""


def evaluate_vacancy(
    vacancy: dict,
    terms: list[str],
    fp_config: FalsePositiveConfig,
) -> VacancyMatch:
    text = _vacancy_text(vacancy)
    if not text.strip():
        return VacancyMatch(False, 0.0, match_reason="Empty vacancy text")

    excluded = _check_false_positive(text, fp_config.exclude_terms)
    if excluded:
        return VacancyMatch(
            False, 0.0,
            match_reason=f"Excluded by false-positive term: {excluded!r}",
            excluded_by=excluded,
        )

    score, matched = _score_vacancy(text, terms)
    if not matched:
        return VacancyMatch(False, score, match_reason="No matching terms")

    if score < fp_config.threshold:
        return VacancyMatch(
            False, score,
            matched_terms=matched,
            match_reason=f"Score {score:.2f} below threshold {fp_config.threshold}",
        )

    return VacancyMatch(
        True, score,
        matched_terms=matched,
        match_reason=f"Matched {len(matched)} term(s): {', '.join(matched[:5])}",
    )
