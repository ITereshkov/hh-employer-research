import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .sources.base import ContactData


@dataclass
class ResolvedContact:
    contact_type: str
    value: str
    confidence: float
    source_url: str
    source_type: str
    is_primary: bool
    is_facility: bool = False


class ContactResolver:
    def resolve(self, contacts: list[ContactData]) -> list[ResolvedContact]:
        grouped: dict[str, list[ContactData]] = {}
        for c in contacts:
            grouped.setdefault(c.contact_type, []).append(c)

        resolved = []
        for ctype, items in grouped.items():
            deduped = self._deduplicate(items)
            deduped.sort(key=lambda c: c.confidence, reverse=True)
            for i, c in enumerate(deduped):
                resolved.append(
                    ResolvedContact(
                        contact_type=c.contact_type,
                        value=c.value,
                        confidence=c.confidence,
                        source_url=c.source_url,
                        source_type=c.source_type,
                        is_primary=(i == 0),
                        is_facility=c.is_facility,
                    )
                )
        return resolved

    def _deduplicate(self, contacts: list[ContactData]) -> list[ContactData]:
        seen: dict[str, ContactData] = {}
        for c in contacts:
            key = self._normalize(c.contact_type, c.value)
            if key not in seen or c.confidence > seen[key].confidence:
                seen[key] = c
        return list(seen.values())

    def _normalize(self, contact_type: str, value: str) -> str:
        if contact_type == "phone":
            return self._normalize_phone(value)
        elif contact_type == "email":
            return self._normalize_email(value)
        elif contact_type == "website":
            return self._normalize_url(value)
        return value.strip().lower()

    def _normalize_phone(self, phone: str) -> str:
        digits = re.sub(r"[^\d+]", "", phone)
        if digits.startswith("8") and len(digits) == 11:
            digits = "+7" + digits[1:]
        elif digits.startswith("7") and len(digits) == 11:
            digits = "+" + digits
        return digits

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        host = re.sub(r"^www\.", "", host)
        path = parsed.path.rstrip("/")
        return f"{host}{path}".lower()

    def compute_signal_score(self, employer: dict, contacts: list[ResolvedContact]) -> float:
        score = 0.0

        vacancy_count = employer.get("vacancy_count", 0)
        if vacancy_count >= 3:
            score += 0.25
        elif vacancy_count >= 2:
            score += 0.15
        elif vacancy_count >= 1:
            score += 0.10

        contact_types = {c.contact_type for c in contacts}
        if "website" in contact_types:
            score += 0.15
        if "phone" in contact_types:
            score += 0.15
        if "email" in contact_types:
            score += 0.10
        if "address" in contact_types:
            score += 0.05

        has_facility = any(c.is_facility for c in contacts) if contacts else False
        if has_facility:
            score += 0.25

        if employer.get("description"):
            score += 0.05

        return min(score, 1.0)
