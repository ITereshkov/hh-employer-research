import logging
from dataclasses import dataclass, field
from typing import Optional

from ..api.client import HHApiClient
from ..api.models import HHVacancyBrief
from ..db.repositories import EmployerRepository, VacancyRepository, EmployerVacancyRepository
from .keywords import VacancyCategory

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEmployer:
    employer_id: int
    name: str
    url: Optional[str]
    alternate_url: Optional[str]
    area_id: Optional[int]
    area_name: Optional[str]
    vacancy_count: int = 0
    categories: set[str] = field(default_factory=set)
    is_new: bool = False


class EmployerExtractor:
    def __init__(
        self,
        employer_repo: EmployerRepository,
        vacancy_repo: VacancyRepository,
        ev_repo: EmployerVacancyRepository,
        api_client: HHApiClient,
    ):
        self._employer_repo = employer_repo
        self._vacancy_repo = vacancy_repo
        self._ev_repo = ev_repo
        self._api = api_client

    async def extract_from_vacancies(
        self,
        vacancies: list[tuple[dict, str, str]],
    ) -> list[ExtractedEmployer]:
        employers_map: dict[int, ExtractedEmployer] = {}

        for vac_dict, keyword, category in vacancies:
            emp_ref = vac_dict.get("employer")
            if not emp_ref or not emp_ref.get("id"):
                continue

            eid = emp_ref["id"]
            area = vac_dict.get("area") or {}

            if eid not in employers_map:
                existing = self._employer_repo.get_by_id(eid)
                employers_map[eid] = ExtractedEmployer(
                    employer_id=eid,
                    name=emp_ref.get("name", ""),
                    url=emp_ref.get("url"),
                    alternate_url=emp_ref.get("alternate_url"),
                    area_id=area.get("id"),
                    area_name=area.get("name"),
                    is_new=existing is None,
                )

            ext = employers_map[eid]
            ext.vacancy_count += 1
            ext.categories.add(category)

            vac_dict["area_id"] = area.get("id")
            vac_dict["area_name"] = area.get("name")
            salary = vac_dict.get("salary") or {}
            vac_dict["salary_from"] = salary.get("from")
            vac_dict["salary_to"] = salary.get("to")
            vac_dict["salary_currency"] = salary.get("currency")
            exp = vac_dict.get("experience") or {}
            vac_dict["experience_id"] = exp.get("id")
            vac_dict["experience_name"] = exp.get("name")
            emp = vac_dict.get("employment") or {}
            vac_dict["employment_type"] = emp.get("name")
            sched = vac_dict.get("schedule") or {}
            vac_dict["schedule_type"] = sched.get("name")

            self._vacancy_repo.upsert(vac_dict, keyword, category)
            self._employer_repo.upsert_from_vacancy(emp_ref)
            self._ev_repo.link(eid, vac_dict["id"], keyword)

        for ext in employers_map.values():
            self._employer_repo.update_vacancy_count(ext.employer_id)

        return list(employers_map.values())

    async def fetch_full_details(self, employer_ids: list[int]) -> list[dict]:
        results = []
        for eid in employer_ids:
            try:
                data = await self._api.get_employer(eid)
                employer_data = {
                    "id": data["id"],
                    "name": data.get("name", ""),
                    "url": data.get("url"),
                    "alternate_url": data.get("alternate_url"),
                    "description": data.get("description"),
                    "logo_url": None,
                    "area_id": data.get("area", {}).get("id") if data.get("area") else None,
                    "area_name": data.get("area", {}).get("name") if data.get("area") else None,
                    "industry_id": data.get("industry", {}).get("id") if data.get("industry") else None,
                    "industry_name": data.get("industry", {}).get("name") if data.get("industry") else None,
                    "raw_json": data,
                }
                logo_urls = data.get("logo_urls")
                if logo_urls:
                    employer_data["logo_url"] = logo_urls.get("original") or logo_urls.get("90")
                self._employer_repo.upsert(employer_data)
                results.append(employer_data)
            except Exception as e:
                logger.error("Failed to fetch employer %d: %s", eid, e)
        return results
