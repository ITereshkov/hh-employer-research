import logging
from dataclasses import dataclass, field
from typing import Optional

from ..api.client import HHApiClient
from ..api.models import HHVacancyBrief, HHSearchResponse
from ..config import SearchConfig
from .keywords import build_search_queries, VacancyCategory

logger = logging.getLogger(__name__)


@dataclass
class SearchRunResult:
    total_vacancies_found: int = 0
    new_vacancies: int = 0
    new_employers: int = 0
    updated_employers: int = 0
    search_run_id: int = 0
    errors: list[str] = field(default_factory=list)
    collected_vacancies: list[tuple[dict, str, str]] = field(default_factory=list)


class VacancySearcher:
    def __init__(self, api_client: HHApiClient, config: SearchConfig):
        self._api = api_client
        self._config = config

    async def run_search(
        self,
        area: Optional[int] = None,
        custom_keywords: Optional[list[str]] = None,
    ) -> SearchRunResult:
        result = SearchRunResult()

        if custom_keywords:
            queries = [(kw, VacancyCategory.OTHER) for kw in custom_keywords]
        else:
            queries = build_search_queries()

        seen_vacancy_ids: set[int] = set()

        for keyword, category in queries:
            logger.info("Searching: %s [%s]", keyword, category.value)
            try:
                async for vacancy in self.search_keyword(keyword, area):
                    if vacancy.id in seen_vacancy_ids:
                        continue
                    seen_vacancy_ids.add(vacancy.id)
                    result.total_vacancies_found += 1
                    vac_dict = vacancy.model_dump()
                    result.collected_vacancies.append(
                        (vac_dict, keyword, category.value)
                    )
            except Exception as e:
                error_msg = f"Error searching '{keyword}': {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        return result

    async def search_keyword(
        self,
        keyword: str,
        area: Optional[int] = None,
    ):
        page = 0
        while page < self._config.max_pages:
            response = await self._fetch_page(keyword, area, page)
            if not response or not response.items:
                break

            for item in response.items:
                yield item

            if page >= response.pages - 1:
                break
            page += 1

    async def _fetch_page(
        self, keyword: str, area: Optional[int], page: int
    ) -> Optional[HHSearchResponse]:
        try:
            data = await self._api.search_vacancies(
                text=keyword,
                area=area,
                page=page,
                per_page=self._config.per_page,
                search_field=self._config.search_field,
            )
            return HHSearchResponse.model_validate(data)
        except Exception as e:
            logger.error("Failed to fetch page %d for '%s': %s", page, keyword, e)
            return None
