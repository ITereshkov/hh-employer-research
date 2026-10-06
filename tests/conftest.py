import pytest
import sqlite3

from hh_parser.db.schema import run_migrations
from hh_parser.db.connection import DatabaseConnection


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_employer():
    return {
        "id": 12345,
        "name": "Тестовая организация",
        "url": "https://hh.ru/employer/12345",
        "alternate_url": "https://hh.ru/employer/12345",
        "description": "Описание тестовой организации",
        "logo_url": None,
        "area_id": 1,
        "area_name": "Москва",
        "industry_id": 7,
        "industry_name": "Образование",
        "raw_json": {"id": 12345, "name": "Тестовая организация"},
    }


@pytest.fixture
def sample_vacancy():
    return {
        "id": 67890,
        "name": "Начальник АХО",
        "description": "<p>Требуется начальник АХО</p>",
        "salary_from": 80000,
        "salary_to": 120000,
        "salary_currency": "RUR",
        "area_id": 1,
        "area_name": "Москва",
        "url": "https://api.hh.ru/vacancy/67890",
        "alternate_url": "https://hh.ru/vacancy/67890",
        "published_at": "2026-10-01T12:00:00+0300",
        "created_at": "2026-10-01T12:00:00+0300",
        "experience_id": "between3And6",
        "experience_name": "От 3 до 6 лет",
        "employment_type": "Полная занятость",
        "schedule_type": "Полный день",
        "raw_json": {"id": 67890, "name": "Начальник АХО"},
    }
