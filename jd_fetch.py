"""Fetch a single job's full description text with a headless browser.

Used to score title-only roles (big built-ins like Apple / Amazon / Google that
only expose a title in their listings) against the CV. One page load per role,
so the scraper only calls this for new, title-matching, recent roles and caps
how many it fetches per run.
"""

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


async def fetch_job_text(context, url: str, timeout_ms: int = 15000) -> str:
    """Load a job URL and return its visible text (cleaned, capped). '' on failure."""
    if not url:
        return ""
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(800)
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        return " ".join((text or "").split())[:8000]
    except Exception:
        return ""
    finally:
        try:
            await page.close()
        except Exception:
            pass
