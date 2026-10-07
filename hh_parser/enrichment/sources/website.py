import logging
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from .base import EnrichmentSource, EnrichmentResult, ContactData

logger = logging.getLogger(__name__)

CONTACT_PAGE_PATTERNS = [
    "/contacts",
    "/contact",
    "/about/contacts",
    "/about/contact",
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
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; HHResearchBot/1.0)"
            },
        )

    async def fetch(self, employer: dict) -> EnrichmentResult:
        start = time.monotonic()
        result = EnrichmentResult(
            employer_id=employer["id"], source_name=self.name
        )

        website = employer.get("official_website")
        if not website:
            result.success = True
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        if not website.startswith("http"):
            website = "https://" + website

        try:
            pages_to_check = [website]
            for pattern in CONTACT_PAGE_PATTERNS:
                pages_to_check.append(urljoin(website, pattern))

            for page_url in pages_to_check:
                html = await self._fetch_page(page_url)
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

    async def _fetch_page(self, url: str) -> Optional[str]:
        try:
            response = await self._client.get(url)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            logger.debug("Failed to fetch %s: %s", url, e)
        return None

    def _extract_contacts(self, html: str, source_url: str) -> list[ContactData]:
        contacts = []
        text = re.sub(r"<[^>]+>", " ", html)

        phones = self._extract_phones(text)
        for phone in phones:
            is_facility = self._is_facility_context(text, phone)
            contacts.append(
                ContactData(
                    contact_type="phone",
                    value=phone,
                    source_url=source_url,
                    source_type="official_website",
                    confidence=0.80 if not is_facility else 0.85,
                    is_facility=is_facility,
                )
            )

        emails = self._extract_emails(text)
        for email in emails:
            is_facility = self._is_facility_context(text, email)
            contacts.append(
                ContactData(
                    contact_type="email",
                    value=email,
                    source_url=source_url,
                    source_type="official_website",
                    confidence=0.80 if not is_facility else 0.85,
                    is_facility=is_facility,
                )
            )

        address = self._extract_address(text)
        if address:
            contacts.append(
                ContactData(
                    contact_type="address",
                    value=address,
                    source_url=source_url,
                    source_type="official_website",
                    confidence=0.75,
                )
            )

        return contacts

    def _extract_phones(self, text: str) -> list[str]:
        patterns = [
            r"\+7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
            r"\+7\d{10}",
        ]
        found = set()
        for pattern in patterns:
            for match in re.findall(pattern, text):
                clean = re.sub(r"[^\d+]", "", match)
                if len(clean) >= 11:
                    found.add(clean)
        return list(found)

    def _extract_emails(self, text: str) -> list[str]:
        pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
        found = set()
        for match in re.findall(pattern, text):
            if not any(
                x in match.lower()
                for x in ["example.com", "domain.com", "email.com", "site.com"]
            ):
                found.add(match.lower())
        return list(found)

    def _extract_address(self, text: str) -> Optional[str]:
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

    def _is_facility_context(self, text: str, contact_value: str) -> bool:
        idx = text.lower().find(contact_value.lower())
        if idx == -1:
            return False
        context_start = max(0, idx - 200)
        context_end = min(len(text), idx + len(contact_value) + 200)
        context = text[context_start:context_end].lower()
        return any(kw in context for kw in FACILITY_KEYWORDS)

    def _has_enough_contacts(self, contacts: list[ContactData]) -> bool:
        has_phone = any(c.contact_type == "phone" for c in contacts)
        has_email = any(c.contact_type == "email" for c in contacts)
        return has_phone and has_email

    async def close(self):
        await self._client.aclose()
