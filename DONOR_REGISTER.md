# DONOR_REGISTER.md

Projects investigated for reusable patterns, API handling, and architecture.

---

## 1. daniyar-sadykov/hh_parser

| Field | Value |
|---|---|
| URL | https://github.com/daniyar-sadykov/hh_parser |
| License | MIT |
| Last Activity | Active (2024+) |
| Language | Python |

**What it solves:** FastAPI service for hh.ru job search with smart filters, deduplication, GPT integration, company contact discovery via 2GIS.

**What is reusable:**
- `HHParser` class using `requests.Session` — clean HTTP pattern
- Pagination loop through HH API pages with configurable delay
- Per-vacancy detail fetching
- Salary filtering logic
- JSON/TXT output patterns

**Verdict: ACCEPTED (patterns)** — Most feature-rich donor. MIT license is clean. We adapted the pagination and rate-limiting patterns but built employer-first logic from scratch since this donor is vacancy-search-centric.

---

## 2. liveinno/hh-vacancy-parser

| Field | Value |
|---|---|
| URL | https://github.com/liveinno/hh-vacancy-parser |
| License | Not specified |
| Last Activity | Active |
| Language | Python |

**What it solves:** CLI/module Python parser for hh.ru vacancies via official public API. Outputs JSON/CSV.

**What is reusable:**
- `_HTMLStripper` class for cleaning HTML from vacancy descriptions (stdlib `html.parser`)
- `HHParser` class with `requests.Session`
- Configurable delay (default 0.5s)
- Pagination: `per_page=100`, max ~20 pages
- UTF-8 BOM and cp1251 CSV encoding variants

**Verdict: ACCEPTED (HTML stripping)** — Clean, minimal, well-structured. The HTML normalization pattern was directly adopted for vacancy description cleaning. No license is a minor concern; we did not copy code, only adopted the approach.

---

## 3. semyon-dev/hh.ru-search

| Field | Value |
|---|---|
| URL | https://github.com/semyon-dev/hh.ru-search |
| License | MIT |
| Last Activity | Oct 2020 (stale) |
| Language | Go |

**What it solves:** Go-based hh.ru vacancy parser indexing into Elasticsearch with REST API.

**What is reusable:**
- `hhAPI` package with `GetByText` (paginated search) and `GetByID` (detail fetch)
- Elasticsearch bulk indexing pattern
- REST API design for search/retrieval

**Verdict: REJECTED** — Go language (project is Python). Stale since 2020. Useful as reference architecture for indexing patterns but not directly reusable.

---

## 4. hukenovs/hh_research (bonus)

| Field | Value |
|---|---|
| URL | https://github.com/hukenovs/hh_research |
| License | Not specified |
| Language | Python |

**What it solves:** Automated hh.ru vacancy search with salary currency conversion and statistical analysis.

**What is reusable:** Salary currency conversion logic; DataFrame-based statistical analysis patterns.

**Verdict: PARTIAL** — Useful reference for salary normalization but not a core parser.

---

## 5. hhru/api (official)

| Field | Value |
|---|---|
| URL | https://github.com/hhru/api |
| License | Documentation / OpenAPI specs |
| Last Activity | Active |

**What it solves:** Official HeadHunter API documentation, OpenAPI specs, auth guides, client libraries.

**Verdict: REFERENCE** — Primary source for API contract. Used to confirm endpoint paths and pagination semantics.

---

## HH API Endpoints Used

| Endpoint | Method | Purpose |
|---|---|---|
| `/employers` | GET | Employer search by text + area |
| `/employers/{id}` | GET | Employer detail (description, industries) |
| `/vacancies` | GET | Vacancy search (filtered by employer_id) |
| `/vacancies/{id}` | GET | Single vacancy detail |
| `/areas` | GET | Geographic areas tree |

## License Compliance

- No code was copied verbatim from any donor.
- Patterns (pagination, rate limiting, HTML stripping) were re-implemented from scratch after studying the approaches.
- All accepted donors have permissive licenses (MIT) or are used for pattern reference only.
- Donors without explicit licenses (liveinno, hukenovs) were used for pattern learning only; no code was copied.
