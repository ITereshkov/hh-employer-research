from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


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
    error: Optional[str] = None
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
    async def fetch(self, employer: dict) -> EnrichmentResult:
        ...

    def can_handle(self, employer: dict) -> bool:
        return True
