import math
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

CVS_BASE_URL = "https://jobs.cvshealth.com"
RESULTS_PER_PAGE = 10
TARGET_CATEGORY = "innovation and technology"

JOB_ID_RE = re.compile(r"\bR\d{6,}\b", re.I)
TOTAL_RESULTS_RE = re.compile(r"Showing\s+([\d,]+)\s+results\s+for", re.I)
TOTAL_RESULTS_FALLBACK_RE = re.compile(r"([\d,]+)\s+results\s+found", re.I)
OF_RESULTS_RE = re.compile(r"\bof\s*([\d,]+)\s*results\b", re.I)


def parse_jobs(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for job_link in soup.select('a[data-ph-at-id="job-link"]'):
        details_href = (job_link.get("href") or "").strip()
        if "/us/en/job/" not in details_href:
            continue

        title = " ".join(job_link.get_text(" ", strip=True).split())
        if not title:
            continue

        container = job_link.find_parent(class_="phw-card-block")
        if container is None:
            container = job_link.parent

        text = " ".join(container.get_text(" ", strip=True).split())
        category = (
            (job_link.get("data-ph-tevent-attr-trait14") or "").strip()
            or _extract_labeled_value(text, "Category")
        )
        if category.lower() != TARGET_CATEGORY:
            continue

        job_id = _extract_job_id(
            (job_link.get("data-ph-tevent-attr-trait169") or "") + " " + text,
            details_href,
        )
        if not job_id or job_id in seen_ids:
            continue

        apply_link = container.find("a", href=re.compile(r"/apply$", re.I))
        apply_href = (apply_link.get("href") or "").strip() if apply_link else ""

        jobs.append(
            {
                "key": job_id,
                "job_id": job_id,
                "title": title,
                "team": _extract_labeled_value(text, "Sub Category"),
                "location": _extract_location(text),
                "posted": "",
                "description": "",
                "url": urljoin(CVS_BASE_URL, details_href),
                "apply_url": apply_href,
            }
        )
        seen_ids.add(job_id)

    return jobs


def _extract_job_id(text: str, href: str) -> str:
    match = JOB_ID_RE.search(text)
    if match:
        return match.group(0).upper()

    match = JOB_ID_RE.search(href)
    if match:
        return match.group(0).upper()

    return ""


def _extract_labeled_value(text: str, label: str) -> str:
    pattern = re.compile(
        rf"{re.escape(label)}\s*:\s*(.*?)\s*(?:"
        r"Location\s*:|Available in\s+\d+\s+locations|"
        r"Job ID\s*:|Category\s*:|Sub Category\s*:|Remote\s*:|Apply Now|$)",
        re.I,
    )
    match = pattern.search(text)
    return " ".join((match.group(1) if match else "").split())


def _extract_location(text: str) -> str:
    location = _extract_labeled_value(text, "Location")
    if location:
        return location

    available_match = re.search(r"(Available in\s+\d+\s+locations)", text, re.I)
    if available_match:
        return " ".join(available_match.group(1).split())

    return ""


def get_total_results(html: str) -> int | None:
    soup = BeautifulSoup(html, "lxml")
    text = " ".join(soup.get_text(" ", strip=True).split())

    for pattern in (TOTAL_RESULTS_RE, TOTAL_RESULTS_FALLBACK_RE, OF_RESULTS_RE):
        match = pattern.search(text)
        if match:
            return int(match.group(1).replace(",", ""))

    return None


def get_total_pages(html: str) -> int | None:
    total_results = get_total_results(html)
    if total_results is None:
        return None
    return max(1, math.ceil(total_results / RESULTS_PER_PAGE))
