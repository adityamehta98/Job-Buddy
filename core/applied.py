#!/usr/bin/env python3
"""Mark jobs as applied (so they are suppressed forever) or list applied jobs.

Examples:
    # Mark two Chime jobs as applied (keys are the 🆔 shown in the alert,
    # or the job_id / key stored in seen_jobs/<slug>.json)
    python applied.py --company chime --id gh-4461450008 --id gh-5391376008

    # List everything you've marked applied for a company
    python applied.py --company chime --list

    # List applied jobs across every company
    python applied.py --list-all
"""

import argparse

from companies import list_companies
from core.state import list_applied, mark_applied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track jobs you've applied to.")
    parser.add_argument("--company", help="Company slug (e.g. chime, anthropic, apple).")
    parser.add_argument(
        "--id",
        action="append",
        dest="ids",
        default=[],
        help="Job key/id to mark applied. Repeat for multiple.",
    )
    parser.add_argument("--list", action="store_true", help="List applied jobs for --company.")
    parser.add_argument("--list-all", action="store_true", help="List applied jobs for all companies.")
    return parser.parse_args()


def _print_applied(slug: str) -> None:
    applied = list_applied(slug)
    if not applied:
        print(f"[{slug}] No applied jobs recorded.")
        return
    print(f"[{slug}] {len(applied)} applied job(s):")
    for item in applied:
        when = item.get("applied_at", "")
        title = item.get("title") or "(no title)"
        print(f"  - {when}  {title}  [{item['key']}]  {item.get('url', '')}")


def main() -> None:
    args = parse_args()

    if args.list_all:
        for slug in list_companies():
            _print_applied(slug)
        return

    if not args.company:
        raise SystemExit("Error: --company is required (or use --list-all).")

    slug = args.company.strip().lower()

    if args.ids:
        updated = mark_applied(slug, args.ids)
        print(f"[{slug}] Marked {len(updated)} job(s) as applied: {', '.join(updated) or '(none new)'}")

    if args.list or not args.ids:
        _print_applied(slug)


if __name__ == "__main__":
    main()
