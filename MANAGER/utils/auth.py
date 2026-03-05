"""Authentication helpers for WebSocket auth hardening.

This module is intentionally lightweight and focuses on **token structure and
claims validation**, not on cryptographic verification. It is designed to be
extended or swapped for project‑specific IdP integrations.

Main goals:

- Provide a clear extension point for token validation before accepting `auth`.
- Enforce basic claims such as `exp`, `aud`, `iss` when configured.
- Avoid logging or exposing raw tokens.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, Optional, Tuple

import jwt
from jwt import ExpiredSignatureError, InvalidAudienceError, InvalidIssuerError, PyJWKClient


def _b64url_decode(data: str) -> bytes:
    """Decode a base64url string without requiring padding."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    """Decode the payload part of a JWT without verifying the signature.

    The token is expected to have the form ``header.payload.signature``.
    Only the payload is parsed and returned as a dictionary.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    _header_b64, payload_b64, _sig_b64 = parts
    raw = _b64url_decode(payload_b64)
    return json.loads(raw.decode("utf-8"))


def validate_token(
    token: Optional[str],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Validate an auth token according to the provided configuration.

    This helper intentionally focuses on **claims semantics**, not on signature
    verification. In many deployments, the Triton Client Manager will sit
    behind an existing IdP or API gateway that already validates and signs
    tokens. In those cases, this function is used to enforce local policies
    (for example: token must include certain claims; `exp` not expired; `aud`
    and `iss` match expected values).

    Args:
        token: Raw token string from the `auth` payload.
        config: Optional configuration dictionary, typically taken from
            `websocket.yaml` under the `auth` key. Supported keys:
                - ``mode``: "simple" or "strict" (default: "simple").
                - ``require_token``: bool, if True a non‑empty token is required.
                - ``required_claims``: list of claim names that must be present.
                - ``issuer``: expected ``iss`` value (if provided).
                - ``audience``: expected ``aud`` value (if provided).
                - ``leeway_seconds``: allowed clock skew for ``exp`` (default: 60).

    Returns:
        (is_valid, error_message). When ``is_valid`` is True, ``error_message``
        is the empty string.
    """
    cfg = config or {}
    mode = cfg.get("mode", "simple")
    require_token = bool(cfg.get("require_token", False))

    # In simple mode we only enforce "require_token" if explicitly requested.
    if mode != "strict":
        if require_token and not token:
            return False, "Missing token in auth payload"
        return True, ""

    # Strict mode – enforce presence of a token.
    if not token:
        return False, "Missing token in auth payload"

    jwks_url = cfg.get("jwks_url")
    public_key_pem = cfg.get("public_key_pem")
    algorithms = cfg.get("algorithms") or ["RS256", "ES256", "HS256"]
    audience = cfg.get("audience")
    expected_iss = cfg.get("issuer")
    leeway = int(cfg.get("leeway_seconds", 60))
    required_claims = cfg.get("required_claims") or []

    def _validate_required_claims(claims: Dict[str, Any]) -> Tuple[bool, str]:
        for name in required_claims:
            if name not in claims:
                return False, f"Missing required claim: '{name}'"
        return True, ""

    # Cryptographic validation path when key material is configured.
    if jwks_url or public_key_pem:
        try:
            if jwks_url:
                jwks_client = PyJWKClient(jwks_url)
                signing_key = jwks_client.get_signing_key_from_jwt(token)
                key = signing_key.key
            else:
                key = public_key_pem

            claims = jwt.decode(
                token,
                key=key,
                algorithms=algorithms,
                audience=audience,
                issuer=expected_iss,
                leeway=leeway,
                options={"require": required_claims},
            )
        except ExpiredSignatureError:
            return False, "Token has expired"
        except InvalidIssuerError:
            return False, "Invalid token issuer"
        except InvalidAudienceError:
            return False, "Invalid token audience"
        except Exception as exc:
            return False, f"Invalid token: {exc}"

        ok, err = _validate_required_claims(claims)
        if not ok:
            return ok, err
        return True, ""

    # Fallback: strict mode without key material – preserve previous behaviour
    # (no signature verification, only payload/claims checks).
    # Decode payload without verifying signature.
    try:
        claims = _decode_jwt_payload(token)
    except Exception:
        return False, "Invalid token format"

    # Enforce required claims.
    ok, err = _validate_required_claims(claims)
    if not ok:
        return ok, err

    # exp: unix timestamp; allow small clock skew.
    if "exp" in claims:
        try:
            exp = float(claims["exp"])
        except (TypeError, ValueError):
            return False, "Invalid 'exp' claim"
        now = time.time()
        if now > exp + leeway:
            return False, "Token has expired"

    # iss: expected issuer if configured.
    if expected_iss is not None:
        iss = claims.get("iss")
        if iss != expected_iss:
            return False, "Invalid token issuer"

    # aud: may be a string or list; compare if configured.
    expected_aud = cfg.get("audience")
    if expected_aud is not None:
        aud = claims.get("aud")
        if isinstance(aud, str):
            audiences = [aud]
        elif isinstance(aud, (list, tuple)):
            audiences = list(aud)
        else:
            return False, "Invalid 'aud' claim"
        if expected_aud not in audiences:
            return False, "Invalid token audience"

    return True, ""


__all__ = ["validate_token"]
