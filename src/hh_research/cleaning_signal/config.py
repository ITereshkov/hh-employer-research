"""Configuration for cleaning-hiring-signal mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..config import ApiConfig, StorageConfig


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "config" / "cleaning-signal.yaml"
)


@dataclass
class QueryTaxonomy:
    cleaning: list[str] = field(default_factory=lambda: [
        "уборщик",
        "уборщица",
        "уборщик помещений",
        "уборщик служебных помещений",
        "уборщик производственных помещений",
        "уборщик производственных и служебных помещений",
        "уборка помещений",
    ])
    facility: list[str] = field(default_factory=lambda: [
        "рабочий по комплексному обслуживанию",
        "рабочий по комплексному обслуживанию зданий",
        "рабочий по комплексному обслуживанию и ремонту зданий",
        "рабочий по обслуживанию здания",
        "рабочий по эксплуатации зданий",
        "технический работник",
        "хозяйственный рабочий",
    ])
    janitorial: list[str] = field(default_factory=lambda: [
        "дворник",
    ])

    @classmethod
    def from_dict(cls, data: Any) -> QueryTaxonomy:
        if not data:
            return cls()
        return cls(
            cleaning=data.get("cleaning", cls().cleaning),
            facility=data.get("facility", cls().facility),
            janitorial=data.get("janitorial", cls().janitorial),
        )

    @property
    def all_terms(self) -> list[str]:
        return self.cleaning + self.facility + self.janitorial


@dataclass
class ExclusionConfig:
    terms: list[str] = field(default_factory=lambda: [
        "кухонный рабочий",
        "подсобный рабочий на производство",
        "складской рабочий",
        "рабочий склада",
        "грузчик",
        "санитар",
        "санитарка",
        "горничная",
        "мойщик посуды",
        "автомойщик",
        "мойщик автомобилей",
        "комплектовщик",
        "кладовщик",
        "разнорабочий",
        "оператор",
        "медицинская сестра",
        "врач",
        "преподаватель",
        "учитель",
        "торговый представитель",
        "продавец",
        "повар",
        "кондитер",
    ])
    threshold: float = 0.2

    @classmethod
    def from_dict(cls, data: Any) -> ExclusionConfig:
        if not data:
            return cls()
        return cls(
            terms=data.get("terms", cls().terms),
            threshold=float(data.get("threshold", 0.2)),
        )


@dataclass
class ScoringConfig:
    weight_per_vacancy: float = 1.0
    weight_fresh_7d: float = 2.0
    weight_fresh_30d: float = 1.0
    weight_unique_role: float = 1.5
    weight_unique_location: float = 1.5
    weight_multi_location: float = 3.0
    weight_repeat_signal: float = 2.0
    threshold_high: float = 8.0
    threshold_medium: float = 4.0

    @classmethod
    def from_dict(cls, data: Any) -> ScoringConfig:
        if not data:
            return cls()
        return cls(
            weight_per_vacancy=float(data.get("weight_per_vacancy", 1.0)),
            weight_fresh_7d=float(data.get("weight_fresh_7d", 2.0)),
            weight_fresh_30d=float(data.get("weight_fresh_30d", 1.0)),
            weight_unique_role=float(data.get("weight_unique_role", 1.5)),
            weight_unique_location=float(data.get("weight_unique_location", 1.5)),
            weight_multi_location=float(data.get("weight_multi_location", 3.0)),
            weight_repeat_signal=float(data.get("weight_repeat_signal", 2.0)),
            threshold_high=float(data.get("threshold_high", 8.0)),
            threshold_medium=float(data.get("threshold_medium", 4.0)),
        )


@dataclass
class EnrichmentCohortConfig:
    min_signal_score: float = 0.0
    signal_levels: list[str] = field(default_factory=lambda: ["HIGH"])
    max_employers: int = 50
    include_top_medium: int = 0

    @classmethod
    def from_dict(cls, data: Any) -> EnrichmentCohortConfig:
        if not data:
            return cls()
        return cls(
            min_signal_score=float(data.get("min_signal_score", 0.0)),
            signal_levels=data.get("signal_levels", ["HIGH"]),
            max_employers=int(data.get("max_employers", 50)),
            include_top_medium=int(data.get("include_top_medium", 0)),
        )


@dataclass
class CleaningProviderConfig:
    name_keywords: list[str] = field(default_factory=lambda: [
        "клининг", "cleaning", "клининговая", "клининго",
        "уборка профессиональная", "профессиональная уборка",
        "сервис уборки", "сервис клинин",
        "чистый", "чистота сервис",
        "facility management", "facility services",
        "обслуживание зданий", "управление объектами",
    ])
    industry_keywords: list[str] = field(default_factory=lambda: [
        "клининг", "cleaning", "уборка",
        "facility management", "facility services",
        "обслуживание зданий",
    ])

    @classmethod
    def from_dict(cls, data: Any) -> CleaningProviderConfig:
        if not data:
            return cls()
        return cls(
            name_keywords=data.get("name_keywords", cls().name_keywords),
            industry_keywords=data.get("industry_keywords", cls().industry_keywords),
        )


@dataclass
class DiscoveryConfig:
    areas: list[int] = field(default_factory=lambda: [1])
    per_page: int = 100
    max_pages_per_query: int = 20
    max_total_vacancies: int = 5000
    delay: float = 0.3

    @classmethod
    def from_dict(cls, data: Any) -> DiscoveryConfig:
        if not data:
            return cls()
        return cls(
            areas=data.get("areas", [1]),
            per_page=int(data.get("per_page", 100)),
            max_pages_per_query=int(data.get("max_pages_per_query", 20)),
            max_total_vacancies=int(data.get("max_total_vacancies", 5000)),
            delay=float(data.get("delay", 0.3)),
        )


@dataclass
class CleaningSignalConfig:
    discovery: DiscoveryConfig
    query_taxonomy: QueryTaxonomy
    exclusions: ExclusionConfig
    scoring: ScoringConfig
    enrichment_cohort: EnrichmentCohortConfig
    cleaning_provider: CleaningProviderConfig
    api: ApiConfig
    storage: StorageConfig
    export_dir: str = "exports"

    @classmethod
    def from_dict(cls, data: dict) -> CleaningSignalConfig:
        return cls(
            discovery=DiscoveryConfig.from_dict(data.get("discovery")),
            query_taxonomy=QueryTaxonomy.from_dict(data.get("query_taxonomy")),
            exclusions=ExclusionConfig.from_dict(data.get("exclusions")),
            scoring=ScoringConfig.from_dict(data.get("scoring")),
            enrichment_cohort=EnrichmentCohortConfig.from_dict(data.get("enrichment_cohort")),
            cleaning_provider=CleaningProviderConfig.from_dict(data.get("cleaning_provider")),
            api=ApiConfig.from_dict(data.get("api")),
            storage=StorageConfig.from_dict(data.get("storage")),
            export_dir=data.get("export_dir", "exports"),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> CleaningSignalConfig:
        path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls.from_dict({})
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)
