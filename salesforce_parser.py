import math
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

SALESFORCE_BASE_URL = "https://salesforce.wd12.myworkdayjobs.com"
SALESFORCE_JOB_LINK_RE = re.compile(r"/en-US/external_career_site/job/.+?(JR\d+(?:-\d+)?)")
SALESFORCE_TOTAL_RESULTS_RE = re.compile(r"([\d,]+)\s+JOBS\s+FOUND", re.I)
SALESFORCE_TOTAL_PAGES_RE = re.compile(r"\d+\s*-\s*\d+\s+of\s+([\d,]+)\s+jobs", re.I)
RESULTS_PER_PAGE = 20


def parse_jobs(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    for link in soup.find_all("a", attrs={"data-automation-id": "jobTitle"}, href=True):
        href = (link.get("href") or "").strip()
        title = link.get_text(" ", strip=True)
        if not href or not title:
            continue

        container = _find_job_container(link)
        if container is None:
            continue

        job_id = _extract_job_id(container, href)
        if not job_id or job_id in seen_ids:
            continue

        jobs.append(
            {
                "key": job_id,
                "job_id": job_id,
                "title": title,
                "team": "",
                "location": _extract_field_text(container, "locations"),
                "posted": _normalize_posted(_extract_field_text(container, "postedOn")),
                "description": "",
                "url": urljoin(SALESFORCE_BASE_URL, href),
            }
        )
        seen_ids.add(job_id)

    return jobs


def _find_job_container(link):
    container = link
    while container is not None:
        if getattr(container, "name", None) == "li" and container.find(
            attrs={"data-automation-id": "subtitle"}
        ):
            return container
        container = container.parent
    return None


def _extract_job_id(container, href: str) -> str:
    subtitle = container.find(attrs={"data-automation-id": "subtitle"})
    if subtitle:
        value = " ".join(subtitle.get_text(" ", strip=True).split())
        match = re.search(r"\b(JR\d+(?:-\d+)?)\b", value)
        if match:
            return match.group(1)

    match = SALESFORCE_JOB_LINK_RE.search(href)
    return match.group(1) if match else ""


def _extract_field_text(container, automation_id: str) -> str:
    field = container.find(attrs={"data-automation-id": automation_id})
    if field is None:
        return ""

    value_tag = field.find("dd")
    if value_tag is None:
        return ""

    return " ".join(value_tag.get_text(" ", strip=True).split())


def _normalize_posted(value: str) -> str:
    return ""


def get_total_results(html: str) -> int | None:
    soup = BeautifulSoup(html, "lxml")

    job_count = soup.find(attrs={"data-automation-id": "jobFoundText"})
    if job_count:
        text = " ".join(job_count.get_text(" ", strip=True).split())
        match = SALESFORCE_TOTAL_RESULTS_RE.search(text)
        if match:
            return int(match.group(1).replace(",", ""))

    text = soup.get_text(" ", strip=True)
    match = SALESFORCE_TOTAL_RESULTS_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def get_total_pages(html: str) -> int | None:
    soup = BeautifulSoup(html, "lxml")

    page_text = soup.find(attrs={"data-automation-id": "jobOutOfText"})
    if page_text:
        text = " ".join(page_text.get_text(" ", strip=True).split())
        match = SALESFORCE_TOTAL_PAGES_RE.search(text)
        if match:
            total_results = int(match.group(1).replace(",", ""))
            return max(1, math.ceil(total_results / RESULTS_PER_PAGE))

    total_results = get_total_results(html)
    if total_results is None:
        return None
    return max(1, math.ceil(total_results / RESULTS_PER_PAGE))