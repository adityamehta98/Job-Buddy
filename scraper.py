#!/usr/bin/env python3
"""
Job Buddy job scraper.
Scrapes configured careers pages and sends alerts for newly seen jobs.
"""

import argparse
import asyncio
import sys
import time

from playwright.async_api import async_playwright

import config
from core import jd_fetch
from core import matcher
from core import resume_store
from core.location_filter import is_us_location
from core.notifier import send_company_digest, send_error, verify_channels
from core.runner import collect_jobs
from core.state import (
    filter_new_jobs,
    is_excluded_role,
    job_age_within,
    load_seen_jobs,
    record_scrape_result,
    should_exclude_title,
    should_include_title,
    update_seen_job_details,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape configured company career sites and send alerts.")
    parser.add_argument(
        "--company",
        action="append",
        dest="companies",
        help="Company slug to scrape. Repeat or pass a comma-separated list.",
    )
    return parser.parse_args()


async def _run_company_scrape(browser, slug: str) -> bool:
    runtime_config = None

    try:
        runtime_config = config.get_company_runtime(slug)
        unique_jobs = await collect_jobs(browser, runtime_config, runtime_config.max_pages)

        if not unique_jobs:
            if runtime_config.definition.allow_empty_results:
                print(
                    f"[scraper] WARNING: No jobs were extracted for "
                    f"{runtime_config.display_name}. Treating as non-fatal for this company."
                )
                record_scrape_result(runtime_config.slug, True)
                return True

            print(f"[scraper] No jobs were extracted for {runtime_config.display_name}.")
            error_message = "No jobs extracted after retries. The page may be unavailable or changed."
            if record_scrape_result(runtime_config.slug, False, error_message):
                await send_error(runtime_config.display_name, error_message)
            else:
                print(
                    f"[{runtime_config.slug}] Suppressing transient/repeated failure alert; "
                    "details remain in the workflow log and artifacts."
                )
            return False

        # Enforce geography immediately after parsing, before a role can enter
        # seen state, matching, or notification. ATS country query parameters
        # are inconsistent, so this normalized post-parse guard is authoritative.
        if config.US_ONLY:
            before_location = len(unique_jobs)
            unique_jobs = [
                job for job in unique_jobs
                if is_us_location(job.get("location", ""), config.ALLOW_REMOTE)
            ]
            dropped_location = before_location - len(unique_jobs)
            if dropped_location:
                print(
                    f"[{runtime_config.slug}] Dropped {dropped_location} "
                    "non-US/unknown-location job(s) before state and matching"
                )
            if not unique_jobs:
                print(f"[{runtime_config.slug}] No US jobs remained after location filtering.")
                return True

        # Preserve the real post date before filter_new_jobs overwrites it.
        for job in unique_jobs:
            job["_posted_raw"] = job.get("posted", "")

        # Apply eligibility filters before seen-state insertion. This keeps the
        # persisted list aligned with the roles that can actually be notified.
        before = len(unique_jobs)
        unique_jobs = [
            job
            for job in unique_jobs
            if not should_exclude_title(
                job.get("title", ""),
                runtime_config.excluded_role_keywords,
                runtime_config.excluded_title_phrases,
            )
        ]
        unique_jobs = [
            job
            for job in unique_jobs
            if not is_excluded_role(job.get("title", ""), runtime_config.excluded_role_keywords)
        ]
        excluded = before - len(unique_jobs)
        if excluded:
            print(f"[{runtime_config.slug}] Excluded {excluded} job(s) by title filter")

        # Positive relevance filter (2c): keep only titles that match the
        # include keywords (global config.INCLUDE_KEYWORDS + per-company).
        include_keywords = runtime_config.included_role_keywords
        if include_keywords:
            before_include = len(unique_jobs)
            unique_jobs = [
                job
                for job in unique_jobs
                if should_include_title(job.get("title", ""), include_keywords)
            ]
            dropped = before_include - len(unique_jobs)
            if dropped:
                print(f"[{runtime_config.slug}] Dropped {dropped} job(s) not matching include keywords")

        # Apply the strict recency window before state insertion. Jobs without
        # a verifiable post date are excluded when a maximum age is active.
        if config.MAX_AGE_HOURS > 0:
            before_age = len(unique_jobs)
            unique_jobs = [
                job
                for job in unique_jobs
                if job_age_within(job.get("_posted_raw", ""), config.MAX_AGE_HOURS)
            ]
            dropped_age = before_age - len(unique_jobs)
            if dropped_age:
                print(
                    f"[{runtime_config.slug}] Dropped {dropped_age} job(s) "
                    f"older than {config.MAX_AGE_HOURS}h or missing a post date"
                )

        new_jobs = filter_new_jobs(runtime_config, unique_jobs)
        print(f"[{runtime_config.slug}] New jobs (not seen before): {len(new_jobs)}")

        # Fetch full descriptions for roles that only have a title (big built-ins),
        # so they can be scored against the CV like the API-based companies.
        cv_text = resume_store.scraper_cv_text() if config.MATCH_THRESHOLD > 0 else ""
        # Description capture serves both the detail UI and CV matching, so it
        # must not depend on a resume being present in this runner.
        if config.FETCH_JOB_DESCRIPTIONS:
            need_desc = [
                job
                for job in new_jobs
                if len((job.get("description") or "").strip()) < 50 and job.get("url")
            ]
            if need_desc:
                to_fetch = need_desc[: config.JD_FETCH_LIMIT]
                print(
                    f"[{runtime_config.slug}] Fetching descriptions for "
                    f"{len(to_fetch)}/{len(need_desc)} role(s)..."
                )
                fetch_context = await browser.new_context(user_agent=jd_fetch.UA)
                try:
                    for job in to_fetch:
                        job["description"] = await jd_fetch.fetch_job_text(
                            fetch_context, job.get("url", ""), config.PAGE_LOAD_TIMEOUT
                        )
                finally:
                    await fetch_context.close()

        # Persist descriptions even for jobs that a later match-threshold
        # filter suppresses from notifications; the UI still needs their JDs.
        update_seen_job_details(runtime_config.slug, new_jobs)

        # CV match filter: drop only jobs we CAN score that fall below the
        # threshold. Jobs we cannot score (no job description available, or no
        # resume set) are kept and flagged, so you still get notified and know
        # the match was not computed.
        if config.MATCH_THRESHOLD > 0:
            kept = []
            dropped_match = 0
            unscored = 0
            for job in new_jobs:
                description = (job.get("description") or "").strip()
                if cv_text and len(description) >= 50:
                    result = matcher.score(
                        cv_text,
                        " ".join([job.get("title", ""), job.get("team", ""), description]),
                    )
                    score_val = result.get("match")
                    job.update(result)
                else:
                    score_val = None  # not enough to score reliably
                job["match"] = score_val
                if score_val is None:
                    if not cv_text:
                        job["match_note"] = "CV match not computed (no resume set)"
                    elif len(description) < 50:
                        job["match_note"] = "CV match not computed (no job description)"
                    else:
                        job["match_note"] = "CV match not computed (no recognized JD skills)"
                    unscored += 1
                    kept.append(job)  # still notify
                elif score_val >= config.MATCH_THRESHOLD:
                    kept.append(job)
                else:
                    dropped_match += 1
            new_jobs = kept
            if dropped_match:
                print(f"[{runtime_config.slug}] Dropped {dropped_match} job(s) below {config.MATCH_THRESHOLD}% CV match")
            if unscored:
                print(f"[{runtime_config.slug}] {unscored} job(s) could not be scored; notifying anyway")

        # Save transparent match evidence for the jobs that remain notifyable.
        update_seen_job_details(runtime_config.slug, new_jobs)

        if new_jobs:
            print(
                f"[{runtime_config.slug}] Sending one company digest "
                f"containing {len(new_jobs)} job(s)..."
            )
            success = await send_company_digest(runtime_config.display_name, new_jobs)
            if not success:
                print(f"[{runtime_config.slug}] Failed to send company digest")
        else:
            print(f"[{runtime_config.slug}] No new jobs to notify.")

        print(
            f"[{runtime_config.slug}] Seen jobs database: "
            f"{len(load_seen_jobs(runtime_config.slug))} entries"
        )
        record_scrape_result(runtime_config.slug, True)
        return True
    except Exception as exc:
        company_name = runtime_config.display_name if runtime_config else slug
        print(f"[{slug}] Unexpected company failure: {exc}")
        error_message = f"Unexpected error: {exc}"
        if record_scrape_result(slug, False, error_message):
            await send_error(company_name, error_message)
        else:
            print(
                f"[{slug}] Suppressing transient/repeated failure alert; "
                "details remain in the workflow log and artifacts."
            )
        return False


async def run_scraper(selected_companies: list[str] | None = None) -> None:
    """Main scraper entry point."""
    start_time = time.time()
    requested_companies = config.get_selected_company_slugs(selected_companies)

    print("=" * 60)
    print("[scraper] Job Buddy starting")
    print(f"[scraper] Companies: {', '.join(requested_companies)}")
    print(f"[scraper] Channels: {', '.join(config.NOTIFY_CHANNELS)}")
    print("=" * 60)

    channels_ok = await verify_channels()
    if not channels_ok:
        print("[scraper] WARNING: No notification channel verified. Alerts may not be delivered.")

    failed_companies = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            for slug in requested_companies:
                if not await _run_company_scrape(browser, slug):
                    failed_companies.append(slug)
        finally:
            await browser.close()

    elapsed = time.time() - start_time
    print(f"\n[scraper] Run completed in {elapsed:.1f}s")

    if failed_companies:
        print(f"[scraper] Failed companies: {', '.join(failed_companies)}")
        sys.exit(1)


def main() -> None:
    args = parse_args()
    asyncio.run(run_scraper(args.companies))


if __name__ == "__main__":
    main()
