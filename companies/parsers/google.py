import json
import math
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

GOOGLE_BASE_URL = "https://www.google.com"
GOOGLE_JOB_LINK_RE = re.compile(
    r"/about/careers/applications/jobs/results/(?P<job_id>\d+)-",
    re.I,
)
GOOGLE_TOTAL_RESULTS_RE = re.compile(r"([\d,]+)\s+jobs\s+matched", re.I)
GOOGLE_ROWS_RE = re.compile(r"Showing\s+\d+\s+to\s+\d+\s+of\s+([\d,]+)\s+rows", re.I)
GOOGLE_RESULTS_PER_PAGE = 20


def parse_jobs(html: str) -> list[dict]:
    jobs_from_embedded_data = _parse_jobs_from_embedded_data(html)
    if jobs_from_embedded_data is not None:
        return jobs_from_embedded_data
    return _parse_jobs_from_html(html)


def _parse_jobs_from_embedded_data(html: str) -> list[dict] | None:
    for payload in _extract_embedded_data_payloads(html):
        jobs = _extract_jobs_from_payload(payload)
        if jobs:
            return jobs
    return None


def _extract_embedded_data_payloads(html: str) -> list[str]:
    return re.findall(
        r"AF_initDataCallback\(\{.*?data:(\[.*?\]),\s*sideChannel:\s*\{\}\}\);",
        html,
        re.DOTALL,
    )


def _extract_jobs_from_payload(payload: str) -> list[dict]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []

    job_lists = []
    _collect_job_lists(data, job_lists)
    if not job_lists:
        return []

    jobs = []
    seen_ids = set()
    for job_list in job_lists:
        for raw_job in job_list:
            job = _normalize_embedded_job(raw_job)
            if job is None:
                continue
            job_id = job["key"]
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            jobs.append(job)

    return jobs


def _collect_job_lists(node, job_lists: list[list[list]]) -> None:
    if isinstance(node, list):
        if _looks_like_job_list(node):
            job_lists.append(node)
            return
        for item in node:
            _collect_job_lists(item, job_lists)


def _looks_like_job_list(node: list) -> bool:
    if not isinstance(node, list) or not node or not all(isinstance(item, list) for item in node):
        return False

    matched = 0
    for item in node[:5]:
        if len(item) < 10:
            return False
        if not isinstance(item[0], str) or not item[0].isdigit():
            return False
        if not isinstance(item[1], str) or not item[1].strip():
            return False
        if not isinstance(item[7], str):
            return False
        matched += 1
    return matched > 0


def _normalize_embedded_job(raw_job: list) -> dict | None:
    if len(raw_job) < 10:
        return None

    job_id = str(raw_job[0]).strip()
    title = str(raw_job[1]).strip()
    company = str(raw_job[7]).strip()
    if not job_id or not title or company.lower() != "google":
        return None

    locations = _extract_embedded_locations(raw_job[9])
    description = _extract_embedded_description(raw_job)

    return {
        "key": job_id,
        "job_id": job_id,
        "title": title,
        "team": _extract_team(title),
        "location": _format_locations(locations),
        "posted": "",
        "description": description,
        "url": f"{GOOGLE_BASE_URL}/about/careers/applications/jobs/results/{job_id}",
    }


def _extract_embedded_locations(value) -> list[str]:
    locations = []
    if not isinstance(value, list):
        return locations

    for entry in value:
        if isinstance(entry, list) and entry:
            label = str(entry[0]).strip()
            if label and label not in locations:
                locations.append(label)
    return locations


def _extract_embedded_description(raw_job: list) -> str:
    for item in raw_job:
        if not isinstance(item, list) or len(item) < 2:
            continue
        html_blob = item[1]
        if not isinstance(html_blob, str) or "<p" not in html_blob:
            continue
        text = _html_fragment_to_text(html_blob)
        if len(text) >= 40:
            return text[:280].strip()
    return ""


def _parse_jobs_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    for link in soup.find_all("a", href=GOOGLE_JOB_LINK_RE):
        href = (link.get("href") or "").strip()
        match = GOOGLE_JOB_LINK_RE.search(href)
        if not match:
            continue

        job_id = match.group("job_id")
        if job_id in seen_ids:
            continue

        title = _extract_html_title(link)
        if not title:
            continue

        container = _find_job_container(link)
        company, location = _extract_company_and_location(container)
        if company.lower() != "google":
            continue

        jobs.append(
            {
                "key": job_id,
                "job_id": job_id,
                "title": title,
                "team": _extract_team(title),
                "location": location,
                "posted": "",
                "description": "",
                "url": urljoin(GOOGLE_BASE_URL, href),
            }
        )
        seen_ids.add(job_id)

    return jobs


def _extract_html_title(link) -> str:
    heading = link.find(["h2", "h3", "h4"])
    if heading is not None:
        return heading.get_text(" ", strip=True)
    text = link.get_text(" ", strip=True)
    return text.replace("Learn more about", "", 1).strip()


def _find_job_container(link):
    container = link
    while container is not None:
        text = " ".join(container.get_text(" ", strip=True).split())
        if "Learn more about" in text and "|" in text and len(text) > 30:
            return container
        container = container.parent
    return link.parent


def _extract_company_and_location(container) -> tuple[str, str]:
    if container is None:
        return "", ""

    text = "\n".join(
        line.strip()
        for line in container.get_text("\n", strip=True).splitlines()
        if line.strip()
    )
    for line in text.splitlines():
        if "|" not in line:
            continue
        company, location = [part.strip() for part in line.split("|", 1)]
        if company:
            return company, location
    return "", ""


def _extract_team(title: str) -> str:
    parts = [part.strip() for part in title.split(",") if part.strip()]
    if len(parts) <= 1:
        return ""
    return " / ".join(parts[1:3])


def _format_locations(locations: list[str]) -> str:
    if not locations:
        return ""
    if len(locations) == 1:
        return locations[0]
    return f"{locations[0]}; +{len(locations) - 1} more"


def _html_fragment_to_text(html_fragment: str) -> str:
    soup = BeautifulSoup(html_fragment, "lxml")
    return " ".join(soup.get_text(" ", strip=True).split())


def get_total_results(html: str) -> int | None:
    embedded_total = _get_total_results_from_embedded_data(html)
    if embedded_total is not None:
        return embedded_total

    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    match = GOOGLE_TOTAL_RESULTS_RE.search(text) or GOOGLE_ROWS_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _get_total_results_from_embedded_data(html: str) -> int | None:
    for payload in _extract_embedded_data_payloads(html):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        total = _find_total_results_value(data)
        if total is not None:
            return total
    return None


def _find_total_results_value(node) -> int | None:
    if isinstance(node, list):
        for index, item in enumerate(node[:-1]):
            next_item = node[index + 1]
            if _looks_like_job_list(item) and isinstance(next_item, int) and next_item > 0:
                return next_item
        for item in node:
            total = _find_total_results_value(item)
            if total is not None:
                return total
    return None


def get_total_pages(html: str) -> int | None:
    total_results = get_total_results(html)
    if total_results is None:
        return None
    return max(1, math.ceil(total_results / GOOGLE_RESULTS_PER_PAGE))
