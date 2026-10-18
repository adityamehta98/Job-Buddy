import re
import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup

LYFT_BASE_URL = "https://app.careerpuck.com"
LYFT_JOB_LINK_RE = re.compile(r"/job-board/lyft/job/(?P<job_id>\d+)")
LYFT_TOTAL_RESULTS_RE = re.compile(r"(?P<count>\d+)\s+job postings found", re.IGNORECASE)
LYFT_DEPARTMENT_NAME = "Software Engineering"
ALLOWED_LOCATIONS = {
    "new york, ny",
    "san francisco, ca",
    "seattle, wa",
}


def parse_jobs(payload: str) -> list[dict]:
    jobs_from_json = _parse_jobs_from_json(payload)
    if jobs_from_json is not None:
        return jobs_from_json

    return _parse_jobs_from_html(payload)


def _parse_jobs_from_json(payload: str) -> list[dict] | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    raw_jobs = data.get("jobs")
    if not isinstance(raw_jobs, list):
        return None

    jobs = []
    seen_ids = set()
    for raw_job in raw_jobs:
        job = _normalize_json_job(raw_job)
        if job is None or job["key"] in seen_ids:
            continue
        seen_ids.add(job["key"])
        jobs.append(job)
    return jobs


def _normalize_json_job(raw_job: dict) -> dict | None:
    if not isinstance(raw_job, dict):
        return None

    departments = [
        department.get("name", "").strip()
        for department in raw_job.get("departments") or []
        if isinstance(department, dict)
    ]
    if LYFT_DEPARTMENT_NAME not in departments:
        return None

    office_names = [
        office.get("name", "").strip()
        for office in raw_job.get("offices") or []
        if isinstance(office, dict) and office.get("name")
    ]
    location = str(raw_job.get("location") or "").strip()
    if not _is_allowed_location(location):
        return None

    job_id = str(raw_job.get("atsSourceId") or raw_job.get("requisitionId") or "").strip()
    title = str(raw_job.get("title") or "").strip()
    if not job_id or not title:
        return None

    public_url = str(raw_job.get("publicUrl") or "").strip()
    return {
        "key": job_id,
        "job_id": job_id,
        "title": title,
        "team": " / ".join(departments[:2]),
        "location": location or ", ".join(office_names),
        "posted": str(raw_job.get("postedAt") or "").strip(),
        "description": _clean_description(str(raw_job.get("content") or "")),
        "url": public_url or f"{LYFT_BASE_URL}/job-board/lyft/job/{job_id}",
    }


def _clean_description(content: str) -> str:
    text = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())[:280]


def _parse_jobs_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    for link in soup.find_all("a", href=LYFT_JOB_LINK_RE):
        href = (link.get("href") or "").strip()
        match = LYFT_JOB_LINK_RE.search(href)
        if not match:
            continue

        job_id = match.group("job_id")
        if job_id in seen_ids:
            continue

        title, location, team = _extract_card_fields(link.get_text("\n", strip=True))
        if not title or not _is_allowed_location(location):
            continue

        jobs.append(
            {
                "key": job_id,
                "job_id": job_id,
                "title": title,
                "team": team,
                "location": location,
                "posted": "",
                "description": "",
                "url": urljoin(LYFT_BASE_URL, href),
            }
        )
        seen_ids.add(job_id)

    return jobs


def _extract_card_fields(card_text: str) -> tuple[str, str, str]:
    lines = [" ".join(line.split()) for line in card_text.splitlines() if line.strip()]
    if not lines:
        return "", "", ""

    title = lines[0]
    details_line = next((line for line in lines[1:] if line.lower() != "learn more"), "")
    if not details_line:
        return title, "", ""

    location, separator, team = details_line.partition(" - ")
    if not separator:
        return title, details_line, ""
    return title, location.strip(), team.strip()


def _is_allowed_location(location: str) -> bool:
    normalized_location = " ".join(location.strip().lower().split())
    return normalized_location in ALLOWED_LOCATIONS


def get_total_results(payload: str) -> int | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        return len(parse_jobs(payload))

    match = LYFT_TOTAL_RESULTS_RE.search(BeautifulSoup(payload, "lxml").get_text(" ", strip=True))
    if not match:
        return None
    return int(match.group("count"))


def get_total_pages(payload: str) -> int | None:
    total_results = get_total_results(payload)
    if total_results is None:
        return 1 if parse_jobs(payload) else 0
    return 1 if total_results > 0 else 0
