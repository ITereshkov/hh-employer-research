import asyncio
import json
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

import httpx

from .endpoints import BASE_URL, USER_AGENT, VACANCIES, VACANCY_DETAIL, EMPLOYER_DETAIL, AREAS, INDUSTRIES
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class HHApiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"HH API error {status_code}: {message}")


class HHApiClient:
    def __init__(
        self,
        rate_limiter: RateLimiter,
        cache_dir: Optional[Path] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
    ):
        self._rate_limiter = rate_limiter
        self._cache_dir = cache_dir
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=self._timeout,
            )
        return self._client

    async def search_vacancies(
        self,
        text: str,
        area: Optional[int] = None,
        page: int = 0,
        per_page: int = 100,
        search_field: str = "name",
        order_by: str = "publication_time",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "text": text,
            "page": page,
            "per_page": per_page,
            "search_field": search_field,
            "order_by": order_by,
        }
        if area is not None:
            params["area"] = area
        return await self._request("GET", VACANCIES, params=params)

    async def get_vacancy(self, vacancy_id: int) -> dict[str, Any]:
        return await self._request(
            "GET", VACANCY_DETAIL.format(vacancy_id=vacancy_id)
        )

    async def get_employer(self, employer_id: int) -> dict[str, Any]:
        return await self._request(
            "GET", EMPLOYER_DETAIL.format(employer_id=employer_id)
        )

    async def get_areas(self) -> list[dict]:
        result = await self._request("GET", AREAS)
        return result if isinstance(result, list) else []

    async def get_industries(self) -> list[dict]:
        result = await self._request("GET", INDUSTRIES)
        return result if isinstance(result, list) else []

    async def _request(
        self, method: str, path: str, params: Optional[dict] = None
    ) -> Any:
        cache_key = self._cache_key(method, path, params)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries):
            await self._rate_limiter.acquire()
            try:
                response = await client.request(method, path, params=params)
                if response.status_code == 429:
                    wait = float(response.headers.get("Retry-After", 60))
                    logger.warning("Rate limited, waiting %.0fs", wait)
                    await asyncio.sleep(wait)
                    continue
                if response.status_code >= 500:
                    logger.warning("Server error %d, retry %d", response.status_code, attempt + 1)
                    await asyncio.sleep(2 ** attempt)
                    continue
                if response.status_code >= 400:
                    raise HHApiError(response.status_code, response.text[:200])
                data = response.json()
                self._write_cache(cache_key, data)
                return data
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning("Timeout on attempt %d for %s", attempt + 1, path)
                await asyncio.sleep(2 ** attempt)
            except httpx.HTTPError as e:
                last_error = e
                logger.warning("HTTP error on attempt %d: %s", attempt + 1, e)
                await asyncio.sleep(2 ** attempt)

        raise last_error or Exception("Request failed after retries")

    def _cache_key(self, method: str, path: str, params: Optional[dict]) -> str:
        raw = f"{method}:{path}:{json.dumps(params or {}, sort=True)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _read_cache(self, key: str) -> Any:
        if not self._cache_dir:
            return None
        cache_file = self._cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def _write_cache(self, key: str, data: Any) -> None:
        if not self._cache_dir:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / f"{key}.json"
        try:
            cache_file.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
