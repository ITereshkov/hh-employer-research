from hh_parser.enrichment.resolver import ContactResolver, ResolvedContact
from hh_parser.enrichment.sources.base import ContactData


class TestContactResolver:
    def setup_method(self):
        self.resolver = ContactResolver()

    def test_resolve_deduplicates_phones(self):
        contacts = [
            ContactData("phone", "+74951234567", "url1", "hh_profile", 0.95),
            ContactData("phone", "+7 (495) 123-45-67", "url2", "website", 0.80),
        ]
        resolved = self.resolver.resolve(contacts)
        phones = [c for c in resolved if c.contact_type == "phone"]
        assert len(phones) == 1
        assert phones[0].confidence == 0.95

    def test_resolve_deduplicates_emails(self):
        contacts = [
            ContactData("email", "Info@Example.COM", "url1", "hh_profile", 0.60),
            ContactData("email", "info@example.com", "url2", "website", 0.80),
        ]
        resolved = self.resolver.resolve(contacts)
        emails = [c for c in resolved if c.contact_type == "email"]
        assert len(emails) == 1
        assert emails[0].confidence == 0.80

    def test_resolve_keeps_different_types(self):
        contacts = [
            ContactData("phone", "+74951234567", "url1", "website", 0.80),
            ContactData("email", "info@example.com", "url1", "website", 0.80),
            ContactData("website", "https://example.com", "url1", "hh_profile", 0.95),
        ]
        resolved = self.resolver.resolve(contacts)
        assert len(resolved) == 3

    def test_primary_flag(self):
        contacts = [
            ContactData("phone", "+74951111111", "url1", "website", 0.80),
            ContactData("phone", "+74952222222", "url2", "hh_profile", 0.60),
        ]
        resolved = self.resolver.resolve(contacts)
        phones = [c for c in resolved if c.contact_type == "phone"]
        assert phones[0].is_primary is True
        assert phones[0].value == "+74951111111"

    def test_normalize_phone_8_to_plus7(self):
        result = self.resolver._normalize_phone("84951234567")
        assert result == "+74951234567"

    def test_normalize_url_strips_www(self):
        result = self.resolver._normalize_url("https://www.example.com/")
        assert result == "example.com"

    def test_signal_score_basic(self):
        employer = {"vacancy_count": 3, "description": "some desc"}
        contacts = [
            ResolvedContact("website", "https://example.com", 0.95, "url", "hh", True),
            ResolvedContact("phone", "+74951234567", 0.80, "url", "web", False),
        ]
        score = self.resolver.compute_signal_score(employer, contacts)
        assert score > 0
        assert score <= 1.0

    def test_signal_score_max_is_1(self):
        employer = {"vacancy_count": 10, "description": "desc"}
        contacts = [
            ResolvedContact("website", "url", 0.95, "url", "hh", True),
            ResolvedContact("phone", "+7", 0.80, "url", "web", True),
            ResolvedContact("email", "e@e.com", 0.80, "url", "web", True),
            ResolvedContact("address", "addr", 0.70, "url", "web", False),
        ]
        score = self.resolver.compute_signal_score(employer, contacts)
        assert score <= 1.0
