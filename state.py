"""State management for seen jobs across multiple company-specific files."""

import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Sequence

import config
from config import CompanyRuntimeConfig

STATE_VERSION = 4

# Regex to split combo titles like "SWE II + Senior SWE" or "PM / Director"
_COMBO_SPLIT = re.compile(r"\s*[+/|]\s*")


def _company_state_file(company_slug: str) -> str:
    return os.path.join(config.SEEN_JOBS_DIR, f"{company_slug}.json")


def _ensure_state_dir() -> None:
    os.makedirs(config.SEEN_JOBS_DIR, exist_ok=True)


def _empty_company_state(company_slug: str) -> dict[str, Any]:
    return {
        "_meta": {"version": STATE_VERSION, "company": company_slug},
        "jobs": {},
    }


def _state_key(value: Any) -> str:
    """Keep third-party job identifiers out of committed state files."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _minimal_state_payload(value: Any) -> dict[str, Any]:
    previous = value if isinstance(value, dict) else {}
    payload = {
        "first_seen": previous.get("first_seen", time.time()),
        "posted": previous.get("posted", ""),
    }
    if previous.get("applied"):
        payload["applied"] = True
        payload["applied_at"] = previous.get("applied_at", "")
    return payload


def _normalize_company_state(company_slug: str, data: Any) -> dict[str, Any]:
    state = _empty_company_state(company_slug)
    if not isinstance(data, dict):
        return state

    jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else data
    if not isinstance(jobs, dict):
        return state

    if data.get("_meta", {}).get("version") == STATE_VERSION:
        state["jobs"] = jobs
        return state

    state["jobs"] = {
        _state_key(key): _minimal_state_payload(value)
        for key, value in jobs.items()
    }
    return state


def _load_company_state(company_slug: str) -> dict[str, Any]:
    state_file = _company_state_file(company_slug)
    if not os.path.exists(state_file):
        return _empty_company_state(company_slug)

    try:
        with open(state_file, "r") as handle:
            return _normalize_company_state(company_slug, json.load(handle))
    except (json.JSONDecodeError, IOError):
        return _empty_company_state(company_slug)


def _prune_seen_jobs(seen: dict[str, Any]) -> dict[str, Any]:
    if len(seen) <= config.MAX_SEEN_JOBS:
        return seen

    # Never prune jobs the user has marked as applied.
    applied_keys = {k for k, v in seen.items() if isinstance(v, dict) and v.get("applied")}
    prunable = [k for k in seen if k not in applied_keys]
    excess = len(seen) - config.MAX_SEEN_JOBS
    if excess <= 0:
        return seen
    sorted_prunable = sorted(prunable, key=lambda key: seen[key].get("first_seen", 0))
    for key in sorted_prunable[:excess]:
        del seen[key]
    return seen


def load_seen_jobs(company_slug: str) -> dict[str, Any]:
    return _load_company_state(company_slug)["jobs"]


def save_seen_jobs(company_slug: str, seen: dict[str, Any]) -> None:
    _ensure_state_dir()
    state = _empty_company_state(company_slug)
    state["jobs"] = _prune_seen_jobs(dict(seen))
    with open(_company_state_file(company_slug), "w") as handle:
        json.dump(state, handle, indent=2)


def _part_matches_excluded(part: str, excluded_role_keywords: Sequence[str]) -> bool:
    """Check if a single title part matches any excluded keyword."""
    part_lower = part.strip().lower()
    if not part_lower:
        return False
    return any(keyword.lower() in part_lower for keyword in excluded_role_keywords)


def is_excluded_role(title: str, excluded_role_keywords: Sequence[str]) -> bool:
    """
    Return True if the job title should be excluded.

    Logic: split the title on combo delimiters (+, /, |).  If *every* part
    contains an excluded keyword the role is excluded.  If at least one part
    is clean, the job is kept — this preserves combo postings like
    "Software Engineer II + Senior Software Engineer".
    """
    parts = _COMBO_SPLIT.split(title)
    if not parts or all(not p.strip() for p in parts):
        return False
    return all(_part_matches_excluded(part, excluded_role_keywords) for part in parts if part.strip())

def should_exclude_title(
    title: str,
    excluded_role_keywords: Sequence[str],
    excluded_title_phrases: Sequence[str],
) -> bool:
    title_lower = title.strip().lower()
    if not title_lower:
        return False

    if any(title_lower == keyword.lower() for keyword in excluded_role_keywords):
        return True

    return any(phrase.lower() in title_lower for phrase in excluded_title_phrases)


def should_include_title(title: str, included_role_keywords: Sequence[str]) -> bool:
    """Return True if the title matches the positive relevance filter.

    An empty keyword list means 'no filter' -> every title is included.
    """
    if not included_role_keywords:
        return True
    title_lower = title.strip().lower()
    if not title_lower:
        return False
    return any(keyword.lower() in title_lower for keyword in included_role_keywords)


def _parse_posted(value: str):
    """Parse a posted date/datetime string into an aware UTC datetime, or None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:  # YYYY-MM-DD
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def job_age_within(posted: str, max_age_hours: int) -> bool:
    """True if the job was posted within max_age_hours.

    Jobs with no parseable date are kept (we cannot tell their age). Date-only
    values are treated as that day at 00:00 UTC.
    """
    if max_age_hours <= 0:
        return True
    posted_dt = _parse_posted(posted)
    if posted_dt is None:
        return True
    age_hours = (datetime.now(timezone.utc) - posted_dt).total_seconds() / 3600
    return age_hours <= max_age_hours


def _today_date_string() -> str:
    return date.today().isoformat()


def _job_state_payload(job: dict, posted_override: str | None = None) -> dict[str, Any]:
    return {
        "first_seen": time.time(),
        "posted": posted_override if posted_override is not None else job.get("posted", ""),
    }


def _resolve_posted_value(job: dict, strategy: str, today: str) -> str:
    if strategy in {"empty", "blank"}:
        return ""
    if strategy in {"today", "new-only-today", "all-found-today"}:
        return today
    return job.get("posted", "")


def filter_new_jobs(runtime_config: CompanyRuntimeConfig, jobs: list[dict]) -> list[dict]:
    seen = load_seen_jobs(runtime_config.slug)
    new_jobs = []
    discovered_on = _today_date_string()
    changed = False

    for job in jobs:
        key = job.get("key") or job.get("job_id") or job.get("role_number")
        if not key:
            continue
        strategy = runtime_config.definition.regular_scrape_posted_strategy
        posted_value = _resolve_posted_value(job, strategy, discovered_on)
        job["posted"] = posted_value

        stored_key = _state_key(key)
        if stored_key not in seen:
            new_jobs.append(job)
            seen[stored_key] = _job_state_payload(job, posted_override=posted_value)
            changed = True
            continue

        if strategy == "all-found-today":
            previous = seen[stored_key]
            first_seen = previous.get("first_seen", time.time())
            seen[stored_key] = _job_state_payload(job, posted_override=posted_value)
            seen[stored_key]["first_seen"] = first_seen
            # Preserve "applied" status across re-writes.
            if previous.get("applied"):
                seen[stored_key]["applied"] = True
                seen[stored_key]["applied_at"] = previous.get("applied_at", "")
            changed = True

    if changed:
        save_seen_jobs(runtime_config.slug, seen)

    return new_jobs


def replace_seen_jobs(runtime_config: CompanyRuntimeConfig, jobs: list[dict]) -> None:
    seen = {}
    posted_strategy = runtime_config.definition.full_scrape_posted_strategy
    today = _today_date_string()

    for job in jobs:
        key = job.get("key") or job.get("job_id") or job.get("role_number")
        if not key:
            continue
        seen[_state_key(key)] = _job_state_payload(
            job,
            posted_override=_resolve_posted_value(job, posted_strategy, today),
        )
    save_seen_jobs(runtime_config.slug, seen)


def update_seen_job_details(company_slug: str, jobs: list[dict]) -> None:
    """Persist enriched fields without losing first-seen or applied metadata."""
    seen = load_seen_jobs(company_slug)
    changed = False
    for job in jobs:
        key = job.get("key") or job.get("job_id") or job.get("role_number")
        if not key:
            continue
        stored_key = _state_key(key)
        previous = seen.get(stored_key) if isinstance(seen.get(stored_key), dict) else {}
        payload = _job_state_payload(job)
        payload["first_seen"] = previous.get("first_seen", payload["first_seen"])
        if previous.get("applied"):
            payload["applied"] = True
            payload["applied_at"] = previous.get("applied_at", "")
        seen[stored_key] = payload
        changed = True
    if changed:
        save_seen_jobs(company_slug, seen)


# --------------------------------------------------------------------------- #
# Applied tracking (2d)
# --------------------------------------------------------------------------- #

def is_applied(company_slug: str, key: str) -> bool:
    entry = load_seen_jobs(company_slug).get(_state_key(key))
    return bool(isinstance(entry, dict) and entry.get("applied"))


def mark_applied(company_slug: str, keys: Sequence[str]) -> list[str]:
    """Mark one or more job keys as applied so they are suppressed forever.

    Returns the list of keys that were updated.
    """
    seen = load_seen_jobs(company_slug)
    today = _today_date_string()
    updated = []
    for key in keys:
        stored_key = _state_key(key)
        entry = seen.get(stored_key)
        if not isinstance(entry, dict):
            entry = {"first_seen": time.time(), "posted": ""}
            seen[stored_key] = entry
        if not entry.get("applied"):
            entry["applied"] = True
            entry["applied_at"] = today
            updated.append(key)
    if updated:
        save_seen_jobs(company_slug, seen)
    return updated


def unmark_applied(company_slug: str, keys: Sequence[str]) -> list[str]:
    """Clear the applied flag on one or more job keys. Returns keys updated."""
    seen = load_seen_jobs(company_slug)
    updated = []
    for key in keys:
        entry = seen.get(_state_key(key))
        if isinstance(entry, dict) and entry.get("applied"):
            entry["applied"] = False
            entry.pop("applied_at", None)
            updated.append(key)
    if updated:
        save_seen_jobs(company_slug, seen)
    return updated


def list_applied(company_slug: str) -> list[dict[str, Any]]:
    seen = load_seen_jobs(company_slug)
    applied = [
        {"key": key, **value}
        for key, value in seen.items()
        if isinstance(value, dict) and value.get("applied")
    ]
    return sorted(applied, key=lambda item: item.get("applied_at", ""), reverse=True)
