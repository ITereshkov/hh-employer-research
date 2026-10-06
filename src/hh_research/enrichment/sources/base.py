"""Base types for enrichment sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ContactData:
    contact_type: str
    value: str
    source_url: str
    source_type: str
    confidence: float
    is_facility: bool = False


@dataclass
class EnrichmentResult:
    employer_id: int
    contacts: list[ContactData] = field(default_factory=list)
    source_name: str = ""
    success: bool = True
    error: str | None = None
    duration_ms: float = 0.0


class EnrichmentSource(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        ...

    @abstractmethod
    def fetch(self, employer: dict) -> EnrichmentResult:
        ...

    def can_handle(self, employer: dict) -> bool:
        return True
