from __future__ import annotations

from typing import Mapping


def next_page_from_headers(headers: Mapping[str, str]) -> int | None:
    """
    GitLab API pagination: uses X-Next-Page header.
    Returns next page number if present, otherwise None.
    """
    raw = (headers.get("X-Next-Page") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None

