"""Uber careers adapter.

Uber migrated careers to jobs.uber.com. The old www.uber.com API 404s now.
The new public endpoint is:

    GET https://jobs.uber.com/api/jobs/search/?countries=United States&page=<n>

Notes learned from the live API:
  * `countries=United States` filters to US roles country-wide (no city needed).
  * `page` is 1-indexed; pageSize is 10.
  * Results are returned newest-first by DisplayDate (ideal for the 24h window).
  * Each job carries a full HTML Description, so Uber roles can be CV-scored.
  * `department` / `query` are ignored server-side, so titles are filtered
    client-side by the scraper's include-keyword list.
"""

import json
from urllib.parse import quote, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from companies.base import CompanyDefinition

UBER_API = "https://jobs.uber.com/api/jobs/search/"
UBER_BASE = "https://jobs.uber.com"
UBER_SEARCH_URL = "https://jobs.uber.com/en/jobs/?countries=United+States"
UBER_COUNTRY = "United States"
RESULTS_PER_PAGE = 10

EXCLUDED_ROLE_KEYWORDS = (
    "principal", "staff", "director", "sr.",
)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def build_search_url(search_url: str, page_num: int) -> str:
    parsed = urlsplit(search_url)
    return urlunsplit(parsed._replace(fragment=f"page={page_num}"))


def _page_num_from_url(url: str) -> int:
    fragment = urlsplit(url).fragment
    if fragment.startswith("page="):
        try:
            return max(1, int(fragment.split("=", 1)[1]))
        except ValueError:
            return 1
    return 1


def _clean_html(content: str) -> str:
    if not content:
        return ""
    text = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())[:8000]


def _normalize(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    job_id = str(raw.get("Id") or raw.get("Reference") or "").strip()
    title = str(raw.get("Title") or "").strip()
    if not job_id or not title:
        return None

    locations = raw.get("Locations") or []
    loc0 = locations[0] if locations and isinstance(locations[0], dict) else {}
    location = ", ".join(
        part for part in (loc0.get("City"), loc0.get("Country")) if part
    )

    teams = [str(t) for t in (raw.get("Teams") or []) if t]
    team = " / ".join(teams[:2])

    url_path = ""
    for entry in raw.get("Urls") or []:
        if isinstance(entry, dict) and entry.get("IsDefault"):
            url_path = entry.get("Url") or ""
            break
    if not url_path:
        urls = raw.get("Urls") or []
        if urls and isinstance(urls[0], dict):
            url_path = urls[0].get("Url") or ""
    url = f"{UBER_BASE}{url_path}" if url_path else f"{UBER_BASE}/en/jobs/{job_id}/"

    return {
        "key": f"uber-{job_id}",
        "job_id": job_id,
        "title": title,
        "team": team,
        "location": location,
        "posted": str(raw.get("DisplayDate") or "")[:10],
        "description": _clean_html(str(raw.get("Description") or "")),
        "url": url,
    }


async def fetch_page_html(page, runtime_config, url: str) -> str:
    page_num = _page_num_from_url(url)
    api_url = f"{UBER_API}?countries={quote(UBER_COUNTRY)}&page={page_num}"
    print(f"[{runtime_config.slug}] Loading API page {page_num}: {api_url}")
    response = await page.context.request.get(
        api_url,
        headers={"accept": "application/json", "user-agent": BROWSER_UA},
        timeout=30000,
    )
    if not response.ok:
        raise RuntimeError(f"Uber API request failed with status {response.status}")
    return await response.text()


def parse_jobs(payload: str) -> list[dict]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    jobs = []
    for raw in data.get("jobs", []) or []:
        job = _normalize(raw)
        if job:
            jobs.append(job)
    return jobs


def get_total_results(payload: str) -> int | None:
    try:
        return json.loads(payload).get("totalJobs")
    except (json.JSONDecodeError, AttributeError):
        return None


def get_total_pages(payload: str) -> int | None:
    try:
        return json.loads(payload).get("totalPages")
    except (json.JSONDecodeError, AttributeError):
        return None


COMPANY = CompanyDefinition(
    slug="uber",
    display_name="Uber",
    default_search_url=UBER_SEARCH_URL,
    default_max_pages=50,
    default_full_scrape_max_pages=50,
    wait_selectors=(),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    fetch_page_html=fetch_page_html,
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
    allow_empty_results=True,
)
