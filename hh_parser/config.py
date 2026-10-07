from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 25
    requests_per_day: int = 1800
    retry_after_seconds: float = 60.0
    max_retries: int = 3


@dataclass
class SearchConfig:
    per_page: int = 100
    max_pages: int = 20
    search_field: str = "name"


@dataclass
class EnrichmentConfig:
    enabled: bool = True
    ttl_hours: int = 168
    max_concurrent: int = 3
    request_timeout: float = 15.0
    batch_size: int = 50
    sources_priority: list[str] = field(
        default_factory=lambda: ["hh_employer", "website", "directory"]
    )


@dataclass
class DatabaseConfig:
    path: Path = Path("data/hh_parser.db")
    wal_mode: bool = True


@dataclass
class AppConfig:
    search: SearchConfig = field(default_factory=SearchConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "AppConfig":
        if config_path is None:
            for candidate in [Path("config.yaml"), Path("config.yml")]:
                if candidate.exists():
                    config_path = candidate
                    break

        data: dict = {}
        if config_path and config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "AppConfig":
        cfg = cls()
        if "search" in data:
            cfg.search = SearchConfig(**data["search"])
        if "enrichment" in data:
            cfg.enrichment = EnrichmentConfig(**data["enrichment"])
        if "database" in data:
            db = data["database"]
            if "path" in db:
                db["path"] = Path(db["path"])
            cfg.database = DatabaseConfig(**db)
        if "rate_limit" in data:
            cfg.rate_limit = RateLimitConfig(**data["rate_limit"])
        if "log_level" in data:
            cfg.log_level = data["log_level"]
        if "data_dir" in data:
            cfg.data_dir = Path(data["data_dir"])
        if "reports_dir" in data:
            cfg.reports_dir = Path(data["reports_dir"])
        return cfg
