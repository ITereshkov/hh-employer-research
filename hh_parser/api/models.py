from pydantic import BaseModel, Field
from typing import Optional


class HHEmployerRef(BaseModel):
    id: int
    name: str
    url: Optional[str] = None
    alternate_url: Optional[str] = None
    logo_urls: Optional[dict] = None


class HHArea(BaseModel):
    id: int
    name: str


class HHIndustry(BaseModel):
    id: int
    name: str


class HHSalary(BaseModel):
    from_: Optional[int] = Field(None, alias="from")
    to: Optional[int] = None
    currency: Optional[str] = None
    gross: Optional[bool] = None

    model_config = {"populate_by_name": True}


class HHVacancyBrief(BaseModel):
    id: int
    name: str
    employer: Optional[HHEmployerRef] = None
    area: Optional[HHArea] = None
    salary: Optional[HHSalary] = None
    url: Optional[str] = None
    alternate_url: Optional[str] = None
    published_at: Optional[str] = None
    created_at: Optional[str] = None
    experience: Optional[dict] = None
    employment: Optional[dict] = None
    schedule: Optional[dict] = None


class HHVacancyDetail(HHVacancyBrief):
    description: Optional[str] = None
    professional_roles: list[dict] = []
    industries: list[dict] = []


class HHEmployerDetail(BaseModel):
    id: int
    name: str
    url: Optional[str] = None
    alternate_url: Optional[str] = None
    description: Optional[str] = None
    logo_urls: Optional[dict] = None
    area: Optional[HHArea] = None
    industry: Optional[HHIndustry] = None
    site_url: Optional[str] = None
    trusted: bool = False
    blacklisted: bool = False
    vacancies_count: int = 0
    linked_companies: list[dict] = []


class HHSearchResponse(BaseModel):
    items: list[HHVacancyBrief] = []
    found: int = 0
    pages: int = 0
    page: int = 0
    per_page: int = 0
