"""Authentication helpers for WebSocket auth hardening.

Trust model (source of truth):

- **Never trust client-provided identity/roles for authorization in secure environments.**
- In `auth.mode: "strict"`, identity and authorization context must be derived
  **exclusively** from the validated token's JWT claims.
- The WebSocket layer may accept a `payload.client` block for backwards
  compatibility, but it must not grant privileges outside development.

What this module does:

- Validates token presence and claim semantics (`exp`, `aud`, `iss`, required claims).
- When `jwks_url` or `public_key_pem` is configured, performs cryptographic signature verification via PyJWT.
- Enforces safety guardrails:
  - HS* algorithms are allowed only in `TCM_ENV=development`.
  - In non-development environments, `auth.mode: "strict"` requires JWKS/PEM (fail-fast via `SecurityError`).

This module intentionally avoids logging or exposing raw tokens.
"""

import base64
import json
import os
import time
from typing import Any, Dict, Optional, Tuple

import jwt
from jwt import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    PyJWKClient,
)


class SecurityError(RuntimeError):
    """Raised when authentication configuration is insecure for the current environment."""


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
    ok, err, _claims = validate_token_and_get_claims(token, config)
    return ok, err


def validate_token_and_get_claims(
    token: Optional[str],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate an auth token and (when available) return verified JWT claims.

    This function is the **only** supported way to obtain JWT claims used for
    authorization decisions in the manager.

    Modes (from `websocket.yaml` → `auth`):

    - `mode != "strict"` (simple/legacy):
      - Returns `(True, "", {})` when allowed by `require_token`.
      - No claims are returned and callers must treat the client as having
        **no implicit privileges** in non-development environments.

    - `mode == "strict"`:
      - Requires a token and returns claims suitable for deriving:
        `sub`, `tenant_id` and `roles`.
      - If `jwks_url` or `public_key_pem` is configured, the claims are
        cryptographically verified.
      - If no key material is configured:
        - In `TCM_ENV != "development"`: raises `SecurityError` (fail-fast).
        - In `TCM_ENV == "development"`: allows "claims-only" validation by
          decoding the JWT payload without verifying the signature.

    Returns:
        `(is_valid, error_message, claims)` where `claims` is a dict of JWT
        claims (empty when not available).
    """
    cfg = config or {}
    mode = cfg.get("mode", "simple")
    require_token = bool(cfg.get("require_token", False))
    claims: Dict[str, Any] = {}

    # In simple mode we only enforce "require_token" if explicitly requested.
    if mode != "strict":
        if require_token and not token:
            return False, "Missing token in auth payload"
        return True, "", {}

    # Strict mode – enforce presence of a token.
    if not token:
        return False, "Missing token in auth payload", {}

    jwks_url = cfg.get("jwks_url")
    public_key_pem = cfg.get("public_key_pem")
    algorithms_cfg = cfg.get("algorithms") or []
    audience = cfg.get("audience")
    expected_iss = cfg.get("issuer")
    leeway = int(cfg.get("leeway_seconds", 60))
    required_claims = cfg.get("required_claims") or []
    env = os.getenv("TCM_ENV", "development").lower()

    def _default_algorithms() -> list[str]:
        """
        Safe defaults:
        - Prefer asymmetric algorithms by default.
        - HS* must be explicitly configured and is only allowed in development.
        """
        return ["RS256", "ES256"]

    algorithms: list[str] = list(algorithms_cfg) if algorithms_cfg else _default_algorithms()

    # Guardrail: HS* algorithms are only allowed in development and must be explicit.
    uses_hs = any(isinstance(a, str) and a.upper().startswith("HS") for a in algorithms)
    if uses_hs and env != "development":
        return False, "HS* algorithms are not allowed outside development"
    if env == "development" and not algorithms_cfg and uses_hs:
        # Defensive: should not happen because defaults exclude HS*, but keep for clarity.
        return False, "HS* algorithms must be explicitly configured"

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
            return False, "Token has expired", {}
        except InvalidIssuerError:
            return False, "Invalid token issuer", {}
        except InvalidAudienceError:
            return False, "Invalid token audience", {}
        except Exception as exc:
            return False, f"Invalid token: {exc}", {}

        ok, err = _validate_required_claims(claims)
        if not ok:
            return ok, err, {}
        return True, "", dict(claims or {})

    # Strict mode without key material.
    # In non-development environments this is considered insecure and must fail-fast.
    if env != "development":
        raise SecurityError(
            "auth.mode='strict' requires cryptographic verification (JWKS/PEM). "
            f"TCM_ENV='{env}' does not allow 'claims-only' validation."
        )

    # Development fallback: allow claims-only validation to keep local workflows simple.
    # Decode payload without verifying signature.
    try:
        claims = _decode_jwt_payload(token)
    except Exception:
        return False, "Invalid token format", {}

    # Enforce required claims.
    ok, err = _validate_required_claims(claims)
    if not ok:
        return ok, err, {}

    # exp: unix timestamp; allow small clock skew.
    if "exp" in claims:
        try:
            exp = float(claims["exp"])
        except (TypeError, ValueError):
            return False, "Invalid 'exp' claim", {}
        now = time.time()
        if now > exp + leeway:
            return False, "Token has expired", {}

    # iss: expected issuer if configured.
    if expected_iss is not None:
        iss = claims.get("iss")
        if iss != expected_iss:
            return False, "Invalid token issuer", {}

    # aud: may be a string or list; compare if configured.
    expected_aud = cfg.get("audience")
    if expected_aud is not None:
        aud = claims.get("aud")
        if isinstance(aud, str):
            audiences = [aud]
        elif isinstance(aud, (list, tuple)):
            audiences = list(aud)
        else:
            return False, "Invalid 'aud' claim", {}
        if expected_aud not in audiences:
            return False, "Invalid token audience", {}

    return True, "", dict(claims or {})


__all__ = ["SecurityError", "validate_token", "validate_token_and_get_claims"]
