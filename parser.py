"""
HTML parser for Apple Jobs search results.
Extracts roles from the rendered Apple careers search page.
"""

import hashlib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

APPLE_BASE_URL = "https://jobs.apple.com"
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
    re.I,
)


def parse_jobs(html: str) -> list[dict]:
    """Parse a rendered Apple Jobs search results page into job dictionaries."""
    soup = BeautifulSoup(html, "lxml")
    jobs = []

    for container in _candidate_containers(soup):
        job = _extract_from_container(container)
        if job:
            jobs.append(job)

    if jobs:
        return _deduplicate(jobs)

    return _extract_from_page_text(soup.get_text("\n", strip=True))


def _candidate_containers(soup: BeautifulSoup) -> list:
    containers = []
    seen = set()

    # Apple result cards consistently surface "Role Number" in the visible card text.
    for node in soup.find_all(string=re.compile(r"Role Number", re.I)):
        card = node.parent
        while card is not None and getattr(card, "name", None) not in {"li", "article", "section", "div"}:
            card = card.parent

        while card is not None:
            text = card.get_text("\n", strip=True)
            if "Role Number" in text and len(text) > 80:
                marker = str(card)
                if marker not in seen:
                    containers.append(card)
                    seen.add(marker)
                break
            card = card.parent

    return containers


def _extract_from_container(container) -> dict | None:
    text = container.get_text("\n", strip=True)
    lines = _clean_lines(text.splitlines())
    if not lines:
        return None

    role_number = _extract_role_number(text)
    if not role_number:
        return None

    title = _extract_title(container, lines, role_number)
    if not title:
        return None

    team = _extract_team(lines, title)
    posted = _extract_posted(text)
    location = _extract_location(lines)
    weekly_hours = _extract_weekly_hours(text)
    description = _extract_description(lines)
    url = _extract_url(container, role_number)

    return {
        "key": _make_key(role_number, url),
        "title": title,
        "team": team,
        "location": location,
        "posted": posted,
        "role_number": role_number,
        "weekly_hours": weekly_hours,
        "description": description,
        "url": url,
    }


def _is_non_title_line(line: str, role_number: str) -> bool:
    lowered = line.lower().strip()
    if line == role_number:
        return True
    if "role number" in lowered:
        return True
    if lowered.startswith("location "):
        return True
    if "weekly hours" in lowered:
        return True
    if DATE_RE.search(line):
        return True
    if lowered in {"actions", "image", "submit resume", "see full role description", "share"}:
        return True
    if lowered.startswith("share"):
        return True
    return False


def _normalize_title(title: str, role_number: str) -> str:
    title = title.strip()
    # Remove redundant role number embedded in title, if present
    if role_number and title.endswith(role_number):
        title = title[: -len(role_number)].strip()
    # Remove extra trailing punctuation/spaces
    title = title.rstrip("-:,. ")
    return title


def _extract_title(container, lines: list[str], role_number: str) -> str:
    for tag_name in ("h1", "h2", "h3", "h4"):
        heading = container.find(tag_name)
        if heading:
            title = heading.get_text(" ", strip=True)
            if title and "Role Number" not in title and not title.strip().lower().startswith("share"):
                return _normalize_title(title, role_number)

    for line in lines:
        if _is_non_title_line(line, role_number):
            continue
        return _normalize_title(line, role_number)

    return ""


def _extract_team(lines: list[str], title: str) -> str:
    title_seen = False
    for line in lines:
        if not title_seen:
            if line == title:
                title_seen = True
            continue
        if DATE_RE.search(line):
            return DATE_RE.sub("", line).strip(" -")
        if line.startswith("Location "):
            break
        if line and not line.startswith("Share "):
            return line
    return ""


def _extract_posted(text: str) -> str:
    match = DATE_RE.search(text)
    return match.group(0) if match else ""


def _extract_location(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("Location "):
            return line.replace("Location ", "", 1).strip()
    return ""


def _extract_weekly_hours(text: str) -> str:
    match = re.search(r"Weekly Hours:\s*([^\n]+)", text, re.I)
    return match.group(1).strip() if match else ""


def _extract_role_number(text: str) -> str:
    match = re.search(r"Role Number:\s*([0-9-]+)", text, re.I)
    return match.group(1).strip() if match else ""


def _extract_description(lines: list[str]) -> str:
    description_lines = []
    start_collecting = False

    for line in lines:
        lowered = line.lower()
        if "weekly hours" in lowered:
            start_collecting = True
            continue
        if not start_collecting:
            continue
        if line in {"Submit Resume", "See full role description", "Actions", "Image"}:
            continue
        if lowered.startswith("share "):
            continue
        description_lines.append(line)

    return " ".join(description_lines[:3]).strip()


def _extract_url(container, role_number: str) -> str:
    for link in container.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not href:
            continue
        if "/details/" in href or "/search?" in href:
            return urljoin(APPLE_BASE_URL, href)
    return f"{APPLE_BASE_URL}/en-us/details/{role_number}"


def _clean_lines(lines: list[str]) -> list[str]:
    cleaned = []
    for raw in lines:
        line = " ".join(raw.split())
        if not line:
            continue
        cleaned.append(line)
    return cleaned


def _extract_from_page_text(page_text: str) -> list[dict]:
    jobs = []
    chunks = re.split(r"(?=Role Number:\s*[0-9-]+)", page_text)
    for chunk in chunks:
        role_number = _extract_role_number(chunk)
        if not role_number:
            continue
        lines = _clean_lines(chunk.splitlines())
        if not lines:
            continue
        title = lines[0]
        normalized_title = _normalize_title(title, role_number)
        jobs.append(
            {
                "key": _make_key(role_number, ""),
                "title": normalized_title,
                "team": _extract_team(lines, normalized_title),
                "location": _extract_location(lines),
                "posted": _extract_posted(chunk),
                "role_number": role_number,
                "weekly_hours": _extract_weekly_hours(chunk),
                "description": _extract_description(lines),
                "url": f"{APPLE_BASE_URL}/en-us/details/{role_number}",
            }
        )
    return _deduplicate(jobs)


def _make_key(role_number: str, url: str) -> str:
    return role_number


def _deduplicate(jobs: list[dict]) -> list[dict]:
    seen_keys = set()
    unique = []
    for job in jobs:
        if job["key"] not in seen_keys:
            seen_keys.add(job["key"])
            unique.append(job)
    return unique


def get_total_pages(html: str) -> int | None:
    """Extract total page count from controls text like '1 of 85'."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)

    # Prefer explicit pagination indicator if available.
    match = re.search(r"\b\d+\s+of\s+(\d+)\b", text, re.I)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

    # Fallback: derive from total results and page size if needed
    return None


def get_total_results(html: str) -> int | None:
    """Extract the Apple search total, e.g. '242 Result(s)'."""
    soup = BeautifulSoup(html, "lxml")
    match = soup.find(string=re.compile(r"\d[\d,]*\+?\s+Result\(s\)", re.I))
    if not match:
        text = soup.get_text("\n", strip=True)
        match = re.search(r"(\d[\d,]*)(\+)?\s+Result\(s\)", text, re.I)
        if match:
            return int(match.group(1).replace(",", ""))
        return None

    num = re.search(r"(\d[\d,]*)", str(match))
    return int(num.group(1).replace(",", "")) if num else None
