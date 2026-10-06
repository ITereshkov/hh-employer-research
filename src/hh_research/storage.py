"""SQLite storage for employer snapshots and historical tracking."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at TEXT NOT NULL,
    config_hash TEXT,
    areas TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS employers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT,
    area_id INTEGER,
    area_name TEXT,
    description TEXT,
    industry TEXT,
    classification TEXT,
    classification_reason TEXT,
    classification_confidence REAL,
    first_seen_at TEXT,
    last_seen_at TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS employer_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    employer_id INTEGER NOT NULL REFERENCES employers(id),
    total_open_vacancies INTEGER DEFAULT 0,
    relevant_open_vacancies INTEGER DEFAULT 0,
    UNIQUE(snapshot_id, employer_id)
);

CREATE TABLE IF NOT EXISTS vacancies (
    id TEXT PRIMARY KEY,
    employer_id INTEGER NOT NULL REFERENCES employers(id),
    name TEXT NOT NULL,
    url TEXT,
    published_at TEXT,
    created_at TEXT,
    salary_from INTEGER,
    salary_to INTEGER,
    currency TEXT,
    schedule TEXT,
    employment TEXT,
    experience TEXT,
    area_id INTEGER,
    area_name TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS vacancy_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    vacancy_id TEXT NOT NULL REFERENCES vacancies(id),
    is_relevant INTEGER NOT NULL DEFAULT 0,
    relevance_score REAL DEFAULT 0.0,
    matched_terms TEXT,
    match_reason TEXT,
    UNIQUE(snapshot_id, vacancy_id)
);

CREATE TABLE IF NOT EXISTS vacancy_status (
    vacancy_id TEXT PRIMARY KEY REFERENCES vacancies(id),
    employer_id INTEGER NOT NULL,
    last_seen_in_snapshot INTEGER REFERENCES snapshots(id),
    first_seen_in_snapshot INTEGER REFERENCES snapshots(id),
    is_currently_open INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employer_id INTEGER NOT NULL REFERENCES employers(id),
    contact_type TEXT NOT NULL,
    value TEXT NOT NULL,
    source_url TEXT,
    source_type TEXT,
    confidence REAL DEFAULT 0.0,
    is_primary INTEGER DEFAULT 0,
    is_facility INTEGER DEFAULT 0,
    retrieved_at TEXT,
    UNIQUE(employer_id, contact_type, value)
);

CREATE TABLE IF NOT EXISTS enrichment_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employer_id INTEGER NOT NULL REFERENCES employers(id),
    source_name TEXT,
    status TEXT,
    message TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_employer_snapshots_employer
    ON employer_snapshots(employer_id);
CREATE INDEX IF NOT EXISTS idx_vacancy_snapshots_vacancy
    ON vacancy_snapshots(vacancy_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_employer
    ON vacancies(employer_id);
CREATE INDEX IF NOT EXISTS idx_vacancy_status_employer
    ON vacancy_status(employer_id);
CREATE INDEX IF NOT EXISTS idx_contacts_employer
    ON contacts(employer_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_log_employer
    ON enrichment_log(employer_id);
"""


class Storage:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._add_enrichment_columns()
        self.conn.commit()

    def _add_enrichment_columns(self):
        alters = [
            "ALTER TABLE employers ADD COLUMN enrichment_status TEXT DEFAULT 'pending'",
            "ALTER TABLE employers ADD COLUMN enrichment_ttl_hours REAL DEFAULT 0",
            "ALTER TABLE employers ADD COLUMN signal_score REAL DEFAULT 0.0",
            "ALTER TABLE employers ADD COLUMN official_website TEXT",
            "ALTER TABLE employers ADD COLUMN official_phone TEXT",
            "ALTER TABLE employers ADD COLUMN official_email TEXT",
            "ALTER TABLE employers ADD COLUMN official_address TEXT",
            "ALTER TABLE employers ADD COLUMN facility_contact_phone TEXT",
            "ALTER TABLE employers ADD COLUMN facility_contact_email TEXT",
        ]
        for sql in alters:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        try:
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

    def close(self):
        self.conn.close()

    def create_snapshot(self, config_hash: str = "", areas: str = "", note: str = "") -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO snapshots (snapshot_at, config_hash, areas, note) VALUES (?, ?, ?, ?)",
            (now, config_hash, areas, note),
        )
        self.conn.commit()
        return cur.lastrowid

    def upsert_employer(self, emp: dict):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO employers (id, name, url, area_id, area_name, description, industry,
               classification, classification_reason, classification_confidence,
               first_seen_at, last_seen_at, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, url=excluded.url, area_id=excluded.area_id,
                 area_name=excluded.area_name, description=excluded.description,
                 industry=excluded.industry, classification=excluded.classification,
                 classification_reason=excluded.classification_reason,
                 classification_confidence=excluded.classification_confidence,
                 last_seen_at=excluded.last_seen_at, raw_json=excluded.raw_json
            """,
            (
                emp["id"], emp["name"], emp.get("url"),
                emp.get("area_id"), emp.get("area_name"),
                emp.get("description"), emp.get("industry"),
                emp.get("classification"), emp.get("classification_reason"),
                emp.get("classification_confidence"),
                now, now,
                json.dumps(emp.get("raw", {}), ensure_ascii=False),
            ),
        )

    def link_employer_snapshot(self, snapshot_id: int, employer_id: int,
                                total_vacancies: int, relevant_vacancies: int):
        self.conn.execute(
            """INSERT OR REPLACE INTO employer_snapshots
               (snapshot_id, employer_id, total_open_vacancies, relevant_open_vacancies)
               VALUES (?, ?, ?, ?)""",
            (snapshot_id, employer_id, total_vacancies, relevant_vacancies),
        )

    def upsert_vacancy(self, vac: dict, employer_id: int):
        self.conn.execute(
            """INSERT INTO vacancies (id, employer_id, name, url, published_at, created_at,
               salary_from, salary_to, currency, schedule, employment, experience,
               area_id, area_name, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, url=excluded.url, published_at=excluded.published_at,
                 salary_from=excluded.salary_from, salary_to=excluded.salary_to,
                 currency=excluded.currency, schedule=excluded.schedule,
                 employment=excluded.employment, experience=excluded.experience,
                 raw_json=excluded.raw_json
            """,
            (
                vac["id"], employer_id, vac.get("name", ""),
                vac.get("url") or vac.get("alternate_url"),
                vac.get("published_at"), vac.get("created_at"),
                (vac.get("salary") or {}).get("from"),
                (vac.get("salary") or {}).get("to"),
                (vac.get("salary") or {}).get("currency"),
                (vac.get("schedule") or {}).get("name"),
                (vac.get("employment") or {}).get("name"),
                (vac.get("experience") or {}).get("name"),
                (vac.get("area") or {}).get("id"),
                (vac.get("area") or {}).get("name"),
                json.dumps(vac.get("raw", vac), ensure_ascii=False),
            ),
        )

    def link_vacancy_snapshot(self, snapshot_id: int, vacancy_id: str,
                               is_relevant: bool, score: float,
                               matched_terms: list[str], match_reason: str):
        self.conn.execute(
            """INSERT OR REPLACE INTO vacancy_snapshots
               (snapshot_id, vacancy_id, is_relevant, relevance_score, matched_terms, match_reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (snapshot_id, vacancy_id, int(is_relevant), score,
             json.dumps(matched_terms, ensure_ascii=False), match_reason),
        )

    def update_vacancy_status(self, snapshot_id: int, vacancy_id: str, employer_id: int):
        self.conn.execute(
            """INSERT INTO vacancy_status (vacancy_id, employer_id, last_seen_in_snapshot,
               first_seen_in_snapshot, is_currently_open)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(vacancy_id) DO UPDATE SET
                 last_seen_in_snapshot=excluded.last_seen_in_snapshot,
                 is_currently_open=1
            """,
            (vacancy_id, employer_id, snapshot_id, snapshot_id),
        )

    def mark_disappeared_vacancies(self, snapshot_id: int, seen_vacancy_ids: set[str]):
        if not seen_vacancy_ids:
            return
        placeholders = ",".join("?" * len(seen_vacancy_ids))
        self.conn.execute(
            f"""UPDATE vacancy_status
                SET is_currently_open = 0
                WHERE vacancy_id NOT IN ({placeholders})
                  AND is_currently_open = 1""",
            list(seen_vacancy_ids),
        )

    def get_latest_snapshot_id(self) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def get_employers_with_relevant(self, snapshot_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT e.*, es.total_open_vacancies, es.relevant_open_vacancies
               FROM employers e
               JOIN employer_snapshots es ON e.id = es.employer_id
               WHERE es.snapshot_id = ? AND es.relevant_open_vacancies > 0
               ORDER BY es.relevant_open_vacancies DESC""",
            (snapshot_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_relevant_vacancies(self, snapshot_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT v.*, vs.relevance_score, vs.matched_terms, vs.match_reason,
                      v.employer_id, e.name as employer_name
               FROM vacancies v
               JOIN vacancy_snapshots vs ON v.id = vs.vacancy_id
               JOIN employers e ON v.employer_id = e.id
               WHERE vs.snapshot_id = ? AND vs.is_relevant = 1
               ORDER BY vs.relevance_score DESC""",
            (snapshot_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_employers(self, snapshot_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT e.*, es.total_open_vacancies, es.relevant_open_vacancies
               FROM employers e
               JOIN employer_snapshots es ON e.id = es.employer_id
               WHERE es.snapshot_id = ?
               ORDER BY e.name""",
            (snapshot_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_snapshot_info(self, snapshot_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return dict(row) if row else None

    def count_new_vacancies(self, snapshot_id: int) -> int:
        row = self.conn.execute(
            """SELECT COUNT(*) FROM vacancy_status
               WHERE first_seen_in_snapshot = ?""",
            (snapshot_id,),
        ).fetchone()
        return row[0] if row else 0

    def count_disappeared_vacancies(self, snapshot_id: int) -> int:
        row = self.conn.execute(
            """SELECT COUNT(*) FROM vacancy_status
               WHERE last_seen_in_snapshot < ? AND is_currently_open = 0""",
            (snapshot_id,),
        ).fetchone()
        return row[0] if row else 0

    def upsert_contact(self, employer_id: int, contact_type: str, value: str,
                       source_url: str = "", source_type: str = "",
                       confidence: float = 0.0, is_primary: bool = False,
                       is_facility: bool = False):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO contacts (employer_id, contact_type, value, source_url,
               source_type, confidence, is_primary, is_facility, retrieved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(employer_id, contact_type, value) DO UPDATE SET
                 source_url=excluded.source_url, source_type=excluded.source_type,
                 confidence=excluded.confidence, is_primary=excluded.is_primary,
                 is_facility=excluded.is_facility, retrieved_at=excluded.retrieved_at
            """,
            (employer_id, contact_type, value, source_url, source_type,
             confidence, int(is_primary), int(is_facility), now),
        )

    def get_contacts(self, employer_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM contacts WHERE employer_id = ? ORDER BY contact_type, confidence DESC",
            (employer_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_contacts(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT c.*, e.name as employer_name
               FROM contacts c JOIN employers e ON c.employer_id = e.id
               ORDER BY c.employer_id, c.contact_type"""
        ).fetchall()
        return [dict(r) for r in rows]

    def update_employer_enrichment(self, employer_id: int, status: str,
                                    ttl_hours: float = 0, signal_score: float = 0.0,
                                    contacts: dict | None = None):
        sets = ["enrichment_status=?", "enrichment_ttl_hours=?", "signal_score=?"]
        params: list = [status, ttl_hours, signal_score]
        if contacts:
            for col in ("official_website", "official_phone", "official_email",
                        "official_address", "facility_contact_phone", "facility_contact_email"):
                if col in contacts:
                    sets.append(f"{col}=?")
                    params.append(contacts[col])
        params.append(employer_id)
        self.conn.execute(
            f"UPDATE employers SET {', '.join(sets)} WHERE id=?", params,
        )

    def log_enrichment(self, employer_id: int, source_name: str,
                       status: str, message: str = ""):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO enrichment_log (employer_id, source_name, status, message, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (employer_id, source_name, status, message, now),
        )

    def get_employers_needing_enrichment(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM employers
               WHERE enrichment_status IS NULL OR enrichment_status = 'pending'
                  OR (enrichment_status = 'done' AND enrichment_ttl_hours > 0
                      AND julianday('now') - julianday(last_seen_at) > enrichment_ttl_hours / 24.0)
               ORDER BY signal_score DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_enrichment_stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM employers").fetchone()[0]
        enriched = self.conn.execute(
            "SELECT COUNT(*) FROM employers WHERE enrichment_status = 'done'"
        ).fetchone()[0]
        with_website = self.conn.execute(
            "SELECT COUNT(*) FROM employers WHERE official_website IS NOT NULL AND official_website != ''"
        ).fetchone()[0]
        with_phone = self.conn.execute(
            "SELECT COUNT(*) FROM employers WHERE official_phone IS NOT NULL AND official_phone != ''"
        ).fetchone()[0]
        with_facility = self.conn.execute(
            "SELECT COUNT(*) FROM employers WHERE facility_contact_phone IS NOT NULL AND facility_contact_phone != ''"
        ).fetchone()[0]
        contacts_total = self.conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        return {
            "employers_total": total,
            "enriched": enriched,
            "with_website": with_website,
            "with_phone": with_phone,
            "with_facility_contact": with_facility,
            "contacts_total": contacts_total,
        }

    def commit(self):
        self.conn.commit()
