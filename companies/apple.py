"""Apple careers adapter.

jobs.apple.com is a React Router app that server-renders its search results
into a hydration blob on the page:

    window.__staticRouterHydrationData.loaderData.search.searchResults

Reading that blob is far more robust than scraping rendered HTML (which broke
and produced "No jobs extracted" alerts) and needs no CSRF token. We load the
search page in the browser and read the structured results, which include the
full job summary (so Apple roles can be CV-scored) and a real post date.

allow_empty_results is True so a future layout change degrades to "no Apple
jobs this run" rather than repeated error notifications.
"""

import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from companies.base import CompanyDefinition

APPLE_BASE = "https://jobs.apple.com"
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

RESULTS_PER_PAGE = 20


def build_search_url(search_url: str, page_num: int) -> str:
    parsed = urlsplit(search_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["page"] = str(page_num)
    return urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))


def _location(raw: dict) -> str:
    locations = raw.get("locations") or []
    if not locations or not isinstance(locations[0], dict):
        return ""
    first = locations[0]
    parts = [first.get("city"), first.get("stateProvince")]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else (first.get("name") or "")


def _normalize(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    position_id = str(raw.get("positionId") or raw.get("id") or "").strip()
    title = str(raw.get("postingTitle") or "").strip()
    if not position_id or not title:
        return None

    slug = raw.get("transformedPostingTitle") or ""
    team = raw.get("team") if isinstance(raw.get("team"), dict) else {}
    team_name = str(team.get("teamName") or "").strip()
    team_code = str(team.get("teamCode") or "").strip()

    url = f"{APPLE_BASE}/en-us/details/{position_id}/{slug}"
    if team_code:
        url += f"?team={team_code}"

    posted = str(raw.get("postDateInGMT") or "")[:10] or str(raw.get("postingDate") or "")
    summary = " ".join(str(raw.get("jobSummary") or "").split())[:8000]

    job = {
        "key": f"apple-{position_id}",
        "job_id": str(raw.get("reqId") or position_id),
        "title": title,
        "team": team_name,
        "location": _location(raw),
        "posted": posted,
        "description": summary,
        "url": url,
    }
    weekly_hours = raw.get("standardWeeklyHours")
    if weekly_hours:
        job["weekly_hours"] = f"{weekly_hours} hrs/week"
    return job


async def fetch_page_html(page, runtime_config, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    print(f"[{runtime_config.slug}] Reading hydrated results: {url}")
    payload = await page.evaluate(
        """async () => {
            for (let i = 0; i < 12; i++) {
                const d = window.__staticRouterHydrationData;
                const s = d && d.loaderData && d.loaderData.search;
                if (s && Array.isArray(s.searchResults)) {
                    return JSON.stringify({
                        searchResults: s.searchResults,
                        totalRecords: s.totalRecords,
                        page: s.page,
                    });
                }
                await new Promise(r => setTimeout(r, 300));
            }
            return JSON.stringify({ searchResults: [], totalRecords: 0, page: 1 });
        }"""
    )
    return payload


def parse_jobs(payload: str) -> list[dict]:
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return []
    jobs = []
    for raw in data.get("searchResults", []) or []:
        job = _normalize(raw)
        if job:
            jobs.append(job)
    return jobs


def get_total_results(payload: str) -> int | None:
    try:
        return json.loads(payload).get("totalRecords")
    except (json.JSONDecodeError, AttributeError):
        return None


def get_total_pages(payload: str) -> int | None:
    total = get_total_results(payload)
    if total is None:
        return None
    if total <= 0:
        return 0
    return max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)


COMPANY = CompanyDefinition(
    slug="apple",
    display_name="Apple",
    default_search_url=APPLE_SEARCH_URL,
    default_max_pages=2,
    default_full_scrape_max_pages=90,
    wait_selectors=(),
    build_search_url=build_search_url,
    parse_jobs=parse_jobs,
    get_total_pages=get_total_pages,
    get_total_results=get_total_results,
    fetch_page_html=fetch_page_html,
    excluded_role_keywords=EXCLUDED_ROLE_KEYWORDS,
    excluded_title_phrases=EXCLUDED_TITLE_PHRASES,
    allow_empty_results=True,
)
