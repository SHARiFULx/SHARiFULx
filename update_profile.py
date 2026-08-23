#!/usr/bin/env python3
"""Refresh public GitHub statistics in the profile SVG files."""

from __future__ import annotations

import calendar
import html
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USERNAME = "SHARiFULx"
API_URL = f"https://api.github.com/users/{USERNAME}"
SVG_FILES = ("dark_mode.svg", "light_mode.svg")
ROOT = Path(__file__).resolve().parent


def github_user() -> dict[str, Any]:
    """Return the public REST representation for the configured account."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-profile-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(API_URL, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the GitHub API: {exc.reason}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("GitHub API returned an unexpected response")
    if str(payload.get("login", "")).casefold() != USERNAME.casefold():
        raise RuntimeError("GitHub API returned a different account")
    return payload


def required_nonnegative_int(payload: dict[str, Any], key: str) -> int:
    """Read and validate a nonnegative integer from an API response."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"GitHub API field {key!r} is invalid")
    return value


def add_years(day: date, years: int) -> date:
    """Shift a date by complete calendar years, handling leap day."""
    year = day.year + years
    last_day = calendar.monthrange(year, day.month)[1]
    return day.replace(year=year, day=min(day.day, last_day))


def add_months(day: date, months: int) -> date:
    """Shift a date by complete calendar months."""
    month_index = day.year * 12 + day.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    last_day = calendar.monthrange(year, month)[1]
    return day.replace(year=year, month=month, day=min(day.day, last_day))


def calendar_age(start: date, end: date) -> str:
    """Format elapsed time as complete years, months, and days."""
    if end < start:
        raise ValueError("end date is earlier than start date")

    years = end.year - start.year
    if add_years(start, years) > end:
        years -= 1
    year_anchor = add_years(start, years)

    months = 0
    while months < 11 and add_months(year_anchor, months + 1) <= end:
        months += 1
    month_anchor = add_months(year_anchor, months)
    days = (end - month_anchor).days

    def unit(value: int, name: str) -> str:
        suffix = "" if value == 1 else "s"
        return f"{value} {name}{suffix}"

    return ", ".join(
        (unit(years, "year"), unit(months, "month"), unit(days, "day"))
    )


def created_date(payload: dict[str, Any]) -> date:
    """Parse the account creation timestamp returned by GitHub."""
    raw = payload.get("created_at")
    if not isinstance(raw, str):
        raise RuntimeError("GitHub API field 'created_at' is invalid")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise RuntimeError("GitHub API returned an invalid creation timestamp") from exc


def replace_svg_value(source: str, element_id: str, value: str) -> str:
    """Replace the text of one uniquely identified tspan."""
    pattern = re.compile(
        rf'(<tspan\b[^>]*\bid="{re.escape(element_id)}"[^>]*>)([^<]*)(</tspan>)'
    )
    escaped = html.escape(value, quote=False)
    updated, count = pattern.subn(lambda match: f"{match.group(1)}{escaped}{match.group(3)}", source)
    if count != 1:
        raise RuntimeError(
            f"Expected one SVG element with id {element_id!r}, found {count}"
        )
    return updated


def update_svg(path: Path, values: dict[str, str]) -> bool:
    """Atomically update a profile SVG and report whether it changed."""
    original = path.read_text(encoding="utf-8")
    updated = original
    for element_id, value in values.items():
        updated = replace_svg_value(updated, element_id, value)
    if updated == original:
        return False

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(updated)
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return True


def main() -> int:
    payload = github_user()
    today = datetime.now(timezone.utc).date()
    values = {
        "account_age": calendar_age(created_date(payload), today),
        "public_repos": str(required_nonnegative_int(payload, "public_repos")),
        "followers": str(required_nonnegative_int(payload, "followers")),
        "following": str(required_nonnegative_int(payload, "following")),
    }

    changed = []
    for filename in SVG_FILES:
        path = ROOT / filename
        if update_svg(path, values):
            changed.append(filename)

    if changed:
        print("Updated " + ", ".join(changed))
    else:
        print("Profile SVGs are already current")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"update_profile.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
