"""Strict United States location filtering shared by the UI and scraper.

Job boards do not expose a consistent country field, so this module accepts an
explicit US signal plus remote roles that are not explicitly restricted to a
foreign geography.
"""

from __future__ import annotations

import re


_STATE_CODES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
    "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR", "GU", "VI",
)

_STATE_NAMES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
    "puerto rico", "guam", "u.s. virgin islands",
)

_COUNTRY_RE = re.compile(
    r"\b(?:united states(?: of america)?|u\.?s\.?(?:a\.?)?)\b", re.IGNORECASE
)
_STATE_NAME_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(name) for name in _STATE_NAMES) + r")\b",
    re.IGNORECASE,
)
# State abbreviations must be uppercase and location-shaped. This avoids
# interpreting words such as "in", "or", and "me" as state codes.
_STATE_CODE_RE = re.compile(
    r"(?:^|[,;/|]\s*|\s[-–—]\s)(?:" + "|".join(_STATE_CODES) +
    r")(?:\s+\d{5}(?:-\d{4})?)?(?=$|[,;/|\s])"
)
_US_REMOTE_RE = re.compile(
    r"\b(?:remote\s*(?:[-–—,/|]|in)?\s*(?:united states|u\.?s\.?(?:a\.?)?)|"
    r"(?:united states|u\.?s\.?(?:a\.?)?)\s*(?:[-–—,/|]|only)?\s*remote)\b",
    re.IGNORECASE,
)
_REMOTE_RE = re.compile(
    r"\b(?:remote(?:[- ]friendly)?|work from (?:home|anywhere)|anywhere|distributed)\b",
    re.IGNORECASE,
)
_FOREIGN_GEOGRAPHY_RE = re.compile(
    r"\b(?:united kingdom|uk|canada|india|europe|eu|emea|apac|latam|"
    r"australia|new zealand|germany|france|ireland|netherlands|spain|portugal|"
    r"italy|sweden|norway|denmark|finland|poland|switzerland|austria|belgium|"
    r"brazil|mexico|singapore|japan|china|hong kong|taiwan|south korea|"
    r"united arab emirates|uae|israel|africa)\b",
    re.IGNORECASE,
)


def is_us_location(location: str, allow_remote: bool = True) -> bool:
    """Accept US roles and, optionally, remote roles without a foreign restriction."""
    text = " ".join(str(location or "").split())
    if not text:
        return False
    if bool(
        _COUNTRY_RE.search(text)
        or _US_REMOTE_RE.search(text)
        or _STATE_NAME_RE.search(text)
        or _STATE_CODE_RE.search(text)
    ):
        return True
    return bool(
        allow_remote
        and _REMOTE_RE.search(text)
        and not _FOREIGN_GEOGRAPHY_RE.search(text)
    )
