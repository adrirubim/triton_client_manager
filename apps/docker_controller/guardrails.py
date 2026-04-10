from __future__ import annotations

import re
from urllib.parse import urlparse

_LOCALHOST_NAMES = {"localhost", "127.0.0.1", "::1"}


def host_from_hostport(hostport: str) -> str:
    """
    Best-effort parse of a host from a hostport string.

    Examples:
      - "localhost:5000" -> "localhost"
      - "127.0.0.1:5000" -> "127.0.0.1"
      - "[::1]:5000"     -> "::1"
      - "::1"            -> "::1"
    """
    value = (hostport or "").strip()
    if not value:
        return ""

    if value.startswith("[") and "]" in value:
        return value[1 : value.index("]")]

    if "://" in value:
        parsed = urlparse(value)
        if parsed.hostname:
            return parsed.hostname

    if ":" in value and value.count(":") == 1:
        return value.split(":", 1)[0]

    return value


def is_local_registry_hostport(local_registry_hostport: str) -> bool:
    host = host_from_hostport(local_registry_hostport).lower()
    return host in _LOCALHOST_NAMES


def image_name_from_gitlab_location(location: str) -> str:
    loc = (location or "").strip().rstrip("/")
    if not loc:
        return ""
    return loc.split("/")[-1]


def compile_allowlist_regex(patterns: list[str]) -> list[re.Pattern]:
    compiled: list[re.Pattern] = []
    for p in patterns:
        p_norm = (p or "").strip()
        if not p_norm:
            continue
        compiled.append(re.compile(p_norm))
    return compiled


def load_allowlist(config: dict) -> tuple[set[str], list[re.Pattern]]:
    allowed_images = config.get("allowed_images") or []
    allowed_regex = config.get("allowed_image_regex") or []

    if isinstance(allowed_images, str):
        allowed_images = [allowed_images]
    if isinstance(allowed_regex, str):
        allowed_regex = [allowed_regex]

    allowed_images_norm = {str(x).strip() for x in allowed_images if str(x).strip()}
    compiled_regex = compile_allowlist_regex([str(x) for x in allowed_regex])

    if not allowed_images_norm and not compiled_regex:
        raise ValueError(
            "Supply-chain guardrail: you must configure an allowlist. "
            "Set 'allowed_images' and/or 'allowed_image_regex' in config.yaml."
        )

    return allowed_images_norm, compiled_regex


def is_allowed_image(
    *, location: str, allowed_images: set[str], allowed_regex: list[re.Pattern]
) -> bool:
    image_name = image_name_from_gitlab_location(location)
    if image_name and image_name in allowed_images:
        return True
    for rx in allowed_regex:
        if rx.search(location) or (image_name and rx.search(image_name)):
            return True
    return False


def validate_supply_chain_guardrails(
    *, config: dict, local_registry_hostport: str, local_registry_scheme: str
) -> tuple[set[str], list[re.Pattern]]:
    provider = (config.get("provider") or "gitlab").strip().lower()
    if provider not in {"gitlab", "ghcr"}:
        raise ValueError(
            f"Supply-chain guardrail: invalid provider {provider!r} "
            "(expected 'gitlab' or 'ghcr')."
        )

    if provider == "gitlab":
        gitlab_url = (config.get("gitlab_url") or "").strip()
        if not gitlab_url.startswith("https://"):
            raise ValueError(
                "Supply-chain guardrail: gitlab_url must start with 'https://'. "
                "Refusing to run with insecure GitLab transport."
            )
        if not config.get("project_id"):
            raise ValueError(
                "Supply-chain guardrail: project_id is required for provider=gitlab."
            )
    else:
        # GHCR does not need GitLab fields; it needs explicit image list.
        owner = (config.get("ghcr_owner") or "").strip()
        if not owner:
            raise ValueError(
                "Supply-chain guardrail: ghcr_owner is required for provider=ghcr."
            )
        remote_images = config.get("remote_images") or []
        if isinstance(remote_images, str):
            remote_images = [remote_images]
        remote_images = [str(x).strip() for x in remote_images if str(x).strip()]
        if not remote_images:
            raise ValueError(
                "Supply-chain guardrail: remote_images must be a non-empty list for provider=ghcr."
            )

    allow_nonlocal = bool(config.get("allow_nonlocal_registry", False))
    is_local = is_local_registry_hostport(local_registry_hostport)

    if not is_local:
        if not allow_nonlocal:
            raise ValueError(
                "Supply-chain guardrail: local_registry points to a non-local host. "
                "Refusing to run unless allow_nonlocal_registry=true is set."
            )
        if (local_registry_scheme or "").lower() != "https":
            raise ValueError(
                "Supply-chain guardrail: non-local local_registry requires "
                "local_registry_scheme=https."
            )

    return load_allowlist(config)

