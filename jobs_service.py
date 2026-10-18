"""Assembles the job list shown in the web UI and scores each job vs the CV.

Two sources:
  * Custom companies (custom_companies.json): fetched live from their ATS API,
    so we get the full job description and a real CV match % + missing keywords.
  * Built-in companies: read from the committed seen_jobs/ state. Those records
    don't carry a description, so their match is computed on title+team only
    (shown with source="title-only").
"""

from __future__ import annotations

import json
import os
import time

import httpx

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
from state import is_applied, load_seen_jobs, should_include_title

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_CUSTOM_CONFIG = os.path.join(_REPO_ROOT, "custom_companies.json")
_UA = {"user-agent": "Mozilla/5.0 (job-buddy-ui)"}

# Simple in-memory cache of live fetches: {slug: (fetched_at, jobs)}
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300  # seconds


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
    jobs: list[dict] = []
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
                jobs.append(_enrich(name, slug, job, cv_text, source="live"))
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    # Built-in companies: from seen_jobs state, title-only match
    if include_builtins:
        for slug in list_companies():
            if slug in custom_slugs:
                continue
            try:
                seen = load_seen_jobs(slug)
            except Exception:
                continue
            for key, value in seen.items():
                if not isinstance(value, dict):
                    continue
                job = {
                    "key": key,
                    "title": value.get("title", ""),
                    "team": value.get("team", ""),
                    "location": value.get("location", ""),
                    "posted": value.get("posted", ""),
                    "url": value.get("url", ""),
                    "description": value.get("description", ""),
                }
                if config.US_ONLY and not is_us_location(
                    job.get("location", ""), config.ALLOW_REMOTE
                ):
                    filtered_non_us += 1
                    continue
                source = "stored-description" if job.get("description") else "title-only"
                jobs.append(_enrich(slug.replace("-", " ").title(), slug, job, cv_text, source=source))

    # Show only roles under the target titles (same include list the scraper uses).
    if config.INCLUDE_KEYWORDS:
        jobs = [j for j in jobs if should_include_title(j.get("title", ""), config.INCLUDE_KEYWORDS)]

    if only_unapplied:
        jobs = [j for j in jobs if not j["applied"]]

    # Sort: highest match first (unknown match last), then newest posted.
    jobs.sort(key=lambda j: (j["match"] if j["match"] is not None else -1, j.get("posted", "")), reverse=True)

    return {
        "jobs": jobs,
        "errors": errors,
        "has_cv": bool(cv_text),
        "us_only": config.US_ONLY,
        "filtered_non_us": filtered_non_us,
    }
