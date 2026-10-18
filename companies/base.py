from dataclasses import dataclass
from typing import Awaitable, Callable

Job = dict[str, str]
PageMetricExtractor = Callable[[str], int | None]
ParseJobs = Callable[[str], list[Job]]
BuildSearchUrl = Callable[[str, int], str]
FetchPageHtml = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class CompanyDefinition:
    slug: str
    display_name: str
    default_search_url: str
    default_max_pages: int
    default_full_scrape_max_pages: int
    wait_selectors: tuple[str, ...]
    build_search_url: BuildSearchUrl
    parse_jobs: ParseJobs
    get_total_pages: PageMetricExtractor
    get_total_results: PageMetricExtractor
    fetch_page_html: FetchPageHtml | None = None
    full_scrape_posted_strategy: str = "source"
    regular_scrape_posted_strategy: str = "new-only-today"
    excluded_role_keywords: tuple[str, ...] = ()
    excluded_title_phrases: tuple[str, ...] = ()
    # Positive relevance filter: when non-empty, only titles containing one of
    # these substrings are kept. Combined with the global config.INCLUDE_KEYWORDS.
    included_role_keywords: tuple[str, ...] = ()
    allow_empty_results: bool = False
