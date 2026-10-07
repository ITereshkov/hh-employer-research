from dataclasses import dataclass
from enum import Enum


class VacancyCategory(str, Enum):
    AHO_MANAGEMENT = "aho_management"
    FACILITY_OPS = "facility_ops"
    ADMIN_SUPPORT = "admin_support"
    MAINTENANCE = "maintenance"
    OTHER = "other"


@dataclass
class KeywordGroup:
    category: VacancyCategory
    terms: list[str]


KEYWORD_GROUPS: list[KeywordGroup] = [
    KeywordGroup(
        category=VacancyCategory.AHO_MANAGEMENT,
        terms=[
            "начальник АХО",
            "руководитель АХО",
            "заместитель директора по АХР",
            "административный директор",
            "директор по административно-хозяйственной части",
            "начальник административно-хозяйственного отдела",
            "заместитель директора по административно-хозяйственной работе",
        ],
    ),
    KeywordGroup(
        category=VacancyCategory.FACILITY_OPS,
        terms=[
            "facility manager",
            "менеджер по эксплуатации",
            "начальник отдела эксплуатации",
            "управляющий эксплуатацией",
            "инженер по эксплуатации зданий",
            "начальник службы эксплуатации",
        ],
    ),
    KeywordGroup(
        category=VacancyCategory.ADMIN_SUPPORT,
        terms=[
            "АХО",
            "административно-хозяйственная",
            "административно-хозяйственный",
            "хозяйственная служба",
            "заведующий хозяйством",
        ],
    ),
    KeywordGroup(
        category=VacancyCategory.MAINTENANCE,
        terms=[
            "главный инженер по эксплуатации",
            "технический директор по эксплуатации",
        ],
    ),
]


def build_search_queries() -> list[tuple[str, VacancyCategory]]:
    queries: list[tuple[str, VacancyCategory]] = []
    for group in KEYWORD_GROUPS:
        for term in group.terms:
            queries.append((term, group.category))
    return queries


def classify_vacancy(name: str, description: str = "") -> tuple[VacancyCategory, str]:
    text = (name + " " + (description or "")).lower()
    for group in KEYWORD_GROUPS:
        for term in group.terms:
            if term.lower() in text:
                return group.category, term
    return VacancyCategory.OTHER, ""
