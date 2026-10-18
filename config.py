"""Shared configuration for Job Buddy."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from companies import get_company, list_companies
from companies.base import CompanyDefinition

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Notification channels: comma-separated, any of: telegram, whatsapp
NOTIFY_CHANNELS = tuple(
    c.strip().lower()
    for c in os.getenv("NOTIFY_CHANNELS", "telegram").split(",")
    if c.strip()
) or ("telegram",)

# WhatsApp via Green API (free Developer plan). Create an instance at
# https://green-api.com, link your WhatsApp by scanning the QR, then copy the
# idInstance, apiTokenInstance and ApiUrl from the console.
GREENAPI_API_URL = os.getenv("GREENAPI_API_URL", "https://api.green-api.com")
GREENAPI_ID_INSTANCE = os.getenv("GREENAPI_ID_INSTANCE", "")
GREENAPI_API_TOKEN = os.getenv("GREENAPI_API_TOKEN", "")


def _normalize_chat_id(raw: str) -> str:
    """Accept a bare phone number or a full Green API chatId (``...@c.us``)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "@" in raw:
        return raw
    digits = re.sub(r"\D", "", raw)
    return f"{digits}@c.us" if digits else ""


# Your own WhatsApp number to receive alerts, e.g. 14155551234 or +1 415 555 1234
GREENAPI_CHAT_ID = _normalize_chat_id(os.getenv("GREENAPI_CHAT_ID", ""))

# ntfy (free push to your phone, no account, no token). Install the ntfy app,
# subscribe to a unique topic, and set NTFY_TOPIC to that topic name.
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")

# Discord: paste a channel webhook URL (Server Settings > Integrations > Webhooks)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Scraping
PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", "15000"))
JOB_CARD_TIMEOUT = int(os.getenv("JOB_CARD_TIMEOUT", "8000"))

# ---- Alerting limits ------------------------------------------------------- #

def _int_env(name: str, default: int) -> int:
    """Read an int env var, tolerating unset or empty values (e.g. unset CI vars)."""
    raw = os.getenv(name, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


# Scrape at most this many pages per company (set 0 to disable the cap).
MAX_PAGES_CAP = _int_env("MAX_PAGES_CAP", 5)
# Only alert on jobs posted within this many hours, when a real post date is
# known. 0 disables it; jobs with no parseable date are always kept.
MAX_AGE_HOURS = _int_env("MAX_AGE_HOURS", 24)
# Only alert on jobs whose CV match is at least this percent. 0 disables it.
# Needs an active resume (uploaded in the UI) or a file set via CV_PATH.
MATCH_THRESHOLD = _int_env("MATCH_THRESHOLD", 75)
# Optional resume file for match scoring in headless runs (e.g. GitHub Actions),
# since resumes uploaded in the UI live only on your local machine.
CV_PATH = os.getenv("CV_PATH", "")
# Fetch each role's full description page so title-only built-ins (Apple,
# Amazon, Google) can be scored too. Slower; set 0 to disable. Only runs for
# matching, recent roles that have no description yet.
FETCH_JOB_DESCRIPTIONS = _int_env("FETCH_JOB_DESCRIPTIONS", 1)
# Cap descriptions fetched per company per run, to keep run time bounded.
JD_FETCH_LIMIT = _int_env("JD_FETCH_LIMIT", 30)
# Keep jobs with an explicit United States signal. ALLOW_REMOTE separately
# permits country-ambiguous remote roles while rejecting explicitly foreign ones.
US_ONLY = _bool_env("US_ONLY", True)
# Include remote roles unless their location explicitly limits them to a
# foreign geography (for example, "Remote - UK" or "Remote, Canada").
ALLOW_REMOTE = _bool_env("ALLOW_REMOTE", True)

# State
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_JOBS_DIR = os.path.join(BASE_DIR, "seen_jobs")
MAX_SEEN_JOBS = int(os.getenv("MAX_SEEN_JOBS", "3000"))

# Diagnostics
SCRAPE_ARTIFACTS_DIR = Path(
    os.getenv("SCRAPE_ARTIFACTS_DIR", os.path.join(BASE_DIR, "artifacts"))
)

DEFAULT_COMPANIES = ("apple",)

# ---- Relevance filter (2c) ------------------------------------------------- #
# Only job titles containing one of these substrings (case-insensitive) are
# alerted on. Set the INCLUDE_KEYWORDS env var to a comma-separated list to
# override, or set it to a single space (" ") / "all" to disable filtering and
# receive every (non-excluded) role. Edit the defaults below to taste.
DEFAULT_INCLUDE_KEYWORDS = (
    # Software engineering / development roles
    "software engineer",
    "software developer",
    "full stack",
    "fullstack",
    "full-stack",
    "backend",
    "back end",
    "back-end",
    "frontend",
    "front end",
    "front-end",
    "web developer",
    "application developer",
    "sde",
    "swe",
    # Data / analytics
    "data engineer",
    "data analyst",
    "data analytics",
    "analytics engineer",
    "data scientist",
    # AI / ML
    "ai engineer",
    "artificial intelligence",
    "machine learning",
    "ml engineer",
    "mlops",
    # Cloud / platform / infrastructure
    "cloud",
    "aws",
    "devops",
    "site reliability",
    "sre",
    "platform engineer",
)


def _parse_keyword_list(raw: str) -> tuple[str, ...]:
    items = [item.strip() for item in raw.split(",")]
    return tuple(item for item in items if item)


_include_env = os.getenv("INCLUDE_KEYWORDS")
if _include_env is None or _include_env.strip() == "":
    # Unset or empty -> use the sensible defaults above (filtering ON).
    INCLUDE_KEYWORDS: tuple[str, ...] = DEFAULT_INCLUDE_KEYWORDS
elif _include_env.strip().lower() in {"all", "*"}:
    INCLUDE_KEYWORDS = ()  # explicitly disable filtering -> alert on everything
else:
    INCLUDE_KEYWORDS = _parse_keyword_list(_include_env)


@dataclass(frozen=True)
class CompanyRuntimeConfig:
    definition: CompanyDefinition
    search_url: str
    max_pages: int
    full_scrape_max_pages: int

    @property
    def slug(self) -> str:
        return self.definition.slug

    @property
    def display_name(self) -> str:
        return self.definition.display_name

    @property
    def excluded_role_keywords(self) -> tuple[str, ...]:
        return self.definition.excluded_role_keywords

    @property
    def excluded_title_phrases(self) -> tuple[str, ...]:
        return self.definition.excluded_title_phrases

    @property
    def included_role_keywords(self) -> tuple[str, ...]:
        """Global include keywords plus any company-specific ones."""
        return tuple(INCLUDE_KEYWORDS) + tuple(self.definition.included_role_keywords)


def _company_env_prefix(slug: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", slug.upper())


def _company_env_name(slug: str, setting: str) -> str:
    return f"{_company_env_prefix(slug)}_{setting}"


def _parse_company_list(raw_value: str) -> list[str]:
    items = [item.strip().lower() for item in raw_value.split(",") if item.strip()]
    unique_items = []
    seen_items = set()
    for item in items:
        if item not in seen_items:
            seen_items.add(item)
            unique_items.append(item)
    return unique_items


def get_selected_company_slugs(cli_companies: list[str] | None = None) -> list[str]:
    if cli_companies:
        requested = []
        for value in cli_companies:
            requested.extend(_parse_company_list(value))
    else:
        requested = _parse_company_list(os.getenv("COMPANIES", ",".join(DEFAULT_COMPANIES)))

    if not requested:
        requested = list(DEFAULT_COMPANIES)

    # "all" is a convenience token meaning every registered company
    # (built-in + custom companies from custom_companies.json).
    if "all" in requested:
        return list_companies()

    supported = set(list_companies())
    invalid = [slug for slug in requested if slug not in supported]
    if invalid:
        supported_list = ", ".join(sorted(supported))
        invalid_list = ", ".join(invalid)
        raise ValueError(f"Unsupported companies: {invalid_list}. Supported companies: {supported_list}")

    return requested


def get_company_runtime(slug: str) -> CompanyRuntimeConfig:
    definition = get_company(slug)
    search_url = os.getenv(
        _company_env_name(definition.slug, "SEARCH_URL"),
        definition.default_search_url,
    )
    max_pages = int(
        os.getenv(
            _company_env_name(definition.slug, "MAX_PAGES"),
            str(definition.default_max_pages),
        )
    )
    full_scrape_max_pages = int(
        os.getenv(
            _company_env_name(definition.slug, "FULL_SCRAPE_MAX_PAGES"),
            str(definition.default_full_scrape_max_pages),
        )
    )
    if MAX_PAGES_CAP > 0:
        max_pages = min(max_pages, MAX_PAGES_CAP)
        full_scrape_max_pages = min(full_scrape_max_pages, MAX_PAGES_CAP)

    return CompanyRuntimeConfig(
        definition=definition,
        search_url=search_url,
        max_pages=max_pages,
        full_scrape_max_pages=full_scrape_max_pages,
    )
