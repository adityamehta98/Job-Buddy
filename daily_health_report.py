#!/usr/bin/env python3
"""Daily portal health report for Job Buddy.

Runs once a day (late evening MST). It reads the day's own scrape workflow runs
from the GitHub Actions API, reconstructs per-company pass/fail for each run from
the logs, and reports any company portal that failed more than a threshold number
of times in a row during the window, plus whether it is still down right now.

This is intentionally self-contained: it needs no change to the scraper and no
extra state file. The per-run failure signal is simply that a company never
printed its "[<slug>] Seen jobs database:" line that run (which only prints when
the scrape actually returned roles); a portal that is down never reaches it.

Env:
  GITHUB_REPOSITORY   owner/repo (auto-set in Actions)
  GITHUB_TOKEN        token with actions:read (auto-set in Actions)
  HEALTH_FAIL_THRESHOLD   consecutive failures to report (default 20)
  HEALTH_LOOKBACK_HOURS   window to scan (default 24)
  HEALTH_WORKFLOW_FILE    scrape workflow filename (default scrape.yml)
  plus the usual NOTIFY_CHANNELS / channel secrets so it can send the report.
"""

import asyncio
import io
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone

import httpx

from core import notifier
API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPOSITORY", "")
TOKEN = os.getenv("GITHUB_TOKEN", "")
WORKFLOW_FILE = os.getenv("HEALTH_WORKFLOW_FILE", "scrape.yml")
THRESHOLD = int(os.getenv("HEALTH_FAIL_THRESHOLD", "20") or "20")
LOOKBACK_HOURS = int(os.getenv("HEALTH_LOOKBACK_HOURS", "24") or "24")
MST = timezone(timedelta(hours=-7))  # Arizona, no DST

_HEADERS = {
    "accept": "application/vnd.github+json",
    "authorization": f"Bearer {TOKEN}",
    "x-github-api-version": "2022-11-28",
}

# "[apple] Scraping Apple jobs" -> slug + display name.
_SCRAPING_RE = re.compile(r"\[([a-z0-9][a-z0-9\-_]*)\] Scraping (.+?) jobs")


def _seen_marker(slug: str) -> str:
    return f"[{slug}] Seen jobs database:"


def list_runs(client: httpx.Client, since_utc: datetime) -> list[dict]:
    """Completed scrape runs created at or after since_utc, oldest first."""
    runs: list[dict] = []
    page = 1
    while page <= 6:
        resp = client.get(
            f"{API}/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/runs",
            params={"per_page": 100, "page": page, "status": "completed"},
        )
        resp.raise_for_status()
        batch = resp.json().get("workflow_runs", [])
        if not batch:
            break
        reached_end = False
        for run in batch:
            created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if created < since_utc:
                reached_end = True
                continue
            runs.append({"id": run["id"], "created": created})
        if reached_end or len(batch) < 100:
            break
        page += 1
    runs.sort(key=lambda r: r["created"])
    return runs


def fetch_log_text(client: httpx.Client, run_id: int) -> str:
    try:
        resp = client.get(f"{API}/repos/{REPO}/actions/runs/{run_id}/logs", follow_redirects=True)
    except httpx.HTTPError:
        return ""
    if resp.status_code != 200:
        return ""
    try:
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile:
        return ""
    parts = []
    for name in archive.namelist():
        if name.endswith(".txt"):
            try:
                parts.append(archive.read(name).decode("utf-8", "ignore"))
            except Exception:
                continue
    return "\n".join(parts)


def parse_run(text: str) -> dict[str, tuple[str, bool]]:
    """{slug: (display_name, succeeded)} for every company attempted this run."""
    companies = {slug: display.strip() for slug, display in _SCRAPING_RE.findall(text)}
    return {
        slug: (display, _seen_marker(slug) in text)
        for slug, display in companies.items()
    }


def analyze(run_statuses: list[dict[str, tuple[str, bool]]]) -> dict[str, dict]:
    """Per company: display, max consecutive failures, still-down, run count."""
    ordered: dict[str, dict] = {}
    for status in run_statuses:
        for slug, (display, ok) in status.items():
            entry = ordered.setdefault(slug, {"display": display, "seq": []})
            entry["display"] = display
            entry["seq"].append(ok)

    report: dict[str, dict] = {}
    for slug, entry in ordered.items():
        seq = entry["seq"]
        current = max_fail = 0
        for ok in seq:
            current = 0 if ok else current + 1
            max_fail = max(max_fail, current)
        report[slug] = {
            "display": entry["display"],
            "max_consecutive_failures": max_fail,
            "currently_down": bool(seq) and not seq[-1],
            "runs": len(seq),
        }
    return report


def build_message(report: dict[str, dict], run_count: int) -> str:
    day = datetime.now(MST).strftime("%b %d")
    failing = {
        slug: data
        for slug, data in report.items()
        if data["max_consecutive_failures"] >= THRESHOLD
    }
    lines = [f"🩺 Job Buddy portal health — {day} (MST)", f"Scrape runs scanned: {run_count}", ""]
    if not failing:
        lines.append(f"All portals healthy. None hit {THRESHOLD} consecutive failures today.")
        return "\n".join(lines)

    lines.append(f"Portals that failed {THRESHOLD}+ times in a row today:")
    for slug, data in sorted(
        failing.items(), key=lambda kv: kv[1]["max_consecutive_failures"], reverse=True
    ):
        state = "STILL DOWN" if data["currently_down"] else "recovered"
        lines.append(
            f"• {data['display']}: {data['max_consecutive_failures']} in a row, {state}"
        )
    healthy = len(report) - len(failing)
    lines.append("")
    lines.append(f"Other portals checked: {healthy} healthy.")
    return "\n".join(lines)


async def main() -> None:
    if not REPO or not TOKEN:
        print("[health] GITHUB_REPOSITORY / GITHUB_TOKEN not set; cannot read runs.")
        return

    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    with httpx.Client(headers=_HEADERS, timeout=60) as client:
        runs = list_runs(client, since)
        print(f"[health] scanning {len(runs)} scrape runs since {since.isoformat()}")
        statuses = []
        for run in runs[:400]:
            text = fetch_log_text(client, run["id"])
            if text:
                statuses.append(parse_run(text))

    report = analyze(statuses)
    message = build_message(report, len(statuses))
    print(message)
    await notifier.send_plain(message)


if __name__ == "__main__":
    asyncio.run(main())
