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

CREATE INDEX IF NOT EXISTS idx_employer_snapshots_employer
    ON employer_snapshots(employer_id);
CREATE INDEX IF NOT EXISTS idx_vacancy_snapshots_vacancy
    ON vacancy_snapshots(vacancy_id);
CREATE INDEX IF NOT EXISTS idx_vacancies_employer
    ON vacancies(employer_id);
CREATE INDEX IF NOT EXISTS idx_vacancy_status_employer
    ON vacancy_status(employer_id);
"""


class Storage:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

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

    def commit(self):
        self.conn.commit()
