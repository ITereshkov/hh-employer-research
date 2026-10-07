import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EmployerFilters:
    area_id: Optional[int] = None
    industry_id: Optional[int] = None
    has_phone: Optional[bool] = None
    has_facility_contact: Optional[bool] = None
    min_signal_score: Optional[float] = None
    min_vacancy_count: Optional[int] = None
    enrichment_status: Optional[str] = None
    category: Optional[str] = None
    search_after: Optional[str] = None


class EmployerRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert(self, data: dict) -> int:
        now = _now_iso()
        existing = self.get_by_id(data["id"])
        if existing:
            self._conn.execute(
                """UPDATE employers SET
                    name=?, url=?, alternate_url=?, description=?, logo_url=?,
                    area_id=?, area_name=?, industry_id=?, industry_name=?,
                    last_updated_at=?, raw_json=?
                   WHERE id=?""",
                (
                    data.get("name", ""),
                    data.get("url"),
                    data.get("alternate_url"),
                    data.get("description"),
                    data.get("logo_url"),
                    data.get("area_id"),
                    data.get("area_name"),
                    data.get("industry_id"),
                    data.get("industry_name"),
                    now,
                    json.dumps(data.get("raw_json"), ensure_ascii=False) if data.get("raw_json") else None,
                    data["id"],
                ),
            )
        else:
            self._conn.execute(
                """INSERT INTO employers
                   (id, name, url, alternate_url, description, logo_url,
                    area_id, area_name, industry_id, industry_name,
                    first_seen_at, last_updated_at, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data["id"],
                    data.get("name", ""),
                    data.get("url"),
                    data.get("alternate_url"),
                    data.get("description"),
                    data.get("logo_url"),
                    data.get("area_id"),
                    data.get("area_name"),
                    data.get("industry_id"),
                    data.get("industry_name"),
                    now,
                    now,
                    json.dumps(data.get("raw_json"), ensure_ascii=False) if data.get("raw_json") else None,
                ),
            )
        self._conn.commit()
        return data["id"]

    def upsert_from_vacancy(self, employer_ref: dict) -> int:
        eid = employer_ref["id"]
        now = _now_iso()
        existing = self.get_by_id(eid)
        if existing:
            self._conn.execute(
                "UPDATE employers SET vacancy_count = vacancy_count + 0, last_updated_at=? WHERE id=?",
                (now, eid),
            )
        else:
            self._conn.execute(
                """INSERT INTO employers (id, name, url, alternate_url, area_id, area_name,
                   first_seen_at, last_updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    eid,
                    employer_ref.get("name", ""),
                    employer_ref.get("url"),
                    employer_ref.get("alternate_url"),
                    employer_ref.get("area_id"),
                    employer_ref.get("area_name"),
                    now,
                    now,
                ),
            )
        self._conn.commit()
        return eid

    def get_by_id(self, employer_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM employers WHERE id=?", (employer_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all(self, filters: Optional[EmployerFilters] = None) -> list[dict]:
        query = "SELECT * FROM employers WHERE 1=1"
        params: list = []
        if filters:
            if filters.area_id is not None:
                query += " AND area_id=?"
                params.append(filters.area_id)
            if filters.industry_id is not None:
                query += " AND industry_id=?"
                params.append(filters.industry_id)
            if filters.has_phone is True:
                query += " AND official_phone IS NOT NULL AND official_phone != ''"
            if filters.has_facility_contact is True:
                query += " AND facility_contact_phone IS NOT NULL AND facility_contact_phone != ''"
            if filters.min_signal_score is not None:
                query += " AND signal_score >= ?"
                params.append(filters.min_signal_score)
            if filters.min_vacancy_count is not None:
                query += " AND vacancy_count >= ?"
                params.append(filters.min_vacancy_count)
            if filters.enrichment_status is not None:
                query += " AND enrichment_status=?"
                params.append(filters.enrichment_status)
            if filters.search_after is not None:
                query += " AND first_seen_at >= ?"
                params.append(filters.search_after)
        query += " ORDER BY signal_score DESC, vacancy_count DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def count(self, filters: Optional[EmployerFilters] = None) -> int:
        query = "SELECT COUNT(*) FROM employers WHERE 1=1"
        params: list = []
        if filters:
            if filters.area_id is not None:
                query += " AND area_id=?"
                params.append(filters.area_id)
            if filters.enrichment_status is not None:
                query += " AND enrichment_status=?"
                params.append(filters.enrichment_status)
        row = self._conn.execute(query, params).fetchone()
        return row[0]

    def get_needs_enrichment(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM employers
               WHERE enrichment_status IN ('pending', 'failed')
               ORDER BY signal_score DESC, vacancy_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stale_enrichment(self, ttl_hours: int, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM employers
               WHERE enrichment_status = 'done'
                 AND (enrichment_ttl IS NULL OR enrichment_ttl < datetime('now'))
               ORDER BY enrichment_ttl ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_enrichment_status(
        self, employer_id: int, status: str, ttl_hours: Optional[int] = None
    ) -> None:
        ttl = None
        if status == "done" and ttl_hours:
            ttl = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE employers SET enrichment_status=?, enrichment_ttl=? WHERE id=?",
            (status, ttl, employer_id),
        )
        self._conn.commit()

    def update_enriched_contacts(self, employer_id: int, contacts: dict) -> None:
        self._conn.execute(
            """UPDATE employers SET
                official_website=?, official_phone=?, official_email=?, official_address=?,
                facility_contact_role=?, facility_contact_name=?,
                facility_contact_phone=?, facility_contact_email=?,
                contact_source_url=?, contact_confidence=?
               WHERE id=?""",
            (
                contacts.get("official_website"),
                contacts.get("official_phone"),
                contacts.get("official_email"),
                contacts.get("official_address"),
                contacts.get("facility_contact_role"),
                contacts.get("facility_contact_name"),
                contacts.get("facility_contact_phone"),
                contacts.get("facility_contact_email"),
                contacts.get("contact_source_url"),
                contacts.get("contact_confidence"),
                employer_id,
            ),
        )
        self._conn.commit()

    def update_vacancy_count(self, employer_id: int) -> None:
        self._conn.execute(
            """UPDATE employers SET vacancy_count = (
                SELECT COUNT(*) FROM employer_vacancies WHERE employer_id=?
            ) WHERE id=?""",
            (employer_id, employer_id),
        )
        self._conn.commit()

    def update_signal_score(self, employer_id: int, score: float) -> None:
        self._conn.execute(
            "UPDATE employers SET signal_score=? WHERE id=?", (score, employer_id)
        )
        self._conn.commit()

    def get_all_employer_ids(self) -> list[int]:
        rows = self._conn.execute("SELECT id FROM employers").fetchall()
        return [r[0] for r in rows]


class VacancyRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert(self, data: dict, keyword: str, category: str) -> int:
        now = _now_iso()
        existing = self.get_by_id(data["id"])
        if existing:
            self._conn.execute(
                """UPDATE vacancies SET
                    name=?, description=?, salary_from=?, salary_to=?, salary_currency=?,
                    area_id=?, area_name=?, url=?, alternate_url=?,
                    published_at=?, created_at=?, experience_id=?, experience_name=?,
                    employment_type=?, schedule_type=?, keyword_match=?, category=?,
                    is_active=1, raw_json=?, retrieved_at=?
                   WHERE id=?""",
                (
                    data.get("name", ""),
                    data.get("description"),
                    data.get("salary_from"),
                    data.get("salary_to"),
                    data.get("salary_currency"),
                    data.get("area_id"),
                    data.get("area_name"),
                    data.get("url"),
                    data.get("alternate_url"),
                    data.get("published_at"),
                    data.get("created_at"),
                    data.get("experience_id"),
                    data.get("experience_name"),
                    data.get("employment_type"),
                    data.get("schedule_type"),
                    keyword,
                    category,
                    json.dumps(data.get("raw_json"), ensure_ascii=False) if data.get("raw_json") else None,
                    now,
                    data["id"],
                ),
            )
        else:
            self._conn.execute(
                """INSERT INTO vacancies
                   (id, name, description, salary_from, salary_to, salary_currency,
                    area_id, area_name, url, alternate_url, published_at, created_at,
                    experience_id, experience_name, employment_type, schedule_type,
                    keyword_match, category, raw_json, retrieved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data["id"],
                    data.get("name", ""),
                    data.get("description"),
                    data.get("salary_from"),
                    data.get("salary_to"),
                    data.get("salary_currency"),
                    data.get("area_id"),
                    data.get("area_name"),
                    data.get("url"),
                    data.get("alternate_url"),
                    data.get("published_at"),
                    data.get("created_at"),
                    data.get("experience_id"),
                    data.get("experience_name"),
                    data.get("employment_type"),
                    data.get("schedule_type"),
                    keyword,
                    category,
                    json.dumps(data.get("raw_json"), ensure_ascii=False) if data.get("raw_json") else None,
                    now,
                ),
            )
        self._conn.commit()
        return data["id"]

    def get_by_id(self, vacancy_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM vacancies WHERE id=?", (vacancy_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_employer(self, employer_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT v.* FROM vacancies v
               JOIN employer_vacancies ev ON v.id = ev.vacancy_id
               WHERE ev.employer_id=?
               ORDER BY v.published_at DESC""",
            (employer_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_by_category(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT category, COUNT(*) FROM vacancies WHERE is_active=1 GROUP BY category"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def count_active(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE is_active=1"
        ).fetchone()
        return row[0]

    def count_fresh(self, days: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE is_active=1 AND published_at >= datetime('now', ?)",
            (f"-{days} days",),
        ).fetchone()
        return row[0]


class EmployerVacancyRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def link(self, employer_id: int, vacancy_id: int, keyword: str) -> None:
        now = _now_iso()
        self._conn.execute(
            """INSERT OR IGNORE INTO employer_vacancies
               (employer_id, vacancy_id, matched_keyword, matched_at)
               VALUES (?,?,?,?)""",
            (employer_id, vacancy_id, keyword, now),
        )
        self._conn.commit()

    def get_vacancies_for_employer(self, employer_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT v.* FROM vacancies v
               JOIN employer_vacancies ev ON v.id = ev.vacancy_id
               WHERE ev.employer_id=?
               ORDER BY v.published_at DESC""",
            (employer_id,),
        ).fetchall()
        return [dict(r) for r in rows]


class ContactRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert(
        self,
        employer_id: int,
        contact_type: str,
        value: str,
        source_url: str,
        source_type: str,
        confidence: float,
    ) -> int:
        now = _now_iso()
        self._conn.execute(
            """INSERT INTO contacts (employer_id, contact_type, value, source_url, source_type, retrieved_at, confidence)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(employer_id, contact_type, value, source_url)
               DO UPDATE SET confidence=excluded.confidence, retrieved_at=excluded.retrieved_at""",
            (employer_id, contact_type, value, source_url, source_type, now, confidence),
        )
        self._conn.commit()
        return employer_id

    def get_for_employer(self, employer_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM contacts WHERE employer_id=? ORDER BY confidence DESC",
            (employer_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_primary(self, employer_id: int, contact_type: str) -> Optional[dict]:
        row = self._conn.execute(
            """SELECT * FROM contacts
               WHERE employer_id=? AND contact_type=?
               ORDER BY confidence DESC LIMIT 1""",
            (employer_id, contact_type),
        ).fetchone()
        return dict(row) if row else None


class EnrichmentLogRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def log(
        self,
        employer_id: int,
        source_type: str,
        status: str,
        details: Optional[str] = None,
    ) -> int:
        now = _now_iso()
        cursor = self._conn.execute(
            """INSERT INTO enrichment_log
               (employer_id, source_type, status, started_at, finished_at, details)
               VALUES (?,?,?,?,?,?)""",
            (employer_id, source_type, status, now, now, details),
        )
        self._conn.commit()
        return cursor.lastrowid


class SearchRunRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_run(self, query_text: str, area_id: Optional[int] = None) -> int:
        now = _now_iso()
        cursor = self._conn.execute(
            """INSERT INTO search_runs (query_text, area_id, started_at, status)
               VALUES (?,?,?,'running')""",
            (query_text, area_id, now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def complete_run(
        self,
        run_id: int,
        total_found: int,
        pages: int,
        new_employers: int,
        new_vacancies: int,
    ) -> None:
        now = _now_iso()
        self._conn.execute(
            """UPDATE search_runs SET
                finished_at=?, total_found=?, pages_fetched=?,
                new_employers=?, new_vacancies=?, status='completed'
               WHERE id=?""",
            (now, total_found, pages, new_employers, new_vacancies, run_id),
        )
        self._conn.commit()

    def fail_run(self, run_id: int, error: str) -> None:
        now = _now_iso()
        self._conn.execute(
            "UPDATE search_runs SET finished_at=?, status='failed' WHERE id=?",
            (now, run_id),
        )
        self._conn.commit()

    def get_recent(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM search_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
