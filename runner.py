from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeout

import config

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
BROWSER_VIEWPORT = {"width": 1440, "height": 1200}


async def scrape_page(page, runtime_config: config.CompanyRuntimeConfig, url: str) -> str:
    if runtime_config.definition.fetch_page_html:
        return await runtime_config.definition.fetch_page_html(page, runtime_config, url)

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"[{runtime_config.slug}] Loading: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT)
            break
        except PlaywrightTimeout:
            if attempt < max_attempts:
                print(
                    f"[{runtime_config.slug}] Timeout on goto (attempt {attempt}/{max_attempts}), retrying..."
                )
                await page.wait_for_timeout(2000)
            else:
                raise

    for selector in runtime_config.definition.wait_selectors:
        try:
            await page.wait_for_selector(selector, timeout=config.JOB_CARD_TIMEOUT)
            print(f"[{runtime_config.slug}] Results detected via selector: {selector}")
            break
        except PlaywrightTimeout:
            continue
    else:
        print(f"[{runtime_config.slug}] Result selectors did not appear in time; capturing page anyway.")

    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(1200)
    return await page.content()


async def collect_jobs(browser, runtime_config: config.CompanyRuntimeConfig, page_limit: int) -> list[dict]:
    print("=" * 60)
    print(f"[{runtime_config.slug}] Scraping {runtime_config.display_name} jobs")
    print(f"[{runtime_config.slug}] Search URL: {runtime_config.search_url}")
    print("=" * 60)

    all_jobs = []
    target_pages = page_limit
    context = await browser.new_context(user_agent=BROWSER_USER_AGENT, viewport=BROWSER_VIEWPORT)
    page = await context.new_page()

    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    try:
        for page_num in range(1, page_limit + 1):
            url = runtime_config.definition.build_search_url(runtime_config.search_url, page_num)
            try:
                html = await scrape_page(page, runtime_config, url)
                jobs = runtime_config.definition.parse_jobs(html)
                print(f"[{runtime_config.slug}] Page {page_num}: found {len(jobs)} jobs")

                if page_num == 1:
                    total_pages_from_ui = runtime_config.definition.get_total_pages(html)
                    if total_pages_from_ui:
                        target_pages = min(page_limit, max(1, total_pages_from_ui))
                        print(f"[{runtime_config.slug}] Total pages on site: {total_pages_from_ui}")
                    else:
                        total_results = runtime_config.definition.get_total_results(html)
                        if total_results:
                            inferred_page_count = max(
                                1,
                                (total_results + max(len(jobs), 1) - 1) // max(len(jobs), 1),
                            )
                            target_pages = min(page_limit, inferred_page_count)
                            print(f"[{runtime_config.slug}] Total matching jobs on site: {total_results}")

                    print(f"[{runtime_config.slug}] Scraping up to {target_pages} page(s) this run")

                if not jobs:
                    await _capture_diagnostics(
                        page,
                        runtime_config,
                        page_num,
                        "no_jobs_found",
                        html=html,
                    )
                    print(f"[{runtime_config.slug}] No jobs found on page {page_num}; stopping pagination.")
                    break

                all_jobs.extend(jobs)

                if page_num >= target_pages:
                    break

                await page.wait_for_timeout(500)

            except PlaywrightTimeout as exc:
                await _capture_diagnostics(page, runtime_config, page_num, "playwright_timeout")
                print(f"[{runtime_config.slug}] Timeout on page {page_num}: {exc}")
                break
            except Exception as exc:
                await _capture_diagnostics(page, runtime_config, page_num, "unexpected_error")
                print(f"[{runtime_config.slug}] Error on page {page_num}: {exc}")
                break
    finally:
        await context.close()

    unique_jobs = []
    seen_keys = set()
    for job in all_jobs:
        key = job.get("key")
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        unique_jobs.append(job)

    print(f"[{runtime_config.slug}] Total unique jobs scraped: {len(unique_jobs)}")
    return unique_jobs


async def _capture_diagnostics(
    page,
    runtime_config: config.CompanyRuntimeConfig,
    page_num: int,
    reason: str,
    *,
    html: str | None = None,
) -> None:
    safe_reason = reason.replace(" ", "_").lower()
    base_dir = config.SCRAPE_ARTIFACTS_DIR / runtime_config.slug / f"page-{page_num}-{safe_reason}"
    base_dir.mkdir(parents=True, exist_ok=True)

    html_path = base_dir / "page.html"
    meta_path = base_dir / "meta.txt"
    screenshot_path = base_dir / "page.png"

    if html is None:
        try:
            html = await page.content()
        except Exception as exc:
            html = f"<!-- failed to capture html: {exc} -->"

    html_path.write_text(html, encoding="utf-8")

    try:
        await page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception as exc:
        screenshot_path.write_text(f"screenshot capture failed: {exc}\n", encoding="utf-8")

    try:
        current_url = page.url
    except Exception:
        current_url = ""

    try:
        title = await page.title()
    except Exception:
        title = ""

    meta_path.write_text(
        "\n".join(
            (
                f"company={runtime_config.slug}",
                f"reason={reason}",
                f"page_num={page_num}",
                f"url={current_url}",
                f"title={title}",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    relative_dir = base_dir.relative_to(Path(config.BASE_DIR))
    print(f"[{runtime_config.slug}] Saved diagnostics to {relative_dir}")
