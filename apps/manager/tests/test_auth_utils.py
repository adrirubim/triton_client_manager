from __future__ import annotations

import json
import time

import jwt

from utils.auth import _b64url_decode, _decode_jwt_payload, validate_token


def _make_jwt(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}

    def enc(obj: dict) -> bytes:
        return json.dumps(obj, separators=(",", ":")).encode("utf-8")

    import base64

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

    return ".".join(
        [
            b64url(enc(header)),
            b64url(enc(payload)),
            "",  # no signature (we do not verify it in utils.auth)
        ]
    )


def test_b64url_decode_roundtrip():
    original = b"hello-world"
    # "hello-world" without padding, precomputed
    encoded = _b64url_decode("aGVsbG8td29ybGQ")
    assert encoded == original


def test_decode_jwt_payload():
    payload = {"sub": "user-1", "exp": int(time.time()) + 60}
    token = _make_jwt(payload)

    decoded = _decode_jwt_payload(token)
    assert decoded["sub"] == "user-1"


def test_validate_token_simple_mode_allows_missing():
    ok, err = validate_token(None, {"mode": "simple"})
    assert ok is True
    assert err == ""


def test_validate_token_strict_mode_missing_token_fails():
    ok, err = validate_token(None, {"mode": "strict", "require_token": True})
    assert ok is False
    assert "Missing token" in err


def test_validate_token_expired_and_valid():
    now = int(time.time())
    # expired token
    expired_token = _make_jwt({"exp": now - 120})
    ok, err = validate_token(
        expired_token,
        {"mode": "strict", "required_claims": ["exp"], "leeway_seconds": 0},
    )
    assert ok is False
    assert "Token has expired" in err

    # valid token
    valid_token = _make_jwt({"exp": now + 120})
    ok, err = validate_token(
        valid_token,
        {"mode": "strict", "required_claims": ["exp"], "leeway_seconds": 0},
    )
    assert ok is True
    assert err == ""


# HS256 keys must be >= 32 bytes to avoid PyJWT InsecureKeyLengthWarning (RFC 7518).
def test_validate_token_with_symmetric_key_signature():
    now = int(time.time())
    payload = {"sub": "user-1", "exp": now + 120}
    secret = "super-secret-key-for-hs256-test-32-bytes"
    token = jwt.encode(payload, secret, algorithm="HS256")

    ok, err = validate_token(
        token,
        {
            "mode": "strict",
            "require_token": True,
            "public_key_pem": secret,
            "algorithms": ["HS256"],
            "required_claims": ["sub", "exp"],
        },
    )
    assert ok is True
    assert err == ""


def test_validate_token_with_wrong_signature_fails():
    now = int(time.time())
    payload = {"sub": "user-1", "exp": now + 120}
    right_key = "right-key-for-hs256-test-32-bytes!!!!"
    wrong_key = "wrong-key-for-hs256-test-32-bytes!!!!"
    token = jwt.encode(payload, right_key, algorithm="HS256")

    ok, err = validate_token(
        token,
        {
            "mode": "strict",
            "require_token": True,
            "public_key_pem": wrong_key,
            "algorithms": ["HS256"],
            "required_claims": ["sub", "exp"],
        },
    )
    assert ok is False
    assert "Invalid token" in err or "signature" in err
