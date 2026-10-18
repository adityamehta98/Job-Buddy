import asyncio

from companies.base import CompanyDefinition
from meta_parser import get_total_pages, get_total_results, parse_jobs

META_SEARCH_URL = (
    "https://www.metacareers.com/jobsearch/"
    "?sort_by_new=true"
    "&roles[0]=Full%20time%20employment"
    "&offices[0]=Irvine%2C%20CA"
    "&offices[1]=Newark%2C%20CA"
    "&offices[2]=Fremont%2C%20CA"
    "&offices[3]=Pasadena%2C%20CA"
    "&offices[4]=San%20Diego%2C%20CA"
    "&offices[5]=San%20Mateo%2C%20CA"
    "&offices[6]=Sausalito%2C%20CA"
    "&offices[7]=Menlo%20Park%2C%20CA"
    "&offices[8]=Sunnyvale%2C%20CA"
    "&offices[9]=Cambridge%2C%20MA"
    "&offices[10]=Foster%20City%2C%20CA"
    "&offices[11]=Los%20Angeles%2C%20CA"
    "&offices[12]=Santa%20Clara%2C%20CA"
    "&offices[13]=Mountain%20View%2C%20CA"
    "&offices[14]=San%20Francisco%2C%20CA"
    "&offices[15]=Northridge%2C%20CA"
    "&offices[16]=Boston%2C%20MA"
    "&offices[17]=Redmond%2C%20WA"
    "&offices[18]=Seattle%2C%20WA"
    "&offices[19]=Bellevue%2C%20WA"
    "&offices[20]=New%20York%2C%20NY"
    "&offices[21]=Austin%2C%20TX"
    "&offices[22]=Temple%2C%20TX"
    "&offices[23]=El%20Paso%2C%20TX"
    "&offices[24]=Garland%2C%20TX"
    "&offices[25]=Houston%2C%20TX"
    "&offices[26]=Fort%20Worth%2C%20TX"
    "&offices[27]=Chicago%2C%20IL"
    "&offices[28]=Miami%2C%20Florida"
    "&offices[29]=Mesa%2C%20AZ"
    "&offices[30]=Chandler%2C%20AZ"
    "&offices[31]=Atlanta%2C%20GA"
    "&offices[32]=North%20America"
)

EXCLUDED_ROLE_KEYWORDS = (
    "principal",
    "senior",
    "staff",
    "lead",
    "director",
    "manager",
)


def build_search_url(search_url: str, page_num: int) -> str:
    return search_url


async def fetch_page_html(page, runtime_config, url: str) -> str:
    print(f"[{runtime_config.slug}] Loading: {url}")
    payload = None

    async def capture_graphql_response(response) -> None:
        nonlocal payload
        if payload is not None:
            return
        if response.request.method != "POST" or "/graphql" not in response.url:
            return
        try:
            text = await response.text()
        except Exception:
            return
        if '"job_search_with_featured_jobs"' in text and '"all_jobs"' in text:
            payload = text

    page.on("response", lambda response: asyncio.create_task(capture_graphql_response(response)))
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    for selector in runtime_config.definition.wait_selectors:
        try:
            await page.wait_for_selector(selector, timeout=8000)
            print(f"[{runtime_config.slug}] Results detected via selector: {selector}")
            break
        except Exception:
            continue

    for _ in range(12):
        if payload is not None:
            return payload
        await page.wait_for_timeout(500)

    return await page.content()


COMPANY = CompanyDefinition(
    slug="meta",
    display_name="Meta",
    default_search_url=META_SEARCH_URL,
    default_max_pages=1,
    default_full_scrape_max_pages=1,
    wait_selectors=(
        'a[href*="/profile/job_details/"]',
        'main',
    ),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    fetch_page_html=fetch_page_html,
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
)