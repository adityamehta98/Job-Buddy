from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from companies.base import CompanyDefinition
from parser import get_total_pages, get_total_results, parse_jobs

APPLE_SEARCH_URL = (
    "https://jobs.apple.com/en-us/search"
        "?location=united-states-USA"
    "&team=apps-and-frameworks-SFTWR-AF+cloud-and-infrastructure-SFTWR-CLD"
    "+core-operating-systems-SFTWR-COS+devops-and-site-reliability-SFTWR-DSR"
    "+engineering-project-management-SFTWR-EPM"
    "+information-systems-and-technology-SFTWR-ISTECH"
    "+machine-learning-and-ai-SFTWR-MCHLN+security-and-privacy-SFTWR-SEC"
    "+software-quality-automation-and-tools-SFTWR-SQAT"
    "+wireless-software-SFTWR-WSFT"
)

EXCLUDED_ROLE_KEYWORDS = (
    "principal",
    "staff",
    "senior",
    "sr.",
    "manager",
    "lead",
    "director",
)

EXCLUDED_TITLE_PHRASES = (
    "machine learning manager",
    "engineering manager",
    "program manager",
)


def build_search_url(search_url: str, page_num: int) -> str:
    parsed = urlsplit(search_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["page"] = str(page_num)
    return urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))


COMPANY = CompanyDefinition(
    slug="apple",
    display_name="Apple",
    default_search_url=APPLE_SEARCH_URL,
    default_max_pages=2,
    default_full_scrape_max_pages=90,
    wait_selectors=(
        "text=Role Number",
        "text=Weekly Hours",
        "h2",
        "li",
    ),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
    excluded_title_phrases=EXCLUDED_TITLE_PHRASES,
)