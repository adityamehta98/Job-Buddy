from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from amazon_parser import get_total_pages, get_total_results, parse_jobs
from companies.base import CompanyDefinition

AMAZON_SEARCH_URL = (
    "https://www.amazon.jobs/en/search"
    "?offset=0"
    "&result_limit=10"
    "&sort=recent"
    "&category%5B%5D=software-development"
    "&job_type%5B%5D=Full-Time"
    "&country%5B%5D=USA"
    "&distanceType=Mi"
    "&radius=24km"
    "&industry_experience=one_to_three_years"
    "&is_manager%5B%5D=0"
    "&latitude="
    "&longitude="
    "&loc_group_id="
    "&loc_query="
    "&base_query="
    "&city="
    "&country="
    "&region="
    "&county="
    "&query_options="
)

EXCLUDED_ROLE_KEYWORDS = (
    "principal",
    "senior",
    "staff",
    "manager",
    "director",
    "lead",
    "sr",
)


def build_search_url(search_url: str, page_num: int) -> str:
    parsed = urlsplit(search_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["result_limit"] = params.get("result_limit", "10")
    page_size = int(params["result_limit"])
    params["offset"] = str(max(page_num - 1, 0) * page_size)
    return urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))


COMPANY = CompanyDefinition(
    slug="amazon",
    display_name="Amazon",
    default_search_url=AMAZON_SEARCH_URL,
    default_max_pages=4,
    default_full_scrape_max_pages=45,
    wait_selectors=(
        "text=Job ID:",
        "text=Basic qualifications",
        "a[href*='/en/jobs/']",
    ),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
)