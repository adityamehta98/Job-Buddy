import json
import math
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

META_BASE_URL = "https://www.metacareers.com"
META_JOB_LINK_RE = re.compile(r"/profile/job_details/(?P<job_id>\d+)")


def parse_jobs(payload: str) -> list[dict]:
    jobs_from_graphql = _parse_jobs_from_graphql(payload)
    if jobs_from_graphql is not None:
        return jobs_from_graphql
    return _parse_jobs_from_html(payload)


def _parse_jobs_from_graphql(payload: str) -> list[dict] | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    all_jobs = (
        data.get("data", {})
        .get("job_search_with_featured_jobs", {})
        .get("all_jobs")
    )
    if not isinstance(all_jobs, list):
        return None

    jobs = []
    for job in all_jobs:
        job_id = str(job.get("id", "")).strip()
        title = str(job.get("title", "")).strip()
        if not job_id or not title:
            continue

        locations = [value.strip() for value in job.get("locations", []) if value and value.strip()]
        teams = [value.strip() for value in job.get("teams", []) if value and value.strip()]
        sub_teams = [value.strip() for value in job.get("sub_teams", []) if value and value.strip()]

        jobs.append(
            {
                "key": job_id,
                "job_id": job_id,
                "title": title,
                "team": _format_team(teams, sub_teams),
                "location": _format_locations(locations),
                "posted": "",
                "description": "",
                "url": f"{META_BASE_URL}/profile/job_details/{job_id}",
            }
        )

    return jobs


def _parse_jobs_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    for link in soup.find_all("a", href=META_JOB_LINK_RE):
        href = (link.get("href") or "").strip()
        match = META_JOB_LINK_RE.search(href)
        if not match:
            continue

        job_id = match.group("job_id")
        if job_id in seen_ids:
            continue

        title_tag = link.find("h3")
        title = title_tag.get_text(" ", strip=True) if title_tag else link.get_text(" ", strip=True)
        if not title:
            continue

        details = [
            " ".join(span.get_text(" ", strip=True).split())
            for span in link.find_all("span")
            if span.get_text(" ", strip=True)
        ]

        location = details[0] if details else ""
        team = ""
        if len(details) >= 4:
            team = " / ".join(dict.fromkeys(details[1:4]))
        elif len(details) > 1:
            team = " / ".join(dict.fromkeys(details[1:]))

        jobs.append(
            {
                "key": job_id,
                "job_id": job_id,
                "title": title,
                "team": team,
                "location": location,
                "posted": "",
                "description": "",
                "url": urljoin(META_BASE_URL, href),
            }
        )
        seen_ids.add(job_id)

    return jobs


def _format_locations(locations: list[str]) -> str:
    if not locations:
        return ""
    if len(locations) == 1:
        return locations[0]
    return f"{locations[0]} +{len(locations) - 1} locations"


def _format_team(teams: list[str], sub_teams: list[str]) -> str:
    values = []
    for value in teams[:2] + sub_teams[:2]:
        if value and value not in values:
            values.append(value)
    return " / ".join(values)


def get_total_results(payload: str) -> int | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    job_count = data.get("data", {}).get("job_search_with_featured_jobs", {}).get("job_count")
    if isinstance(job_count, int):
        return job_count
    return None


def get_total_pages(payload: str) -> int | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    all_jobs = data.get("data", {}).get("job_search_with_featured_jobs", {}).get("all_jobs")
    if isinstance(all_jobs, list):
        return 1 if all_jobs else 0

    total_results = get_total_results(payload)
    if total_results is None:
        return None
    return max(1, math.ceil(total_results / max(total_results, 1)))