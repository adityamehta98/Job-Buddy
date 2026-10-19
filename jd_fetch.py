"""Fetch a single job's full description text with a headless browser.

Used to score title-only roles (big built-ins like Apple / Amazon / Google that
only expose a title in their listings) against the CV. One page load per role,
so the scraper only calls this for new, title-matching, recent roles and caps
how many it fetches per run.
"""

import re
from datetime import datetime

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_POSTED_DATE_RE = re.compile(
    r"(?:date\s+posted|posted(?:\s+on)?|publication\s+date)\s*:?\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def extract_posted_date(text: str) -> str:
    """Return an ISO date only when the detail page labels it as posted."""
    match = _POSTED_DATE_RE.search(" ".join(str(text or "").split()))
    if not match:
        return ""
    value = match.group(1)
    for date_format in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            pass
    return ""


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
