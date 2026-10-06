"""Extract contacts from HH employer profile (description, site_url)."""

from __future__ import annotations

import logging
import re
import time

from .base import ContactData, EnrichmentResult, EnrichmentSource
from ...api_client import HHApiClient

logger = logging.getLogger(__name__)


class HHEmployerSource(EnrichmentSource):
    @property
    def name(self) -> str:
        return "hh_employer"

    @property
    def priority(self) -> int:
        return 1

    def __init__(self, api_client: HHApiClient):
        self._api = api_client

    def fetch(self, employer: dict) -> EnrichmentResult:
        start = time.monotonic()
        result = EnrichmentResult(
            employer_id=employer["id"], source_name=self.name,
        )
        try:
            data = self._api.get_employer(employer["id"])

            site_url = data.get("site_url")
            if site_url:
                result.contacts.append(ContactData(
                    contact_type="website",
                    value=site_url,
                    source_url=f"https://hh.ru/employer/{employer['id']}",
                    source_type="hh_profile",
                    confidence=0.95,
                ))

            description = data.get("description") or ""
            if description:
                for phone in self._extract_phones(description):
                    result.contacts.append(ContactData(
                        contact_type="phone",
                        value=phone,
                        source_url=f"https://hh.ru/employer/{employer['id']}",
                        source_type="hh_profile",
                        confidence=0.60,
                    ))
                for email in self._extract_emails(description):
                    result.contacts.append(ContactData(
                        contact_type="email",
                        value=email,
                        source_url=f"https://hh.ru/employer/{employer['id']}",
                        source_type="hh_profile",
                        confidence=0.60,
                    ))
        except Exception as e:
            result.success = False
            result.error = str(e)

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    @staticmethod
    def _extract_phones(text: str) -> list[str]:
        patterns = [
            r"\+7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
            r"\+7\d{10}",
        ]
        found: set[str] = set()
        for pattern in patterns:
            for match in re.findall(pattern, text):
                clean = re.sub(r"[^\d+]", "", match)
                if len(clean) >= 11:
                    found.add(clean)
        return list(found)

    @staticmethod
    def _extract_emails(text: str) -> list[str]:
        pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
        return list(set(re.findall(pattern, text)))
