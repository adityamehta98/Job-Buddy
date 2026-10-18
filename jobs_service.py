"""Assembles the job list shown in the web UI and scores each job vs the CV.

Two sources:
  * Custom companies (custom_companies.json): fetched live from their ATS API,
    so we get the full job description and a real CV match % + missing keywords.
  * Built-in companies: read from the committed seen_jobs/ state. Those records
    don't carry a description, so their match is computed on title+team only
    (shown with source="title-only").
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from playwright.async_api import async_playwright

import config
import matcher
import resume_store
from location_filter import is_us_location
from companies import list_companies
from companies.generic_ats import (
    api_url_for,
    resolve_from_url,
    parse_ats,
    sniff_from_html,
    slugify,
)
from runner import collect_jobs
from state import is_applied, should_include_title

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_CUSTOM_CONFIG = os.path.join(_REPO_ROOT, "custom_companies.json")
_UA = {"user-agent": "Mozilla/5.0 (job-buddy-ui)"}

# Simple in-memory cache of live fetches: {slug: (fetched_at, jobs)}
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300  # seconds
def _load_builtin_cache() -> dict[str, tuple[float, list[dict]]]:
    try:
        with open(config.DASHBOARD_CACHE_FILE, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    cache = {}
    if isinstance(raw, dict):
        for slug, value in raw.items():
            if isinstance(value, dict) and isinstance(value.get("jobs"), list):
                cache[slug] = (float(value.get("fetched_at", 0)), value["jobs"])
    return cache


def _save_builtin_cache() -> None:
    payload = {
        slug: {"fetched_at": fetched_at, "jobs": jobs}
        for slug, (fetched_at, jobs) in _BUILTIN_CACHE.items()
    }
    with open(config.DASHBOARD_CACHE_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


_BUILTIN_CACHE: dict[str, tuple[float, list[dict]]] = _load_builtin_cache()
_BUILTIN_CACHE_TTL = 600  # seconds
_BUILTIN_FETCH_LOCK = threading.Lock()
_DISCOVERY_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Custom companies config (read + write for the Companies tab)
# --------------------------------------------------------------------------- #

def _load_config() -> dict:
    if not os.path.exists(_CUSTOM_CONFIG):
        return {"companies": []}
    try:
        with open(_CUSTOM_CONFIG, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {"companies": []}
    if isinstance(data, list):
        data = {"companies": data}
    data.setdefault("companies", [])
    return data


def _save_config(data: dict) -> None:
    with open(_CUSTOM_CONFIG, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def list_custom_companies() -> list[dict]:
    return [c for c in _load_config().get("companies", []) if isinstance(c, dict)]


def add_custom_company(name: str, url: str, ats: str = "", token: str = "") -> dict:
    name = (name or "").strip()
    url = (url or "").strip()
    if not name or not url:
        raise ValueError("Both name and URL are required.")
    data = _load_config()
    companies = data.get("companies", [])
    slug = slugify(name)
    if any(slugify(str(c.get("name", ""))) == slug for c in companies):
        raise ValueError(f"A company named '{name}' is already in the list.")
    entry = {"name": name, "url": url}
    if ats.strip():
        entry["ats"] = ats.strip().lower()
    if token.strip():
        entry["token"] = token.strip()
    companies.append(entry)
    data["companies"] = companies
    _save_config(data)
    _CACHE.pop(slug, None)
    return entry


def delete_custom_company(name: str) -> bool:
    data = _load_config()
    slug = slugify(name)
    before = len(data.get("companies", []))
    data["companies"] = [
        c for c in data.get("companies", []) if slugify(str(c.get("name", ""))) != slug
    ]
    if len(data["companies"]) == before:
        return False
    _save_config(data)
    _CACHE.pop(slug, None)
    return True


# --------------------------------------------------------------------------- #
# Live fetch for a custom company
# --------------------------------------------------------------------------- #

def _resolve(entry: dict) -> tuple[str | None, str | None]:
    ats = (entry.get("ats") or "").strip().lower() or None
    token = (entry.get("token") or "").strip() or None
    if ats and token:
        return ats, token
    url = entry.get("url", "")
    a, t = resolve_from_url(url)
    ats, token = ats or a, token or t
    if ats and token:
        return ats, token
    # Custom domain: sniff the careers page HTML for an embedded ATS token.
    try:
        html = httpx.get(url, headers=_UA, timeout=20, follow_redirects=True).text
        a, t = sniff_from_html(html)
        ats, token = ats or a, token or t
    except httpx.HTTPError:
        pass
    return ats, token


def _fetch_custom_jobs(entry: dict) -> list[dict]:
    slug = slugify(str(entry.get("name", "")))
    now = time.time()
    cached = _CACHE.get(slug)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    ats, token = _resolve(entry)
    if not (ats and token):
        raise RuntimeError(
            f"Could not detect the ATS for {entry.get('name')} ({entry.get('url')}). "
            f"Add 'ats' and 'token' for it."
        )
    resp = httpx.get(api_url_for(ats, token), headers=_UA, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    jobs = parse_ats(ats, token, resp.text)
    _CACHE[slug] = (now, jobs)
    return jobs


# --------------------------------------------------------------------------- #
# Live fetch for built-in companies
# --------------------------------------------------------------------------- #

async def _fetch_builtins_async(slugs: list[str]) -> tuple[dict[str, list[dict]], list[str]]:
    results: dict[str, list[dict]] = {}
    errors: list[str] = []
    semaphore = asyncio.Semaphore(3)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            async def fetch_one(slug: str) -> None:
                runtime = config.get_company_runtime(slug)
                async with semaphore:
                    try:
                        jobs = await collect_jobs(
                            browser,
                            runtime,
                            min(runtime.max_pages, config.UI_MAX_PAGES),
                        )
                        results[slug] = jobs
                        if not jobs and not runtime.definition.allow_empty_results:
                            errors.append(f"{runtime.display_name}: no jobs were returned")
                    except Exception as exc:
                        errors.append(f"{runtime.display_name}: {exc}")

            await asyncio.gather(*(fetch_one(slug) for slug in slugs))
        finally:
            await browser.close()

    return results, errors


def _fetch_builtin_jobs(slugs: list[str]) -> tuple[dict[str, list[dict]], list[str]]:
    """Return cached built-ins immediately and refresh stale data safely."""
    now = time.time()
    results: dict[str, list[dict]] = {}
    missing: list[str] = []
    stale: list[str] = []
    for slug in slugs:
        cached = _BUILTIN_CACHE.get(slug)
        if cached:
            results[slug] = cached[1]
            if now - cached[0] >= _BUILTIN_CACHE_TTL:
                stale.append(slug)
        else:
            missing.append(slug)

    def refresh(refresh_slugs: list[str]) -> list[str]:
        fetched, refresh_errors = asyncio.run(_fetch_builtins_async(refresh_slugs))
        changed = False
        for refresh_slug, jobs in fetched.items():
            # Cache a successful empty response too; otherwise companies that
            # legitimately have no qualifying roles would block every launch.
            _BUILTIN_CACHE[refresh_slug] = (time.time(), jobs)
            changed = True
        if changed:
            _save_builtin_cache()
        return refresh_errors

    if missing:
        # With no snapshot to show, the first request must wait for one fetch.
        with _BUILTIN_FETCH_LOCK:
            still_missing = [slug for slug in missing if slug not in _BUILTIN_CACHE]
            targets = list(dict.fromkeys(still_missing + stale))
            errors = refresh(targets) if targets else []
        for slug in slugs:
            cached = _BUILTIN_CACHE.get(slug)
            if cached:
                results[slug] = cached[1]
        return results, errors

    if stale and _BUILTIN_FETCH_LOCK.acquire(blocking=False):
        def background_refresh() -> None:
            try:
                refresh(stale)
            finally:
                _BUILTIN_FETCH_LOCK.release()

        threading.Thread(target=background_refresh, daemon=True).start()

    return results, []


# --------------------------------------------------------------------------- #
# Stable dates and dashboard age window
# --------------------------------------------------------------------------- #

def _parse_posted_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").date()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date()
    except ValueError:
        return None


def _load_discovery_dates() -> dict[str, str]:
    try:
        with open(config.DASHBOARD_DISCOVERY_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_discovery_dates(data: dict[str, str]) -> None:
    with open(config.DASHBOARD_DISCOVERY_FILE, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def _discovery_key(slug: str, job: dict) -> str:
    identifier = job.get("key") or job.get("job_id") or job.get("url") or job.get("title")
    return hashlib.sha256(f"{slug}:{identifier}".encode("utf-8")).hexdigest()


def _assign_stable_dates(raw_jobs: list[tuple[str, str, dict, str]]) -> list[tuple[str, str, dict, str]]:
    """Use source dates where available, otherwise persist first discovery."""
    today = datetime.now(timezone.utc).date()
    oldest_kept = today - timedelta(days=config.UI_MAX_AGE_DAYS)
    with _DISCOVERY_LOCK:
        discoveries = _load_discovery_dates()
        changed = False
        output = []
        active_keys: set[str] = set()

        for company_name, slug, job, source in raw_jobs:
            key = _discovery_key(slug, job)
            active_keys.add(key)
            posted_date = _parse_posted_date(job.get("posted", ""))
            if posted_date is None:
                posted_date = _parse_posted_date(discoveries.get(key, "")) or today
                if key not in discoveries:
                    discoveries[key] = posted_date.isoformat()
                    changed = True
                job = dict(job)
                job["posted"] = posted_date.isoformat()
                job["date_basis"] = "first-seen"
            else:
                job = dict(job)
                job["posted"] = posted_date.isoformat()
                job["date_basis"] = "posted"

            if oldest_kept <= posted_date <= today:
                output.append((company_name, slug, job, source))

        # Bound the local metadata file without retaining identifiers for jobs
        # that disappeared more than a month ago.
        prune_before = today - timedelta(days=30)
        for key, value in list(discoveries.items()):
            discovered = _parse_posted_date(value)
            if key not in active_keys and (discovered is None or discovered < prune_before):
                discoveries.pop(key, None)
                changed = True
        if changed:
            _save_discovery_dates(discoveries)
        return output


# --------------------------------------------------------------------------- #
# Assemble + score
# --------------------------------------------------------------------------- #

def _enrich(company_name: str, slug: str, job: dict, cv_text: str, source: str) -> dict:
    key = job.get("key") or job.get("job_id") or ""
    description = (job.get("description") or "").strip()
    # Only score when we have a real job description; title-only records would
    # otherwise inflate the match from the title text alone.
    comparison_text = " ".join([job.get("title", ""), job.get("team", ""), description])
    if cv_text and len(description) >= 50:
        result = matcher.score(cv_text, comparison_text)
    elif len(description) >= 50:
        result = matcher.analyze_jd(comparison_text)
    else:
        result = {
            "match": None, "matched": [], "missing": [], "extracted": [],
            "keyword_details": [], "matched_count": 0, "jd_skill_count": 0,
            "method": "skills-vocabulary-v2", "confidence": "unavailable",
            "jd_chars": len(description), "resume_chars": len(cv_text),
        }
    enriched = {
        "company": company_name,
        "slug": slug,
        "key": key,
        "title": job.get("title", ""),
        "team": job.get("team", ""),
        "location": job.get("location", ""),
        "posted": job.get("posted", ""),
        "date_basis": job.get("date_basis", "posted"),
        "url": job.get("url", ""),
        "description": description,
        "applied": is_applied(slug, key),
        "source": source,
        "match_basis": "full-description" if len(description) >= 50 else "unavailable",
    }
    enriched.update(result)
    return enriched


def get_all_jobs(only_unapplied: bool = True, include_builtins: bool = True) -> dict:
    """Return {jobs: [...], errors: [...], has_cv: bool}."""
    cv_text = resume_store.active_resume_text()
    raw_jobs: list[tuple[str, str, dict, str]] = []
    errors: list[str] = []
    filtered_non_us = 0

    custom = list_custom_companies()
    custom_slugs = {slugify(str(c.get("name", ""))) for c in custom}

    # Custom companies: live, full description -> real match
    for entry in custom:
        name = str(entry.get("name", ""))
        slug = slugify(name)
        try:
            for job in _fetch_custom_jobs(entry):
                if config.US_ONLY and not is_us_location(
                    job.get("location", ""), config.ALLOW_REMOTE
                ):
                    filtered_non_us += 1
                    continue
                raw_jobs.append((name, slug, job, "live"))
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    # Built-in companies: fetch live with their registered parsers. Persisted
    # seen state intentionally contains no third-party titles or URLs, so it
    # cannot serve as the dashboard's source of display data.
    if include_builtins:
        builtin_slugs = [slug for slug in list_companies() if slug not in custom_slugs]
        builtin_jobs, builtin_errors = _fetch_builtin_jobs(builtin_slugs)
        errors.extend(builtin_errors)
        for slug in builtin_slugs:
            runtime = config.get_company_runtime(slug)
            for job in builtin_jobs.get(slug, []):
                if config.US_ONLY and not is_us_location(
                    job.get("location", ""), config.ALLOW_REMOTE
                ):
                    filtered_non_us += 1
                    continue
                raw_jobs.append((runtime.display_name, slug, job, "live-built-in"))

    # Resolve missing dates to a stable first-discovered date, then remove
    # roles outside the dashboard's five-day window before expensive scoring.
    raw_jobs = _assign_stable_dates(raw_jobs)

    jobs = [
        _enrich(company_name, slug, job, cv_text, source)
        for company_name, slug, job, source in raw_jobs
    ]

    # Show only roles under the target titles (same include list the scraper uses).
    if config.INCLUDE_KEYWORDS:
        jobs = [j for j in jobs if should_include_title(j.get("title", ""), config.INCLUDE_KEYWORDS)]

    if only_unapplied:
        jobs = [j for j in jobs if not j["applied"]]

    # Newest first by default; the dashboard offers additional sort modes.
    jobs.sort(key=lambda j: (j.get("posted", ""), j.get("company", ""), j.get("title", "")), reverse=True)

    return {
        "jobs": jobs,
        "errors": errors,
        "has_cv": bool(cv_text),
        "us_only": config.US_ONLY,
        "filtered_non_us": filtered_non_us,
        "max_age_days": config.UI_MAX_AGE_DAYS,
    }
