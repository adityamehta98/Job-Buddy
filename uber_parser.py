import json
import math
import re

from bs4 import BeautifulSoup

UBER_BASE_URL = "https://www.uber.com"
UBER_JOB_URL_TEMPLATE = f"{UBER_BASE_URL}/careers/list/{{job_id}}"
UBER_JOB_LINK_RE = re.compile(r"/careers/list/(?P<job_id>\d+)", re.I)
UBER_JOBS_SITE_BASE_URL = "https://jobs.uber.com"
UBER_JOBS_SITE_LINK_RE = re.compile(r"/en/jobs/(?P<job_slug>[^/?#\"'>\s]+)", re.I)
UBER_TOTAL_RESULTS_RE = re.compile(r"([\d,]+)\s+open\s+roles", re.I)
UBER_RESULTS_PER_PAGE = 10


def parse_jobs(html: str) -> list[dict]:
    jobs_from_json = _parse_jobs_from_json(html)
    if jobs_from_json is not None:
        return jobs_from_json
    return _parse_jobs_from_html(html)


def _parse_jobs_from_json(payload: str) -> list[dict] | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    results = _extract_results(data)
    if results is None:
        return None

    jobs = []
    seen_ids = set()
    for raw_job in results:
        job = _normalize_json_job(raw_job)
        if job is None or job["key"] in seen_ids:
            continue
        seen_ids.add(job["key"])
        jobs.append(job)
    return jobs


def _extract_results(data: dict) -> list[dict] | None:
    if not isinstance(data, dict):
        return None

    nested_data = data.get("data", {})
    if isinstance(nested_data, dict):
        nested_results = nested_data.get("results")
        if isinstance(nested_results, list):
            return nested_results
        if isinstance(nested_results, dict):
            nested_items = nested_results.get("items")
            if isinstance(nested_items, list):
                return nested_items

        nested_jobs = nested_data.get("jobs")
        if isinstance(nested_jobs, list):
            return nested_jobs

    top_level_results = data.get("results")
    if isinstance(top_level_results, list):
        return top_level_results

    top_level_jobs = data.get("jobs")
    if isinstance(top_level_jobs, list):
        return top_level_jobs

    return None


def _normalize_json_job(raw_job: dict) -> dict | None:
    if not isinstance(raw_job, dict):
        return None

    job_id = str(raw_job.get("id") or "").strip()
    title = str(raw_job.get("title") or "").strip()
    if not job_id or not title:
        return None

    return {
        "key": job_id,
        "job_id": job_id,
        "title": title,
        "team": _extract_team(raw_job),
        "location": _format_locations(raw_job.get("allLocations") or [raw_job.get("location")]),
        "posted": _extract_posted(raw_job),
        "description": _clean_description(str(raw_job.get("description") or "")),
        "url": UBER_JOB_URL_TEMPLATE.format(job_id=job_id),
    }


def _extract_team(raw_job: dict) -> str:
    for key in ("programAndPlatform", "team", "department"):
        value = str(raw_job.get(key) or "").strip()
        if value:
            return value
    return ""


def _format_locations(locations: list) -> str:
    formatted_locations = []
    for location in locations:
        if not isinstance(location, dict):
            continue

        city = str(location.get("city") or "").strip()
        region = str(location.get("region") or "").strip()
        country_name = str(location.get("countryName") or location.get("country") or "").strip()

        if city and region:
            label = f"{city}, {region}"
        elif city and country_name:
            label = f"{city}, {country_name}"
        elif region and country_name:
            label = f"{region}, {country_name}"
        else:
            label = city or region or country_name

        if label and label not in formatted_locations:
            formatted_locations.append(label)

    if not formatted_locations:
        return ""
    if len(formatted_locations) == 1:
        return formatted_locations[0]
    return f"{formatted_locations[0]}; +{len(formatted_locations) - 1} more"


def _extract_posted(raw_job: dict) -> str:
    for key in ("updatedDate", "creationDate"):
        value = str(raw_job.get(key) or "").strip()
        if value:
            return value.split("T", 1)[0]
    return ""


def _clean_description(description: str) -> str:
    text = re.sub(r"\[[^\]]+\]\(([^)]+)\)", r"\1", description)
    text = re.sub(r"[*_`#>-]+", " ", text)
    text = " ".join(text.split())
    return text[:280].strip()


def _parse_jobs_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    for link in soup.find_all("a", href=UBER_JOB_LINK_RE):
        href = (link.get("href") or "").strip()
        match = UBER_JOB_LINK_RE.search(href)
        if not match:
            continue

        job_id = match.group("job_id")
        title = link.get_text(" ", strip=True)
        if not job_id or not title or job_id in seen_ids:
            continue

        container = _find_job_container(link)
        team, location = _extract_team_and_location(container)

        jobs.append(
            {
                "key": job_id,
                "job_id": job_id,
                "title": title,
                "team": team,
                "location": location,
                "posted": "",
                "description": "",
                "url": f"{UBER_BASE_URL}{href}" if href.startswith("/") else href,
            }
        )
        seen_ids.add(job_id)

    if jobs:
        return jobs

    for link in soup.find_all("a", href=UBER_JOBS_SITE_LINK_RE):
        href = (link.get("href") or "").strip()
        if "/saved-jobs/" in href or href.endswith("#main-content"):
            continue

        match = UBER_JOBS_SITE_LINK_RE.search(href)
        if not match:
            continue

        job_slug = match.group("job_slug")
        if not job_slug or job_slug in seen_ids:
            continue

        title = link.get_text(" ", strip=True)
        if not title:
            continue

        jobs.append(
            {
                "key": job_slug,
                "job_id": job_slug,
                "title": title,
                "team": "",
                "location": "",
                "posted": "",
                "description": "",
                "url": (
                    f"{UBER_JOBS_SITE_BASE_URL}{href}"
                    if href.startswith("/")
                    else href
                ),
            }
        )
        seen_ids.add(job_slug)

    return jobs


def _find_job_container(link):
    container = link
    while container is not None:
        text = " ".join(container.get_text(" ", strip=True).split())
        if "Sub-Team" in text and "Location" in text:
            return container
        container = container.parent
    return link.parent


def _extract_team_and_location(container) -> tuple[str, str]:
    if container is None:
        return "", ""

    text = " ".join(container.get_text(" ", strip=True).split())
    team = ""
    location = ""

    if "Sub-Team" in text:
        team = text.split("Sub-Team", 1)[1].split("Location", 1)[0].strip()
    if "Location" in text:
        location = text.split("Location", 1)[1].split("Role", 1)[0].strip()

    return team, location


def get_total_results(html: str) -> int | None:
    total_from_json = _get_total_results_from_json(html)
    if total_from_json is not None:
        return total_from_json

    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    match = UBER_TOTAL_RESULTS_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _get_total_results_from_json(payload: str) -> int | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    total_results = data.get("data", {}).get("totalResults")
    if isinstance(total_results, int):
        return total_results
    if isinstance(total_results, dict):
        low = total_results.get("low")
        if isinstance(low, int):
            return low
    return None


def get_total_pages(html: str) -> int | None:
    total_results = get_total_results(html)
    if total_results is None:
        return None
    return max(1, math.ceil(total_results / UBER_RESULTS_PER_PAGE))