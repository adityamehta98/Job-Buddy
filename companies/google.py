from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from companies.base import CompanyDefinition
from google_parser import get_total_pages, get_total_results, parse_jobs

GOOGLE_SEARCH_URL = (
    "https://www.google.com/about/careers/applications/jobs/results/"
    "?location=United%20States"
    "&target_level=MID"
    "&target_level=EARLY"
    "&employment_type=FULL_TIME"
    "&sort_by=date"
    "&q=%22Software%20Engineer%22"
)

EXCLUDED_ROLE_KEYWORDS = (
    "principal",
    "staff",
    "senior",
    "Senior",
    "sr.",
    "manager",
    "lead",
    "director",
    "III",
)


def build_search_url(search_url: str, page_num: int) -> str:
    parsed = urlsplit(search_url)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_params = [(key, value) for key, value in params if key != "page"]
    filtered_params.append(("page", str(page_num)))
    return urlunsplit(parsed._replace(query=urlencode(filtered_params, doseq=True)))


COMPANY = CompanyDefinition(
    slug="google",
    display_name="Google",
    default_search_url=GOOGLE_SEARCH_URL,
    default_max_pages=3,
    default_full_scrape_max_pages=25,
    wait_selectors=(
        'a[href*="/about/careers/applications/jobs/results/"]',
        'text=Jobs search results',
        'text=jobs matched',
    ),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
)
