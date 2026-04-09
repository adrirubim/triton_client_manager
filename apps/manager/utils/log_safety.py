from __future__ import annotations

import hashlib


def safe_log_id(value: object) -> str:
    """
    Return a stable, non-reversible identifier for logs.

    We keep traceability (same input -> same output) while avoiding clear-text
    identifiers that CodeQL may treat as sensitive (e.g. correlation IDs).
    """

    if value is None:
        return "-"

    s = str(value).strip()
    if not s:
        return "-"

    digest = hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"
