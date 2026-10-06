"""HH API client with pagination, rate limiting, caching, retry/backoff."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from .config import ApiConfig, StorageConfig

logger = logging.getLogger(__name__)


class HHApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"HH API {status}: {message}")


class HHApiClient:
    def __init__(self, api_config: ApiConfig, storage_config: StorageConfig):
        self.cfg = api_config
        self.storage_cfg = storage_config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.cfg.user_agent,
            "Accept": "application/json",
        })
        self._cache_dir = Path(storage_config.cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request_time = 0.0

    def _rate_limit(self):
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.cfg.delay:
            time.sleep(self.cfg.delay - elapsed)
        self._last_request_time = time.monotonic()

    def _cache_key(self, url: str, params: dict) -> str:
        raw = json.dumps({"url": url, "params": params}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def _get_cached(self, key: str) -> dict | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if age_hours > self.storage_cfg.cache_ttl_hours:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _set_cached(self, key: str, data: dict):
        path = self._cache_path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def _request(self, path: str, params: dict | None = None, use_cache: bool = True) -> dict:
        url = f"{self.cfg.base_url}{path}"
        params = params or {}
        key = self._cache_key(url, params)

        if use_cache:
            cached = self._get_cached(key)
            if cached is not None:
                logger.debug("Cache hit: %s", path)
                return cached

        last_exc = None
        for attempt in range(1, self.cfg.max_retries + 1):
            self._rate_limit()
            try:
                logger.debug("API request: %s params=%s attempt=%d", path, params, attempt)
                resp = self.session.get(url, params=params, timeout=self.cfg.timeout)
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                    logger.warning("Rate limited, waiting %.1fs", wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("Server error %d, retry in %ds", resp.status_code, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 400:
                    raise HHApiError(resp.status_code, resp.text[:500])
                data = resp.json()
                if use_cache:
                    self._set_cached(key, data)
                return data
            except requests.exceptions.RequestException as e:
                last_exc = e
                wait = 2 ** attempt
                logger.warning("Request error: %s, retry in %ds", e, wait)
                time.sleep(wait)
        raise HHApiError(0, f"All {self.cfg.max_retries} retries failed: {last_exc}")

    def get(self, path: str, params: dict | None = None, use_cache: bool = True) -> dict:
        return self._request(path, params, use_cache)

    def paginate(self, path: str, params: dict | None = None, max_pages: int | None = None) -> list[dict]:
        params = dict(params or {})
        params.setdefault("per_page", self.cfg.per_page)
        max_pages = max_pages or self.cfg.max_pages
        items = []
        page = 0
        while page < max_pages:
            params["page"] = page
            data = self._request(path, params, use_cache=True)
            page_items = data.get("items", [])
            items.extend(page_items)
            total_pages = data.get("pages", 1)
            logger.info(
                "Paginating %s: page %d/%d, got %d items (total %d)",
                path, page + 1, total_pages, len(page_items), data.get("found", 0),
            )
            if page + 1 >= total_pages:
                break
            page += 1
        return items

    def search_employers(self, text: str, area_id: int | None = None) -> list[dict]:
        params: dict[str, Any] = {"text": text, "per_page": self.cfg.per_page}
        if area_id is not None:
            params["area"] = area_id
        return self.paginate("/employers", params)

    def get_employer(self, employer_id: int | str) -> dict:
        return self.get(f"/employers/{employer_id}")

    def get_employer_vacancies(self, employer_id: int | str) -> list[dict]:
        params = {"employer_id": employer_id, "per_page": self.cfg.per_page}
        return self.paginate("/vacancies", params)

    def get_vacancy(self, vacancy_id: int | str) -> dict:
        return self.get(f"/vacancies/{vacancy_id}")

    def get_areas(self) -> list[dict]:
        return self.get("/areas", use_cache=True)
