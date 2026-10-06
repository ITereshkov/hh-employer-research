"""Scrape public contacts from employer official websites."""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urljoin

import requests

from .base import ContactData, EnrichmentResult, EnrichmentSource

logger = logging.getLogger(__name__)

CONTACT_PAGE_PATTERNS = [
    "/contacts",
    "/contact",
    "/about/contacts",
    "/kontakty",
    "/o-kompanii/kontakty",
    "/about",
]

FACILITY_KEYWORDS = [
    "ахо",
    "административно-хозяйствен",
    "хозяйственн",
    "эксплуатац",
    "facility",
    "главный инженер",
    "техническ",
]


class WebsiteSource(EnrichmentSource):
    @property
    def name(self) -> str:
        return "website"

    @property
    def priority(self) -> int:
        return 2

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; HHResearchBot/1.0)",
        })

    def fetch(self, employer: dict) -> EnrichmentResult:
        start = time.monotonic()
        result = EnrichmentResult(
            employer_id=employer["id"], source_name=self.name,
        )

        website = employer.get("official_website") or employer.get("site_url")
        if not website:
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        if not website.startswith("http"):
            website = "https://" + website

        try:
            pages_to_check = [website]
            for pattern in CONTACT_PAGE_PATTERNS:
                pages_to_check.append(urljoin(website, pattern))

            for page_url in pages_to_check:
                html = self._fetch_page(page_url)
                if html is None:
                    continue
                contacts = self._extract_contacts(html, page_url)
                result.contacts.extend(contacts)
                if self._has_enough_contacts(result.contacts):
                    break
        except Exception as e:
            result.success = False
            result.error = str(e)

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    def _fetch_page(self, url: str) -> str | None:
        try:
            resp = self._session.get(url, timeout=self._timeout)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            logger.debug("Failed to fetch %s: %s", url, e)
        return None

    def _extract_contacts(self, html: str, source_url: str) -> list[ContactData]:
        contacts: list[ContactData] = []
        text = re.sub(r"<[^>]+>", " ", html)

        for phone in self._extract_phones(text):
            is_fac = self._is_facility_context(text, phone)
            contacts.append(ContactData(
                contact_type="phone", value=phone,
                source_url=source_url, source_type="official_website",
                confidence=0.85 if is_fac else 0.80,
                is_facility=is_fac,
            ))

        for email in self._extract_emails(text):
            is_fac = self._is_facility_context(text, email)
            contacts.append(ContactData(
                contact_type="email", value=email,
                source_url=source_url, source_type="official_website",
                confidence=0.85 if is_fac else 0.80,
                is_facility=is_fac,
            ))

        address = self._extract_address(text)
        if address:
            contacts.append(ContactData(
                contact_type="address", value=address,
                source_url=source_url, source_type="official_website",
                confidence=0.75,
            ))

        return contacts

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
        found: set[str] = set()
        for match in re.findall(pattern, text):
            low = match.lower()
            if not any(x in low for x in ("example.com", "domain.com", "email.com", "site.com")):
                found.add(low)
        return list(found)

    @staticmethod
    def _extract_address(text: str) -> str | None:
        patterns = [
            r"(?:г\.\s*\w+|Москва|Санкт-Петербург)[^.\n]{10,100}(?:ул\.|просп\.|пер\.|бульвар|пр-т)[^.\n]{5,50}",
            r"(?:Россия|РФ)[^.\n]{10,150}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                addr = match.group(0).strip()
                if len(addr) > 15:
                    return addr[:200]
        return None

    @staticmethod
    def _is_facility_context(text: str, contact_value: str) -> bool:
        idx = text.lower().find(contact_value.lower())
        if idx == -1:
            return False
        context_start = max(0, idx - 200)
        context_end = min(len(text), idx + len(contact_value) + 200)
        context = text[context_start:context_end].lower()
        return any(kw in context for kw in FACILITY_KEYWORDS)

    @staticmethod
    def _has_enough_contacts(contacts: list[ContactData]) -> bool:
        has_phone = any(c.contact_type == "phone" for c in contacts)
        has_email = any(c.contact_type == "email" for c in contacts)
        return has_phone and has_email
