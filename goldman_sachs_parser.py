import math
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

GOLDMAN_SACHS_BASE_URL = "https://higher.gs.com"
GOLDMAN_SACHS_ROLE_LINK_RE = re.compile(r"/roles/(?P<job_id>\d+)$")
GOLDMAN_SACHS_TOTAL_RE = re.compile(r"Showing\s+\d+\s+of\s+([\d,]+)\s+matches", re.I)

KNOWN_LOCATIONS = (
    "West Palm Beach",
    "Salt Lake City",
    "Newport Beach",
    "San Francisco",
    "Jersey City",
    "Los Angeles",
    "Menlo Park",
    "New York",
    "Washington",
    "Wilmington",
    "Morristown",
    "Minneapolis",
    "Philadelphia",
    "Pittsburgh",
    "Richardson",
    "Atlanta",
    "Boston",
    "Chicago",
    "Dallas",
    "Denver",
    "Detroit",
    "Draper",
    "Houston",
    "Irving",
    "Albany",
    "Miami",
    "Seattle",
    "Troy",
)


def parse_jobs(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    for link in soup.find_all("a", href=GOLDMAN_SACHS_ROLE_LINK_RE):
        href = (link.get("href") or "").strip()
        match = GOLDMAN_SACHS_ROLE_LINK_RE.search(href)
        if not match:
            continue

        job_id = match.group("job_id")
        if job_id in seen_ids:
            continue

        container = _find_job_container(link)
        job = _extract_job(container, link, job_id)
        if job is None:
            continue

        jobs.append(job)
        seen_ids.add(job_id)

    return jobs


def _find_job_container(link):
    container = link
    while container is not None:
        text = container.get_text("\n", strip=True)
        if len(text) > 20 and ("Share" in text or "Save" in text):
            return container
        container = container.parent
    return link.parent


def _extract_job(container, link, job_id: str) -> dict | None:
    title_blob = link.get_text(" ", strip=True)
    if not title_blob:
        return None

    lines = _clean_lines(container.get_text("\n", strip=True).splitlines())
    title, location = _extract_title_and_location(title_blob)
    team = _extract_team(lines, title_blob)
    url = urljoin(GOLDMAN_SACHS_BASE_URL, link.get("href", ""))

    return {
        "key": job_id,
        "job_id": job_id,
        "title": title,
        "team": team,
        "location": location,
        "posted": "",
        "description": "",
        "url": url,
    }


def _extract_title_and_location(title_blob: str) -> tuple[str, str]:
    parts = [part.strip() for part in title_blob.split("·") if part.strip()]
    if len(parts) < 2:
        return title_blob, ""

    prefix = parts[0]
    country = parts[1]
    title, city = _strip_known_location_suffix(prefix)
    if not city:
        return prefix, country
    return title, f"{city}, {country}"


def _strip_known_location_suffix(prefix: str) -> tuple[str, str]:
    normalized_prefix = " ".join(prefix.split())

    for city in KNOWN_LOCATIONS:
        repeated_suffix = f"-{city} {city}"
        if normalized_prefix.endswith(repeated_suffix):
            title = normalized_prefix[: -len(repeated_suffix)].strip(" -,")
            return title, city

        spaced_suffix = f" {city}"
        if normalized_prefix.endswith(spaced_suffix):
            title = normalized_prefix[: -len(spaced_suffix)].strip(" -,")
            return title, city

    return normalized_prefix, ""


def _extract_team(lines: list[str], title_blob: str) -> str:
    for line in lines:
        if line == title_blob:
            continue
        if line in {"Share", "Save"}:
            continue
        if line.startswith("Showing "):
            continue
        return line
    return ""


def _clean_lines(lines: list[str]) -> list[str]:
    cleaned = []
    for raw in lines:
        line = " ".join(raw.split())
        if line:
            cleaned.append(line)
    return cleaned


def get_total_results(html: str) -> int | None:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    match = GOLDMAN_SACHS_TOTAL_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def get_total_pages(html: str) -> int | None:
    total_results = get_total_results(html)
    if total_results is None:
        return None
    return max(1, math.ceil(total_results / 20))