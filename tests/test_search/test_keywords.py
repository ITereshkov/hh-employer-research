from hh_parser.search.keywords import (
    build_search_queries,
    classify_vacancy,
    VacancyCategory,
    KEYWORD_GROUPS,
)


class TestKeywords:
    def test_build_search_queries_returns_tuples(self):
        queries = build_search_queries()
        assert len(queries) > 0
        for term, category in queries:
            assert isinstance(term, str)
            assert isinstance(category, VacancyCategory)

    def test_keyword_groups_have_terms(self):
        for group in KEYWORD_GROUPS:
            assert len(group.terms) > 0
            assert isinstance(group.category, VacancyCategory)

    def test_classify_vacancy_aho_management(self):
        cat, kw = classify_vacancy("Начальник АХО")
        assert cat == VacancyCategory.AHO_MANAGEMENT
        assert "АХО" in kw.lower() or "начальник" in kw.lower()

    def test_classify_vacancy_facility(self):
        cat, kw = classify_vacancy("Facility Manager")
        assert cat == VacancyCategory.FACILITY_OPS

    def test_classify_vacancy_admin_support(self):
        cat, kw = classify_vacancy("Заведующий хозяйством")
        assert cat == VacancyCategory.ADMIN_SUPPORT

    def test_classify_vacancy_other(self):
        cat, kw = classify_vacancy("Python разработчик")
        assert cat == VacancyCategory.OTHER
        assert kw == ""

    def test_classify_vacancy_case_insensitive(self):
        cat, _ = classify_vacancy("НАЧАЛЬНИК АХО")
        assert cat == VacancyCategory.AHO_MANAGEMENT
