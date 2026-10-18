from companies.base import CompanyDefinition
from lyft_parser import get_total_pages, get_total_results, parse_jobs

LYFT_API_URL = "https://api.careerpuck.com/v1/public/job-boards/lyft"
LYFT_SEARCH_URL = "https://app.careerpuck.com/job-board/lyft"

EXCLUDED_ROLE_KEYWORDS = (
    "engineering manager",
    "gestionnaire en ingénierie",
    "head of",
    "senior",
    "staff",
)


def build_search_url(search_url: str, page_num: int) -> str:
    return search_url


async def fetch_page_html(page, runtime_config, url: str) -> str:
    print(f"[{runtime_config.slug}] Loading API: {LYFT_API_URL}")
    response = await page.context.request.get(
        LYFT_API_URL,
        headers={"user-agent": "Mozilla/5.0"},
        timeout=30000,
    )
    if not response.ok:
        raise RuntimeError(f"Lyft API request failed with status {response.status}")
    return await response.text()


COMPANY = CompanyDefinition(
    slug="lyft",
    display_name="Lyft",
    default_search_url=LYFT_SEARCH_URL,
    default_max_pages=1,
    default_full_scrape_max_pages=1,
    wait_selectors=(
        'a[href*="/job-board/lyft/job/"]',
        'text=job postings found',
        'text=Software Engineering',
    ),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    fetch_page_html=fetch_page_html,
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
)
