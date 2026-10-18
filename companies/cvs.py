import re
from urllib.parse import urlsplit, urlunsplit

from companies.base import CompanyDefinition
from cvs_parser import get_total_pages, get_total_results, parse_jobs

CVS_SEARCH_URL = (
    "https://jobs.cvshealth.com/us/en/search-results"
    "?keywords=software%20development%20engineer"
)

EXCLUDED_ROLE_KEYWORDS = (
    "principal",
    "staff",
    "senior",
    "lead",
    "manager",
    "director",
    "architect",
    "sr.",
)

RESULTS_PER_PAGE = 10


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

    # Wait for client-side rendering to complete before checking selectors
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass

    for selector in runtime_config.definition.wait_selectors:
        try:
            await page.wait_for_selector(selector, timeout=15000)
            print(f"[{runtime_config.slug}] Results detected via selector: {selector}")
            break
        except Exception:
            continue

    # The CVS jobs site keeps sort in UI state (URL does not change), so set it explicitly.
    sort_select = page.locator('select[aria-label="Sort by:"]')
    if await sort_select.count():
        try:
            await sort_select.first.select_option(label="Recent")
        except Exception:
            await sort_select.first.select_option("Most recent")
        # Wait for job cards to reload after sort change
        try:
            await page.wait_for_selector('a[data-ph-at-id="job-link"]', timeout=8000)
        except Exception:
            pass
        await page.wait_for_timeout(800)

    if page_num > 1:
        for target_page in range(2, page_num + 1):
            target_start = (target_page - 1) * RESULTS_PER_PAGE + 1
            await _go_to_page(page, target_page)
            await page.wait_for_timeout(1200)
            await page.wait_for_function(
                "expected => {"
                "  const node = document.querySelector('[aria-label=\"Search results\"]');"
                "  return node && (node.textContent || '').includes(expected);"
                "}",
                arg=f"{target_start}-",
                timeout=10000,
            )

    await page.wait_for_timeout(1200)
    return await page.content()


async def _go_to_page(page, target_page: int) -> None:
    pager = page.get_by_role("button", name=f"Page {target_page}")
    if await pager.count():
        await pager.first.click()
        return

    current_page = await _current_page_number(page)
    while current_page < target_page:
        next_button = page.get_by_role("button", name="Next")
        if not await next_button.count():
            raise RuntimeError(f"Unable to find CVS pagination control for page {target_page}")
        await next_button.first.click()
        await page.wait_for_timeout(800)
        current_page = await _current_page_number(page)


async def _current_page_number(page) -> int:
    locator = page.locator('[aria-label^="Page "][aria-current="true"]')
    if await locator.count():
        label = await locator.first.get_attribute("aria-label")
        if label:
            try:
                return int(label.rsplit(" ", 1)[1])
            except ValueError:
                pass

    text = await page.get_by_label("Search results").text_content()
    text = " ".join((text or "").split())
    if not text:
        return 1
    match = re.search(r"(\d+)\s*-\s*(\d+)\s*of", text)
    if not match:
        return 1
    start_index = int(match.group(1))
    return ((start_index - 1) // RESULTS_PER_PAGE) + 1


COMPANY = CompanyDefinition(
    slug="cvs",
    display_name="CVS Health",
    default_search_url=CVS_SEARCH_URL,
    default_max_pages=2,
    default_full_scrape_max_pages=6,
    wait_selectors=(
        'a[data-ph-at-id="job-link"]',
        'h2:has-text("Showing")',
        'h3 a[href*="/us/en/job/"]',
    ),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    fetch_page_html=fetch_page_html,
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
)
