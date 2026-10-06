"""Deterministic employer classifier with confidence and reason."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .employer_discovery import DiscoveredEmployer


class EmployerType(str, Enum):
    SCHOOL = "SCHOOL"
    GYMNASIUM_LYCEUM = "GYMNASIUM_LYCEUM"
    COLLEGE = "COLLEGE"
    HOSPITAL = "HOSPITAL"
    POLYCLINIC = "POLYCLINIC"
    MEDICAL_CENTER = "MEDICAL_CENTER"
    MATERNITY = "MATERNITY"
    OTHER_MEDICAL = "OTHER_MEDICAL"
    OTHER_EDUCATION = "OTHER_EDUCATION"
    UNKNOWN = "UNKNOWN"


@dataclass
class ClassificationResult:
    employer_type: EmployerType
    confidence: float
    reason: str


_RULES: list[tuple[list[str], EmployerType, float]] = [
    (["роддом", "родильн"], EmployerType.MATERNITY, 0.95),
    (["гимнази"], EmployerType.GYMNASIUM_LYCEUM, 0.95),
    (["лицей"], EmployerType.GYMNASIUM_LYCEUM, 0.9),
    (["школа", "сош", "общеобразовательн"], EmployerType.SCHOOL, 0.9),
    (["колледж"], EmployerType.COLLEGE, 0.9),
    (["техникум"], EmployerType.COLLEGE, 0.85),
    (["гкб", "городская больница", "клиническая больница", "стационар"], EmployerType.HOSPITAL, 0.95),
    (["больница"], EmployerType.HOSPITAL, 0.85),
    (["поликлиника"], EmployerType.POLYCLINIC, 0.9),
    (["диагностическ", "медицинск", "медуслуг"], EmployerType.MEDICAL_CENTER, 0.8),
    (["образовательн"], EmployerType.OTHER_EDUCATION, 0.7),
]

_MEDICAL_HINTS = [
    "медицин", "здравоохран", "клиник", "лечебн", "терапевт",
    "хирург", "гбуз", "мбу", "ниим", "медцент",
]

_EDUCATION_HINTS = [
    "образован", "обучен", "учебн", "педагог", "мбоу", "гбоу",
    "дошк", "детск", "воспитат",
]


def _text_for(employer: DiscoveredEmployer) -> str:
    parts = [employer.name or ""]
    if employer.description:
        parts.append(employer.description)
    if employer.industry:
        parts.append(employer.industry)
    return " ".join(parts).lower()


def classify_employer(employer: DiscoveredEmployer) -> ClassificationResult:
    text = _text_for(employer)
    if not text.strip():
        return ClassificationResult(EmployerType.UNKNOWN, 0.0, "No text data")

    for keywords, etype, confidence in _RULES:
        for kw in keywords:
            if kw in text:
                return ClassificationResult(
                    etype, confidence,
                    f"Keyword {kw!r} matched → {etype.value}",
                )

    medical_score = sum(1 for h in _MEDICAL_HINTS if h in text)
    education_score = sum(1 for h in _EDUCATION_HINTS if h in text)

    if medical_score >= 2:
        return ClassificationResult(
            EmployerType.OTHER_MEDICAL, 0.6,
            f"Multiple medical hints ({medical_score}) detected",
        )
    if education_score >= 2:
        return ClassificationResult(
            EmployerType.OTHER_EDUCATION, 0.6,
            f"Multiple education hints ({education_score}) detected",
        )
    if medical_score == 1:
        return ClassificationResult(
            EmployerType.OTHER_MEDICAL, 0.4,
            "Single medical hint — low confidence",
        )
    if education_score == 1:
        return ClassificationResult(
            EmployerType.OTHER_EDUCATION, 0.4,
            "Single education hint — low confidence",
        )

    return ClassificationResult(EmployerType.UNKNOWN, 0.0, "No matching patterns")


def is_target_employer(result: ClassificationResult) -> bool:
    return result.employer_type != EmployerType.UNKNOWN and result.confidence >= 0.5
