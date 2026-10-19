import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

AMAZON_BASE_URL = "https://www.amazon.jobs"
AMAZON_JOB_LINK_RE = re.compile(r"/en/jobs/(?P<job_id>\d+)/")
AMAZON_POSTED_RE = re.compile(r"Posted\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.I)
AMAZON_TOTAL_PAGES_RE = re.compile(r"\b\d+\s*\.\.\.\s*(\d+)\b")


def parse_jobs(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    for link in soup.find_all("a", href=AMAZON_JOB_LINK_RE):
        href = (link.get("href") or "").strip()
        match = AMAZON_JOB_LINK_RE.search(href)
        if not match:
            continue

        job_id = match.group("job_id")
        if job_id in seen_ids:
            continue

        container = _find_job_container(link)
        if container is None:
            continue

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
        if "Job ID:" in text and len(text) > 40:
            return container
        container = container.parent
    return None


def _extract_job(container, link, job_id: str) -> dict | None:
    lines = _clean_lines(container.get_text("\n", strip=True).splitlines())
    title = link.get_text(" ", strip=True)
    if not title:
        return None

    location = _extract_location(lines, title)
    posted = _extract_posted("\n".join(lines))
    description = _extract_description(lines)
    url = urljoin(AMAZON_BASE_URL, link.get("href", ""))

    return {
        "key": job_id,
        "job_id": job_id,
        "title": title,
        "team": "",
        "location": location,
        "posted": posted,
        "description": description,
        "url": url,
    }


def _extract_location(lines: list[str], title: str) -> str:
    title_seen = False
    location_parts = []

    for line in lines:
        if not title_seen:
            if line == title:
                title_seen = True
            continue

        if line == "|":
            continue
        if line.startswith("Job ID:") or line.startswith("Posted "):
            break
        location_parts.append(line)

    return " ".join(location_parts).strip()


def _extract_posted(text: str) -> str:
    match = AMAZON_POSTED_RE.search(text)
    return match.group(1) if match else ""


def _extract_description(lines: list[str]) -> str:
    description_lines = []
    collecting = False

    for line in lines:
        lowered = line.lower()
        if lowered.startswith("basic qualifications") or lowered.startswith("preferred qualifications"):
            collecting = True
            continue
        if not collecting:
            continue
        if lowered.startswith("read more about the job"):
            break
        if line in {"Share", "Save"}:
            continue
        description_lines.append(line.lstrip("• "))
        if len(description_lines) >= 3:
            break

    return " ".join(description_lines).strip()


def _clean_lines(lines: list[str]) -> list[str]:
    cleaned = []
    for raw in lines:
        line = " ".join(raw.split())
        if line:
            cleaned.append(line)
    return cleaned


def get_total_pages(html: str) -> int | None:
    soup = BeautifulSoup(html, "lxml")

    page_numbers = []
    for link in soup.find_all("a", href=True):
        text = link.get_text(" ", strip=True)
        if text.isdigit():
            page_numbers.append(int(text))
    if page_numbers:
        return max(page_numbers)

    text = soup.get_text(" ", strip=True)
    match = AMAZON_TOTAL_PAGES_RE.search(text)
    if match:
        return int(match.group(1))

    return None


def get_total_results(html: str) -> int | None:
    return None