"""Configuration loader for research.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "research.yaml"


@dataclass
class AreasConfig:
    ids: list[int] = field(default_factory=lambda: [1])

    @classmethod
    def from_dict(cls, data: Any) -> AreasConfig:
        if data is None:
            return cls()
        if isinstance(data, list):
            return cls(ids=[int(a) for a in data])
        if isinstance(data, dict):
            return cls(ids=[int(a) for a in data.get("ids", [1])])
        return cls()


@dataclass
class EmployerCategoriesConfig:
    school: list[str] = field(default_factory=list)
    hospital: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> EmployerCategoriesConfig:
        if not data:
            return cls(
                school=[
                    "школа", "СОШ", "МБОУ", "ГБОУ", "гимназия", "лицей",
                    "образовательный комплекс", "общеобразовательная",
                    "колледж", "техникум",
                ],
                hospital=[
                    "больница", "городская больница", "клиническая больница",
                    "ГКБ", "ГБУЗ", "поликлиника", "городская поликлиника",
                    "медицинский центр", "диагностический центр",
                    "роддом", "родильный дом",
                ],
            )
        return cls(
            school=data.get("school", []),
            hospital=data.get("hospital", []),
        )


@dataclass
class VacancyCategoriesConfig:
    cleaning: list[str] = field(default_factory=list)
    facility_maintenance: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> VacancyCategoriesConfig:
        if not data:
            return cls(
                cleaning=[
                    "уборщик", "уборщица", "уборщик помещений",
                    "уборщик служебных помещений",
                    "уборщик производственных и служебных помещений",
                    "уборка помещений",
                ],
                facility_maintenance=[
                    "дворник", "рабочий по комплексному обслуживанию",
                    "рабочий по комплексному обслуживанию зданий",
                    "рабочий по комплексному обслуживанию и ремонту зданий",
                    "рабочий по обслуживанию здания",
                    "технический работник", "подсобный рабочий",
                    "хозяйственный рабочий",
                ],
            )
        return cls(
            cleaning=data.get("cleaning", []),
            facility_maintenance=data.get("facility_maintenance", []),
        )


@dataclass
class FalsePositiveConfig:
    exclude_terms: list[str] = field(default_factory=list)
    threshold: float = 0.2

    @classmethod
    def from_dict(cls, data: Any) -> FalsePositiveConfig:
        if not data:
            return cls(
                exclude_terms=[
                    "кухонный рабочий", "медицинская сестра", "лаборант",
                    "врач", "преподаватель", "учитель", "оператор",
                    "складской рабочий", "грузчик", "комплектовщик",
                    "разнорабочий", "торговый представитель",
                ],
                threshold=0.2,
            )
        return cls(
            exclude_terms=data.get("exclude_terms", []),
            threshold=float(data.get("threshold", 0.2)),
        )


@dataclass
class ApiConfig:
    base_url: str = "https://api.hh.ru"
    per_page: int = 100
    max_pages: int = 20
    delay: float = 0.3
    timeout: int = 30
    max_retries: int = 3
    user_agent: str = "HHResearchBot/1.0 (ivan-research@mail.ru)"

    @classmethod
    def from_dict(cls, data: Any) -> ApiConfig:
        if not data:
            return cls()
        return cls(
            base_url=data.get("base_url", "https://api.hh.ru"),
            per_page=int(data.get("per_page", 100)),
            max_pages=int(data.get("max_pages", 20)),
            delay=float(data.get("delay", 0.3)),
            timeout=int(data.get("timeout", 30)),
            max_retries=int(data.get("max_retries", 3)),
            user_agent=data.get("user_agent", "HH-Employer-Research/0.1.0 (research@example.com)"),
        )


@dataclass
class StorageConfig:
    db_path: str = "data/research.db"
    cache_dir: str = "data/cache"
    cache_ttl_hours: int = 6

    @classmethod
    def from_dict(cls, data: Any) -> StorageConfig:
        if not data:
            return cls()
        return cls(
            db_path=data.get("db_path", "data/research.db"),
            cache_dir=data.get("cache_dir", "data/cache"),
            cache_ttl_hours=int(data.get("cache_ttl_hours", 6)),
        )


@dataclass
class ResearchConfig:
    areas: AreasConfig
    employer_categories: EmployerCategoriesConfig
    vacancy_categories: VacancyCategoriesConfig
    false_positives: FalsePositiveConfig
    api: ApiConfig
    storage: StorageConfig
    export_dir: str = "exports"

    @classmethod
    def from_dict(cls, data: dict) -> ResearchConfig:
        return cls(
            areas=AreasConfig.from_dict(data.get("areas")),
            employer_categories=EmployerCategoriesConfig.from_dict(
                data.get("employer_categories")
            ),
            vacancy_categories=VacancyCategoriesConfig.from_dict(
                data.get("vacancy_categories")
            ),
            false_positives=FalsePositiveConfig.from_dict(
                data.get("false_positives")
            ),
            api=ApiConfig.from_dict(data.get("api")),
            storage=StorageConfig.from_dict(data.get("storage")),
            export_dir=data.get("export_dir", "exports"),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> ResearchConfig:
        path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls.from_dict({})
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @property
    def all_employer_terms(self) -> list[str]:
        terms = []
        terms.extend(self.employer_categories.school)
        terms.extend(self.employer_categories.hospital)
        return terms

    @property
    def all_vacancy_terms(self) -> list[str]:
        terms = []
        terms.extend(self.vacancy_categories.cleaning)
        terms.extend(self.vacancy_categories.facility_maintenance)
        return terms
