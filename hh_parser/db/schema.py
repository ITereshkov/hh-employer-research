import sqlite3
from pathlib import Path

INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS employers (
    id                      INTEGER PRIMARY KEY,
    name                    TEXT NOT NULL,
    url                     TEXT,
    alternate_url           TEXT,
    description             TEXT,
    logo_url                TEXT,
    area_id                 INTEGER,
    area_name               TEXT,
    industry_id             INTEGER,
    industry_name           TEXT,
    official_website        TEXT,
    official_phone          TEXT,
    official_email          TEXT,
    official_address        TEXT,
    facility_contact_role   TEXT,
    facility_contact_name   TEXT,
    facility_contact_phone  TEXT,
    facility_contact_email  TEXT,
    contact_source_url      TEXT,
    contact_confidence      REAL,
    vacancy_count           INTEGER DEFAULT 0,
    signal_score            REAL DEFAULT 0.0,
    first_seen_at           TEXT NOT NULL,
    last_updated_at         TEXT NOT NULL,
    enrichment_status       TEXT DEFAULT 'pending',
    enrichment_ttl          TEXT,
    raw_json                TEXT
);

CREATE INDEX IF NOT EXISTS idx_employers_area ON employers(area_id);
CREATE INDEX IF NOT EXISTS idx_employers_industry ON employers(industry_id);
CREATE INDEX IF NOT EXISTS idx_employers_signal ON employers(signal_score DESC);
CREATE INDEX IF NOT EXISTS idx_employers_enrichment ON employers(enrichment_status);
CREATE INDEX IF NOT EXISTS idx_employers_vacancy_count ON employers(vacancy_count DESC);

CREATE TABLE IF NOT EXISTS vacancies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    salary_from     INTEGER,
    salary_to       INTEGER,
    salary_currency TEXT,
    area_id         INTEGER,
    area_name       TEXT,
    url             TEXT,
    alternate_url   TEXT,
    published_at    TEXT,
    created_at      TEXT,
    experience_id   TEXT,
    experience_name TEXT,
    employment_type TEXT,
    schedule_type   TEXT,
    keyword_match   TEXT,
    category        TEXT,
    is_active       INTEGER DEFAULT 1,
    raw_json        TEXT,
    retrieved_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vacancies_published ON vacancies(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_vacancies_category ON vacancies(category);
CREATE INDEX IF NOT EXISTS idx_vacancies_active ON vacancies(is_active);

CREATE TABLE IF NOT EXISTS employer_vacancies (
    employer_id     INTEGER NOT NULL REFERENCES employers(id),
    vacancy_id      INTEGER NOT NULL REFERENCES vacancies(id),
    matched_keyword TEXT,
    matched_at      TEXT NOT NULL,
    PRIMARY KEY (employer_id, vacancy_id)
);

CREATE INDEX IF NOT EXISTS idx_ev_employer ON employer_vacancies(employer_id);
CREATE INDEX IF NOT EXISTS idx_ev_vacancy ON employer_vacancies(vacancy_id);

CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employer_id     INTEGER NOT NULL REFERENCES employers(id),
    contact_type    TEXT NOT NULL,
    value           TEXT NOT NULL,
    source_url      TEXT,
    source_type     TEXT NOT NULL,
    retrieved_at    TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    is_primary      INTEGER DEFAULT 0,
    notes           TEXT,
    UNIQUE(employer_id, contact_type, value, source_url)
);

CREATE INDEX IF NOT EXISTS idx_contacts_employer ON contacts(employer_id);
CREATE INDEX IF NOT EXISTS idx_contacts_type ON contacts(contact_type);
CREATE INDEX IF NOT EXISTS idx_contacts_confidence ON contacts(confidence DESC);

CREATE TABLE IF NOT EXISTS enrichment_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employer_id     INTEGER NOT NULL REFERENCES employers(id),
    source_type     TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    details         TEXT,
    retry_count     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_enrichment_log_employer ON enrichment_log(employer_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_log_status ON enrichment_log(status);

CREATE TABLE IF NOT EXISTS search_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text      TEXT NOT NULL,
    area_id         INTEGER,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    total_found     INTEGER DEFAULT 0,
    pages_fetched   INTEGER DEFAULT 0,
    new_employers   INTEGER DEFAULT 0,
    new_vacancies   INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running'
);
"""


def run_migrations(conn: sqlite3.Connection) -> None:
    conn.executescript(INITIAL_SCHEMA)
