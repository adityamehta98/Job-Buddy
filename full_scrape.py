#!/usr/bin/env python3
"""
One-time script to seed seen_jobs.json for one or more configured companies.
Run this locally once if you want future notifier runs to alert only on newly posted roles.
"""

import argparse
import asyncio
import sys
import time

from playwright.async_api import async_playwright

import config
from location_filter import is_us_location
from runner import collect_jobs
from state import is_excluded_role, replace_seen_jobs, should_exclude_title


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the seen-job state for configured companies.")
    parser.add_argument(
        "--company",
        action="append",
        dest="companies",
        help="Company slug to seed. Repeat or pass a comma-separated list.",
    )
    return parser.parse_args()


async def _seed_company_jobs(browser, slug: str) -> bool:
    runtime_config = None

    try:
        runtime_config = config.get_company_runtime(slug)
        unique_jobs = await collect_jobs(browser, runtime_config, runtime_config.full_scrape_max_pages)
        filtered_jobs = [
            job
            for job in unique_jobs
            if not should_exclude_title(
                job.get("title", ""),
                runtime_config.excluded_role_keywords,
                runtime_config.excluded_title_phrases,
            )
        ]
        filtered_jobs = [
            job
            for job in filtered_jobs
            if not is_excluded_role(job.get("title", ""), runtime_config.excluded_role_keywords)
        ]
        title_filtered_count = len(unique_jobs) - len(filtered_jobs)
        if config.US_ONLY:
            before_location = len(filtered_jobs)
            filtered_jobs = [
                job for job in filtered_jobs
                if is_us_location(job.get("location", ""), config.ALLOW_REMOTE)
            ]
            location_filtered_count = before_location - len(filtered_jobs)
            if location_filtered_count:
                print(f"[{runtime_config.slug}] Excluded {location_filtered_count} non-US/unknown-location job(s) during seed")

        if title_filtered_count:
            print(f"[{runtime_config.slug}] Excluded {title_filtered_count} job(s) by title filter during seed")

        replace_seen_jobs(runtime_config, filtered_jobs)
        print(
            f"[full-scrape] Saved {len(filtered_jobs)} entries for "
            f"{runtime_config.display_name} to {config.SEEN_JOBS_DIR}"
        )
        return True
    except Exception as exc:
        company_name = runtime_config.display_name if runtime_config else slug
        print(f"[{slug}] Failed to seed {company_name}: {exc}")
        return False


async def scrape_all_jobs(selected_companies: list[str] | None = None) -> None:
    requested_companies = config.get_selected_company_slugs(selected_companies)

    print("=" * 60)
    print("[full-scrape] Seeding seen-job state")
    print(f"[full-scrape] Companies: {', '.join(requested_companies)}")
    print("=" * 60)

    failed_companies = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            for slug in requested_companies:
                if not await _seed_company_jobs(browser, slug):
                    failed_companies.append(slug)
        finally:
            await browser.close()

    print("[full-scrape] Done.")

    if failed_companies:
        print(f"[full-scrape] Failed companies: {', '.join(failed_companies)}")
        sys.exit(1)


if __name__ == "__main__":
    started_at = time.time()
    args = parse_args()
    asyncio.run(scrape_all_jobs(args.companies))
    print(f"[full-scrape] Completed in {time.time() - started_at:.1f}s")
