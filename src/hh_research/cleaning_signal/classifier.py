"""Role classification, false-positive control, employer categorization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from html.parser import HTMLParser

from .config import CleaningProviderConfig, ExclusionConfig, QueryTaxonomy


class RoleCategory(str, Enum):
    INDOOR_CLEANING = "INDOOR_CLEANING"
    JANITORIAL = "JANITORIAL"
    FACILITY_MAINTENANCE = "FACILITY_MAINTENANCE"
    MIXED_CLEANING_MAINTENANCE = "MIXED_CLEANING_MAINTENANCE"
    OTHER_RELEVANT = "OTHER_RELEVANT"
    REJECTED = "REJECTED"


class EmployerCategory(str, Enum):
    EDUCATION = "EDUCATION"
    HEALTHCARE = "HEALTHCARE"
    RETAIL = "RETAIL"
    WAREHOUSE_LOGISTICS = "WAREHOUSE_LOGISTICS"
    SHOPPING_CENTER = "SHOPPING_CENTER"
    BUSINESS_CENTER = "BUSINESS_CENTER"
    HOSPITALITY = "HOSPITALITY"
    MANUFACTURING = "MANUFACTURING"
    FITNESS = "FITNESS"
    PUBLIC_SECTOR = "PUBLIC_SECTOR"
    FACILITY_MANAGEMENT = "FACILITY_MANAGEMENT"
    CLEANING_COMPANY = "CLEANING_COMPANY"
    OTHER = "OTHER"


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
class RoleClassification:
    role_category: RoleCategory
    relevance_score: float
    matched_terms: list[str] = field(default_factory=list)
    match_reason: str = ""
    excluded_by: str = ""
    is_relevant: bool = False


@dataclass
class EmployerCategoryResult:
    category: EmployerCategory
    confidence: float
    reason: str
    is_cleaning_provider: bool = False


_CLEANING_TITLE_PATTERNS: list[tuple[list[str], RoleCategory]] = [
    (["уборщик помещений", "уборщица помещений", "уборщик служебных"],
     RoleCategory.INDOOR_CLEANING),
    (["уборщик производственных", "уборщик производственных и служебных"],
     RoleCategory.INDOOR_CLEANING),
    (["уборщик", "уборщица", "уборка помещений"],
     RoleCategory.INDOOR_CLEANING),
    (["дворник"],
     RoleCategory.JANITORIAL),
    (["рабочий по комплексному обслуживанию и ремонту",
      "рабочий по комплексному обслуживанию зданий",
      "рабочий по комплексному обслуживанию"],
     RoleCategory.FACILITY_MAINTENANCE),
    (["рабочий по эксплуатации зданий", "рабочий по обслуживанию здания"],
     RoleCategory.FACILITY_MAINTENANCE),
    (["хозяйственный рабочий"],
     RoleCategory.MIXED_CLEANING_MAINTENANCE),
    (["технический работник"],
     RoleCategory.OTHER_RELEVANT),
]

_EXCLUSION_PATTERNS: list[str] = [
    "кухонный",
    "складской", "склада",
    "грузчик",
    "санитар", "санитарк",
    "горничн",
    "мойщик посуд",
    "автомойщик", "мойщик автомобил",
    "комплектовщик",
    "кладовщик",
    "разнорабочий",
    "подсобный рабочий на производств",
    "оператор производств",
    "оператор станк",
    "медицинск сестр",
    "врач",
    "преподавател", "учител",
    "торгов представитель",
    "продавец",
    "повар", "кондитер",
]

_EMPLOYER_CATEGORY_RULES: list[tuple[list[str], EmployerCategory, float]] = [
    (["школа", "сош", "мбоу", "гбоу", "гимнази", "лицей",
      "образовательн", "колледж", "техникум", "университет",
      "дошк", "детск", "воспитат"],
     EmployerCategory.EDUCATION, 0.85),
    (["больница", "гкб", "гбуз", "поликлиник", "клиник",
      "медицинск", "здравоохран", "стационар", "роддом"],
     EmployerCategory.HEALTHCARE, 0.85),
    (["магазин", "торгов", "ритейл", "retail", "супермаркет",
      "гипермаркет", "продукт"],
     EmployerCategory.RETAIL, 0.75),
    (["склад", "логистик", "warehouse", "фулфилмент"],
     EmployerCategory.WAREHOUSE_LOGISTICS, 0.8),
    (["торгов центр", "тц ", "тц.", "shopping", "mall",
      "торгово-развлекательн"],
     EmployerCategory.SHOPPING_CENTER, 0.85),
    (["бизнес-центр", "бц ", "бц.", "business center",
      "офисн центр", "офисный центр"],
     EmployerCategory.BUSINESS_CENTER, 0.85),
    (["гостиниц", "отел", "hotel", "хостел", "санатори"],
     EmployerCategory.HOSPITALITY, 0.8),
    (["завод", "производств", "фабрик", "manufactur", "промышленн",
      "цех"],
     EmployerCategory.MANUFACTURING, 0.75),
    (["фитнес", "спорт", "fitness", "gym", "спортзал", "бассейн"],
     EmployerCategory.FITNESS, 0.8),
    (["управляющ компан", "ук ", "мфоу", "жилищн", "коммунальн",
      "государственн", "администраци", "муниципальн", "управа",
      "департамент", "министерств"],
     EmployerCategory.PUBLIC_SECTOR, 0.7),
    (["facility management", "facility services",
      "обслуживани здани", "управление объектам",
      "эксплуатац здани"],
     EmployerCategory.FACILITY_MANAGEMENT, 0.85),
]

_CLEANING_PROVIDER_NAME_KW = [
    "клининг", "cleaning", "клинингов", "клининго",
    "профессиональн уборк", "сервис уборки", "сервис клинин",
    "чистота сервис", "чистый дом", "чистый город",
    "facility management", "facility services",
]

_CLEANING_PROVIDER_INDUSTRY_KW = [
    "клининг", "cleaning", "уборка",
    "facility management", "facility services",
]


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


def classify_role(
    vacancy: dict,
    taxonomy: QueryTaxonomy,
    exclusions: ExclusionConfig,
) -> RoleClassification:
    text = _vacancy_text(vacancy)
    name_lower = (vacancy.get("name") or "").lower()

    if not text.strip():
        return RoleClassification(
            RoleCategory.REJECTED, 0.0,
            match_reason="Empty vacancy text",
        )

    for ex_term in exclusions.terms:
        if ex_term.lower() in text:
            return RoleClassification(
                RoleCategory.REJECTED, 0.0,
                match_reason=f"Excluded by term: {ex_term!r}",
                excluded_by=ex_term,
            )

    for ex_pat in _EXCLUSION_PATTERNS:
        if ex_pat in text:
            title_has_clean = any(
                t.lower() in name_lower
                for t in taxonomy.cleaning + taxonomy.facility + taxonomy.janitorial
            )
            if not title_has_clean:
                return RoleClassification(
                    RoleCategory.REJECTED, 0.0,
                    match_reason=f"Excluded by pattern: {ex_pat!r}",
                    excluded_by=ex_pat,
                )

    matched_terms: list[str] = []
    matched_categories: set[RoleCategory] = set()
    score = 0.0

    for patterns, category in _CLEANING_TITLE_PATTERNS:
        for pat in patterns:
            if pat in text:
                matched_categories.add(category)
                matched_terms.append(pat)
                score += 1.0
                if len(pat) > 15:
                    score += 0.5

    if not matched_categories:
        for term in taxonomy.all_terms:
            if term.lower() in text:
                matched_terms.append(term)
                score += 0.5

    if not matched_terms:
        return RoleClassification(
            RoleCategory.REJECTED, 0.0,
            match_reason="No matching terms",
        )

    if len(matched_categories) > 1:
        final_category = RoleCategory.MIXED_CLEANING_MAINTENANCE
    elif len(matched_categories) == 1:
        final_category = matched_categories.pop()
    else:
        final_category = RoleCategory.OTHER_RELEVANT

    norm_score = min(score / max(len(taxonomy.all_terms) * 0.15, 1), 1.0)

    return RoleClassification(
        role_category=final_category,
        relevance_score=norm_score,
        matched_terms=list(dict.fromkeys(matched_terms)),
        match_reason=f"Matched {len(matched_terms)} term(s): {', '.join(matched_terms[:5])}",
        is_relevant=True,
    )


def classify_employer_category(
    employer_name: str,
    employer_industry: str | None = None,
    employer_description: str | None = None,
    cleaning_provider_config: CleaningProviderConfig | None = None,
) -> EmployerCategoryResult:
    parts = [employer_name or ""]
    if employer_industry:
        parts.append(employer_industry)
    if employer_description:
        parts.append(employer_description)
    text = " ".join(parts).lower()

    cp_config = cleaning_provider_config or CleaningProviderConfig()

    for kw in cp_config.name_keywords:
        if kw.lower() in (employer_name or "").lower():
            return EmployerCategoryResult(
                category=EmployerCategory.CLEANING_COMPANY,
                confidence=0.9,
                reason=f"Name contains cleaning-provider keyword: {kw!r}",
                is_cleaning_provider=True,
            )

    for kw in cp_config.industry_keywords:
        if kw.lower() in (employer_industry or "").lower():
            return EmployerCategoryResult(
                category=EmployerCategory.CLEANING_COMPANY,
                confidence=0.85,
                reason=f"Industry contains cleaning-provider keyword: {kw!r}",
                is_cleaning_provider=True,
            )

    for keywords, category, confidence in _EMPLOYER_CATEGORY_RULES:
        for kw in keywords:
            if kw in text:
                return EmployerCategoryResult(
                    category=category,
                    confidence=confidence,
                    reason=f"Keyword {kw!r} matched → {category.value}",
                )

    return EmployerCategoryResult(
        category=EmployerCategory.OTHER,
        confidence=0.3,
        reason="No matching patterns",
    )
