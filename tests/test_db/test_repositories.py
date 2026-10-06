import sqlite3

from hh_parser.db.schema import run_migrations
from hh_parser.db.repositories import EmployerRepository, EmployerFilters


class TestEmployerRepository:
    def test_upsert_creates_new(self, db_conn, sample_employer):
        repo = EmployerRepository(db_conn)
        eid = repo.upsert(sample_employer)
        assert eid == 12345

        emp = repo.get_by_id(12345)
        assert emp is not None
        assert emp["name"] == "Тестовая организация"
        assert emp["area_name"] == "Москва"

    def test_upsert_updates_existing(self, db_conn, sample_employer):
        repo = EmployerRepository(db_conn)
        repo.upsert(sample_employer)

        sample_employer["name"] = "Обновлённое название"
        repo.upsert(sample_employer)

        emp = repo.get_by_id(12345)
        assert emp["name"] == "Обновлённое название"

    def test_upsert_from_vacancy(self, db_conn):
        repo = EmployerRepository(db_conn)
        ref = {"id": 99, "name": "Из вакансии", "url": None, "alternate_url": None}
        eid = repo.upsert_from_vacancy(ref)
        assert eid == 99

        emp = repo.get_by_id(99)
        assert emp["name"] == "Из вакансии"

    def test_get_all_with_filters(self, db_conn, sample_employer):
        repo = EmployerRepository(db_conn)
        repo.upsert(sample_employer)

        all_emps = repo.get_all()
        assert len(all_emps) == 1

        filtered = repo.get_all(EmployerFilters(area_id=999))
        assert len(filtered) == 0

        filtered = repo.get_all(EmployerFilters(area_id=1))
        assert len(filtered) == 1

    def test_count(self, db_conn, sample_employer):
        repo = EmployerRepository(db_conn)
        assert repo.count() == 0

        repo.upsert(sample_employer)
        assert repo.count() == 1

    def test_get_needs_enrichment(self, db_conn, sample_employer):
        repo = EmployerRepository(db_conn)
        repo.upsert(sample_employer)

        needs = repo.get_needs_enrichment()
        assert len(needs) == 1
        assert needs[0]["enrichment_status"] == "pending"

    def test_update_enrichment_status(self, db_conn, sample_employer):
        repo = EmployerRepository(db_conn)
        repo.upsert(sample_employer)

        repo.update_enrichment_status(12345, "done", ttl_hours=168)
        emp = repo.get_by_id(12345)
        assert emp["enrichment_status"] == "done"

    def test_update_enriched_contacts(self, db_conn, sample_employer):
        repo = EmployerRepository(db_conn)
        repo.upsert(sample_employer)

        contacts = {
            "official_website": "https://example.com",
            "official_phone": "+74951234567",
            "official_email": "info@example.com",
            "official_address": "г. Москва, ул. Тестовая, 1",
        }
        repo.update_enriched_contacts(12345, contacts)

        emp = repo.get_by_id(12345)
        assert emp["official_website"] == "https://example.com"
        assert emp["official_phone"] == "+74951234567"

    def test_update_signal_score(self, db_conn, sample_employer):
        repo = EmployerRepository(db_conn)
        repo.upsert(sample_employer)

        repo.update_signal_score(12345, 0.75)
        emp = repo.get_by_id(12345)
        assert emp["signal_score"] == 0.75
