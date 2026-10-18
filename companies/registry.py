import json
import os

from companies.amazon import COMPANY as AMAZON
from companies.apple import COMPANY as APPLE
from companies.base import CompanyDefinition
from companies.cvs import COMPANY as CVS
from companies.cvs_wd import COMPANY as CVS_WD
from companies.generic_ats import build_custom_company
from companies.goldman_sachs import COMPANY as GOLDMAN_SACHS
from companies.google import COMPANY as GOOGLE
from companies.lyft import COMPANY as LYFT
from companies.meta import COMPANY as META
from companies.salesforce import COMPANY as SALESFORCE
from companies.uber import COMPANY as UBER

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CUSTOM_CONFIG = os.path.join(_REPO_ROOT, "custom_companies.json")

COMPANIES: dict[str, CompanyDefinition] = {
    AMAZON.slug: AMAZON,
    APPLE.slug: APPLE,
    CVS.slug: CVS,
    CVS_WD.slug: CVS_WD,
    GOLDMAN_SACHS.slug: GOLDMAN_SACHS,
    GOOGLE.slug: GOOGLE,
    LYFT.slug: LYFT,
    META.slug: META,
    SALESFORCE.slug: SALESFORCE,
    UBER.slug: UBER,
}


def _as_tuple(value) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _load_custom_companies() -> None:
    """Merge user-defined companies from custom_companies.json into the registry."""
    if not os.path.exists(_CUSTOM_CONFIG):
        return
    try:
        with open(_CUSTOM_CONFIG, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[registry] WARNING: could not read custom_companies.json: {exc}")
        return

    entries = data.get("companies", []) if isinstance(data, dict) else data
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not name or not url:
            print(f"[registry] WARNING: skipping custom company with missing name/url: {entry!r}")
            continue
        try:
            definition = build_custom_company(
                name,
                url,
                ats=(entry.get("ats") or None),
                token=(entry.get("token") or None),
                included_role_keywords=_as_tuple(entry.get("included_role_keywords")),
                excluded_role_keywords=_as_tuple(entry.get("excluded_role_keywords")),
                excluded_title_phrases=_as_tuple(entry.get("excluded_title_phrases")),
            )
        except Exception as exc:  # defensive: one bad entry shouldn't break startup
            print(f"[registry] WARNING: could not load custom company '{name}': {exc}")
            continue

        if definition.slug in COMPANIES:
            print(
                f"[registry] WARNING: custom company '{name}' -> slug '{definition.slug}' "
                f"clashes with an existing company; skipping."
            )
            continue
        COMPANIES[definition.slug] = definition


_load_custom_companies()


def get_company(slug: str) -> CompanyDefinition:
    normalized_slug = slug.strip().lower()
    try:
        return COMPANIES[normalized_slug]
    except KeyError as exc:
        supported = ", ".join(sorted(COMPANIES))
        raise ValueError(f"Unsupported company '{slug}'. Supported companies: {supported}") from exc


def list_companies() -> list[str]:
    return sorted(COMPANIES)
