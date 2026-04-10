from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TagChoice:
    name: str
    created_at: datetime | None
    updated_at: datetime | None


def _parse_gitlab_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    # GitLab often returns ISO strings ending in 'Z'
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _coerce_tag(tag: dict) -> TagChoice | None:
    name = (tag.get("name") or "").strip()
    if not name:
        return None
    return TagChoice(
        name=name,
        created_at=_parse_gitlab_ts(tag.get("created_at")),
        updated_at=_parse_gitlab_ts(tag.get("updated_at")),
    )


def choose_tag_name(
    *,
    tags: list[dict],
    strategy: str = "updated_at",
    name_regex: str | None = None,
) -> str | None:
    """
    Pick a deterministic tag name from GitLab tag objects.

    Supported strategies:
      - "updated_at" (default): max(updated_at, fallback created_at)
      - "created_at": max(created_at, fallback updated_at)

    Optional name_regex filters candidates first.
    """
    strategy_norm = (strategy or "updated_at").strip().lower()
    if strategy_norm not in {"updated_at", "created_at"}:
        raise ValueError(
            f"Invalid tag_selection_strategy: {strategy!r} "
            "(expected 'updated_at' or 'created_at')"
        )

    rx = re.compile(name_regex) if (name_regex and name_regex.strip()) else None
    choices: list[TagChoice] = []
    for t in tags:
        if not isinstance(t, dict):
            continue
        choice = _coerce_tag(t)
        if choice is None:
            continue
        if rx and not rx.search(choice.name):
            continue
        choices.append(choice)

    if not choices:
        return None

    def key_updated(c: TagChoice):
        ts = c.updated_at or c.created_at or datetime.fromtimestamp(0, tz=timezone.utc)
        return (ts, c.name)

    def key_created(c: TagChoice):
        ts = c.created_at or c.updated_at or datetime.fromtimestamp(0, tz=timezone.utc)
        return (ts, c.name)

    key_fn = key_updated if strategy_norm == "updated_at" else key_created
    return max(choices, key=key_fn).name

