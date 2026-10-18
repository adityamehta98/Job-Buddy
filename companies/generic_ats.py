"""Generic ATS adapters + career-URL resolver.

Lets you monitor almost any company by dropping a Name + careers URL into
``custom_companies.json``. Supports the major hosted ATS platforms that expose
a public JSON API: Greenhouse, Lever, Ashby, and SmartRecruiters.

For each custom company we:
  1. Resolve which ATS it uses and the board token (from the URL, or by
     sniffing the careers page HTML at runtime, or from an explicit override).
  2. Hit that ATS's public JSON API (full job list + descriptions in one call).
  3. Normalise every posting into the project's standard job dict:
       {key, job_id, title, team, location, posted, description, url}

No Playwright DOM scraping and no per-company parser needed — one file covers
them all. These adapters run inside the existing scrape flow by reusing the
browser context's request client (see ``fetch_page_html``).
"""

from __future__ import annotations

import json
import re
from html import unescape
from datetime import datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from companies.base import CompanyDefinition

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Max characters of job description we keep (used later for CV match scoring).
MAX_DESCRIPTION_CHARS = 8000


# --------------------------------------------------------------------------- #
# ATS detection / resolution
# --------------------------------------------------------------------------- #

# Patterns that pull the board token straight out of a known ATS URL.
_URL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greenhouse", re.compile(r"(?:boards(?:-api)?|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=|v1/boards/)?([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("lever", re.compile(r"(?:jobs\.lever\.co|api\.lever\.co/v0/postings)/([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("ashby", re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com/(?:v1/companies/)?([a-z0-9][a-z0-9\-_]*)", re.I)),
)

# Patterns to look for inside the HTML of a *custom-domain* careers page.
_SNIFF_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("greenhouse", re.compile(r"(?:job-boards|boards)\.greenhouse\.io/([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?for=([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("lever", re.compile(r"(?:jobs|api)\.lever\.co/(?:v0/postings/)?([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("ashby", re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([a-z0-9][a-z0-9\-_]*)", re.I)),
    ("smartrecruiters", re.compile(r"api\.smartrecruiters\.com/v1/companies/([a-z0-9][a-z0-9\-_]*)", re.I)),
)

# Hosts that are the ATS itself (token lives in the path) vs. a custom domain.
_KNOWN_ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com")


def resolve_from_url(url: str) -> tuple[str | None, str | None]:
    """Best-effort (ats, token) directly from a URL's structure."""
    host = (urlsplit(url).hostname or "").lower()
    if any(h in host for h in _KNOWN_ATS_HOSTS):
        for ats, pattern in _URL_PATTERNS:
            match = pattern.search(url)
            if match:
                token = match.group(1)
                if token and token.lower() not in {"v1", "boards", "embed", "www", "posting-api"}:
                    return ats, token
    return None, None


def sniff_from_html(html: str) -> tuple[str | None, str | None]:
    """Look inside a careers page's HTML for an embedded ATS board token."""
    for ats, pattern in _SNIFF_PATTERNS:
        match = pattern.search(html)
        if match:
            return ats, match.group(1)
    return None, None


def api_url_for(ats: str, token: str) -> str:
    if ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    if ats == "lever":
        return f"https://api.lever.co/v0/postings/{token}?mode=json"
    if ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
    if ats == "smartrecruiters":
        return f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100"
    raise ValueError(f"Unsupported ATS '{ats}'")


# --------------------------------------------------------------------------- #
# Per-ATS parsers  ->  standard job dicts
# --------------------------------------------------------------------------- #

def _clean_html(content: str) -> str:
    if not content:
        return ""
    # Some boards return HTML entities containing another layer of markup.
    # Decode before stripping tags so the detail view never shows raw <div>s.
    text = BeautifulSoup(unescape(content), "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())[:MAX_DESCRIPTION_CHARS]


def _iso_date(value) -> str:
    """Normalise assorted timestamp shapes to YYYY-MM-DD (best effort)."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e12 else value
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
        text = str(value)
        return text[:10]
    except (ValueError, OSError, OverflowError):
        return ""


def _parse_greenhouse(token: str, payload: str) -> list[dict]:
    data = json.loads(payload)
    jobs = []
    for raw in data.get("jobs", []) or []:
        job_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not job_id or not title:
            continue
        location = ""
        if isinstance(raw.get("location"), dict):
            location = str(raw["location"].get("name") or "").strip()
        departments = [
            str(d.get("name") or "").strip()
            for d in raw.get("departments") or []
            if isinstance(d, dict)
        ]
        jobs.append({
            "key": f"gh-{job_id}",
            "job_id": job_id,
            "title": title,
            "team": " / ".join([d for d in departments if d][:2]),
            "location": location,
            "posted": _iso_date(raw.get("updated_at") or raw.get("first_published")),
            "description": _clean_html(str(raw.get("content") or "")),
            "url": str(raw.get("absolute_url") or "").strip(),
        })
    return jobs


def _parse_lever(token: str, payload: str) -> list[dict]:
    data = json.loads(payload)
    if not isinstance(data, list):
        return []
    jobs = []
    for raw in data:
        job_id = str(raw.get("id") or "").strip()
        title = str(raw.get("text") or "").strip()
        if not job_id or not title:
            continue
        categories = raw.get("categories") or {}
        jobs.append({
            "key": f"lever-{job_id}",
            "job_id": job_id,
            "title": title,
            "team": str(categories.get("team") or categories.get("department") or "").strip(),
            "location": str(categories.get("location") or "").strip(),
            "posted": _iso_date(raw.get("createdAt")),
            "description": _clean_html(str(raw.get("descriptionPlain") or raw.get("description") or "")),
            "url": str(raw.get("hostedUrl") or raw.get("applyUrl") or "").strip(),
        })
    return jobs


def _parse_ashby(token: str, payload: str) -> list[dict]:
    data = json.loads(payload)
    jobs = []
    for raw in data.get("jobs", []) or []:
        job_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not job_id or not title:
            continue
        jobs.append({
            "key": f"ashby-{job_id}",
            "job_id": job_id,
            "title": title,
            "team": str(raw.get("department") or raw.get("team") or "").strip(),
            "location": str(raw.get("location") or "").strip(),
            "posted": _iso_date(raw.get("publishedAt") or raw.get("updatedAt")),
            "description": _clean_html(str(raw.get("descriptionPlain") or raw.get("descriptionHtml") or "")),
            "url": str(raw.get("jobUrl") or raw.get("applyUrl") or "").strip(),
        })
    return jobs


def _parse_smartrecruiters(token: str, payload: str) -> list[dict]:
    data = json.loads(payload)
    jobs = []
    for raw in data.get("content", []) or []:
        job_id = str(raw.get("id") or "").strip()
        title = str(raw.get("name") or "").strip()
        if not job_id or not title:
            continue
        loc = raw.get("location") or {}
        location = ", ".join(
            part for part in (loc.get("city"), loc.get("region"), loc.get("country")) if part
        )
        department = ""
        if isinstance(raw.get("department"), dict):
            department = str(raw["department"].get("label") or "").strip()
        jobs.append({
            "key": f"sr-{job_id}",
            "job_id": job_id,
            "title": title,
            "team": department,
            "location": location,
            "posted": _iso_date(raw.get("releasedDate") or raw.get("createdOn")),
            "description": "",  # SmartRecruiters needs a per-posting fetch for full text
            "url": f"https://jobs.smartrecruiters.com/{token}/{job_id}",
        })
    return jobs


_PARSERS = {
    "greenhouse": _parse_greenhouse,
    "lever": _parse_lever,
    "ashby": _parse_ashby,
    "smartrecruiters": _parse_smartrecruiters,
}

SUPPORTED_ATS = tuple(_PARSERS)


def parse_ats(ats: str, token: str, payload: str) -> list[dict]:
    parser = _PARSERS.get(ats)
    if not parser:
        raise ValueError(f"Unsupported ATS '{ats}'")
    return parser(token, payload)


# --------------------------------------------------------------------------- #
# Dynamic CompanyDefinition factory
# --------------------------------------------------------------------------- #

def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "company"


def build_custom_company(
    name: str,
    url: str,
    *,
    ats: str | None = None,
    token: str | None = None,
    included_role_keywords: tuple[str, ...] = (),
    excluded_role_keywords: tuple[str, ...] = (),
    excluded_title_phrases: tuple[str, ...] = (),
) -> CompanyDefinition:
    """Create a CompanyDefinition for a custom company from Name + URL."""
    # Shared, mutable resolution state so fetch + parse agree on the ATS.
    resolved: dict[str, str | None] = {"ats": ats, "token": token}
    if not (resolved["ats"] and resolved["token"]):
        guessed_ats, guessed_token = resolve_from_url(url)
        resolved["ats"] = resolved["ats"] or guessed_ats
        resolved["token"] = resolved["token"] or guessed_token

    async def _request_text(page, target_url: str) -> str:
        response = await page.context.request.get(
            target_url, headers={"user-agent": BROWSER_UA}, timeout=30000
        )
        if not response.ok:
            raise RuntimeError(f"{name}: request to {target_url} failed ({response.status})")
        return await response.text()

    async def fetch_page_html(page, runtime_config, _url: str) -> str:
        if not (resolved["ats"] and resolved["token"]):
            # Custom domain: sniff the careers page for an embedded ATS token.
            html = await _request_text(page, url)
            a, t = sniff_from_html(html)
            resolved["ats"], resolved["token"] = a, t
        if not (resolved["ats"] and resolved["token"]):
            raise RuntimeError(
                f"{name}: could not auto-detect the ATS for {url}. "
                f'Add explicit "ats" and "token" in custom_companies.json '
                f"(supported: {', '.join(SUPPORTED_ATS)})."
            )
        api = api_url_for(resolved["ats"], resolved["token"])
        print(f"[{slugify(name)}] ATS={resolved['ats']} token={resolved['token']}")
        return await _request_text(page, api)

    def parse_jobs(payload: str) -> list[dict]:
        if not (resolved["ats"] and resolved["token"]):
            return []
        return parse_ats(resolved["ats"], resolved["token"], payload)

    def get_total_results(payload: str) -> int | None:
        try:
            return len(parse_jobs(payload))
        except (ValueError, json.JSONDecodeError):
            return None

    def get_total_pages(payload: str) -> int | None:
        return 1 if get_total_results(payload) else 0

    return CompanyDefinition(
        slug=slugify(name),
        display_name=name,
        default_search_url=url,
        default_max_pages=1,
        default_full_scrape_max_pages=1,
        wait_selectors=(),
        build_search_url=lambda search_url, page_num: search_url,
        parse_jobs=parse_jobs,
        get_total_pages=get_total_pages,
        get_total_results=get_total_results,
        fetch_page_html=fetch_page_html,
        included_role_keywords=included_role_keywords,
        excluded_role_keywords=excluded_role_keywords,
        excluded_title_phrases=excluded_title_phrases,
        allow_empty_results=True,
    )
