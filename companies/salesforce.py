from urllib.parse import urlsplit, urlunsplit

from companies.base import CompanyDefinition
from salesforce_parser import get_total_pages, get_total_results, parse_jobs

SALESFORCE_SEARCH_URL = (
    "https://salesforce.wd12.myworkdayjobs.com/en-US/external_career_site"
    "?redirect=/en-US/external_career_site/userHome"
    "&CF_-_REC_-_LRV_-_Job_Posting_Anchor_-_Country_from_Job_Posting_Location_Extended"
    "=bc33aa3152ec42d4995f4791a106ed09"
    "&timeType=0e28126347c3100fe3b402cf26290000"
    "&jobFamilyGroup=14fa3452ec7c1011f90d0002a2100000"
    "&workerSubType=3a910852b2c31010f48d2bbc8b020000"
)

EXCLUDED_ROLE_KEYWORDS = (
    "principal",
    "senior",
    "staff",
    "lead",
    "director",
    "manager",
    "architect",
    "pmts",
    "smts",
    "lmts",
    "sr.",
)

RESULTS_PER_PAGE = 20


def build_search_url(search_url: str, page_num: int) -> str:
    parsed = urlsplit(search_url)
    return urlunsplit(parsed._replace(fragment=f"page={page_num}"))


async def fetch_page_html(page, runtime_config, url: str) -> str:
    parsed = urlsplit(url)
    base_url = urlunsplit(parsed._replace(fragment=""))
    page_num = 1
    if parsed.fragment.startswith("page="):
        try:
            page_num = max(1, int(parsed.fragment.split("=", 1)[1]))
        except ValueError:
            page_num = 1

    print(f"[{runtime_config.slug}] Loading: {base_url} (page {page_num})")
    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)

    for selector in runtime_config.definition.wait_selectors:
        try:
            await page.wait_for_selector(selector, timeout=8000)
            print(f"[{runtime_config.slug}] Results detected via selector: {selector}")
            break
        except Exception:
            continue

    if page_num > 1:
        for target_page in range(2, page_num + 1):
            target_start = (target_page - 1) * RESULTS_PER_PAGE + 1
            await _go_to_page(page, target_page)
            await page.wait_for_timeout(1200)
            await page.wait_for_function(
                "expected => {"
                "  const node = document.querySelector('[data-automation-id=\"jobOutOfText\"]');"
                "  return node && (node.textContent || '').includes(expected);"
                "}",
                arg=str(target_start),
                timeout=10000,
            )

    await page.wait_for_timeout(1200)
    return await page.content()


async def _go_to_page(page, target_page: int) -> None:
    pager = page.get_by_label(f"page {target_page}")
    if await pager.count():
        await pager.first.click()
        return

    current_page = await _current_page_number(page)
    while current_page < target_page:
        next_button = page.get_by_label("next")
        if not await next_button.count():
            raise RuntimeError(f"Unable to find Salesforce pagination control for page {target_page}")
        await next_button.first.click()
        await page.wait_for_timeout(800)
        current_page = await _current_page_number(page)


async def _current_page_number(page) -> int:
    locator = page.locator('[aria-label^="page "][aria-current="true"]')
    if await locator.count():
        label = await locator.first.get_attribute("aria-label")
        if label:
            try:
                return int(label.rsplit(" ", 1)[1])
            except ValueError:
                pass

    text = await page.locator('[data-automation-id="jobOutOfText"]').text_content()
    text = " ".join((text or "").split())
    if not text:
        return 1
    start_index = int(text.split("-", 1)[0].strip())
    return ((start_index - 1) // RESULTS_PER_PAGE) + 1


COMPANY = CompanyDefinition(
    slug="salesforce",
    display_name="Salesforce",
    default_search_url=SALESFORCE_SEARCH_URL,
    default_max_pages=2,
    default_full_scrape_max_pages=6,
    wait_selectors=(
        '[data-automation-id="jobResults"]',
        '[data-automation-id="jobTitle"]',
        '[data-automation-id="jobFoundText"]',
    ),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    fetch_page_html=fetch_page_html,
    full_scrape_posted_strategy="empty",
    regular_scrape_posted_strategy="all-found-today",
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
)