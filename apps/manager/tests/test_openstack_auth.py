from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from classes.openstack.auth.auth import OpenstackAuth
from classes.openstack.auth.catalog import Catalog


def _make_token_payload():
    """Helper to build a minimal valid token payload."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    return {
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "project": {"id": "project-123"},
        "catalog": [
            {
                "id": "svc-id",
                "type": "compute",
                "name": "nova",
                "endpoints": [
                    {
                        "region": "RegionOne",
                        "interface": "public",
                        "url": "https://compute.example.com",
                    }
                ],
            }
        ],
    }


class _FakeResponse:
    """Minimal fake requests.Response for auth tests."""

    def __init__(self, status_code=200, headers=None, json_body=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_body = json_body or {}

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json_body


@patch("classes.openstack.auth.auth.requests.post")
def test_authenticate_success_and_catalog_parsing(mock_post):
    """OpenstackAuth.authenticate should set token, dates, project_id and catalog."""
    token_payload = _make_token_payload()
    mock_post.return_value = _FakeResponse(
        status_code=200,
        headers={"X-Subject-Token": "token-abc"},
        json_body={"token": token_payload},
    )

    auth = OpenstackAuth(
        auth_url="https://keystone.example.com",
        application_credential_id="cred-id",
        application_credential_secret="cred-secret",
        region_name="RegionOne",
    )

    ok = auth.authenticate()

    assert ok is True
    assert auth.get_token() == "token-abc"
    assert auth.get_project_id() == "project-123"
    assert isinstance(auth.token_issued_at, datetime)
    assert isinstance(auth.token_expires_at, datetime)
    assert auth.token_expires_at > auth.token_issued_at
    assert isinstance(auth.catalog, Catalog)
    assert auth.catalog.compute is not None
    # repr() should reflect authenticated status
    assert "authenticated" in repr(auth)


@patch("classes.openstack.auth.auth.requests.post")
def test_authenticate_missing_subject_token_returns_false(mock_post):
    """If X-Subject-Token header is missing, authenticate must return False."""
    token_payload = _make_token_payload()
    mock_post.return_value = _FakeResponse(
        status_code=200,
        headers={},  # no X-Subject-Token
        json_body={"token": token_payload},
    )

    auth = OpenstackAuth(
        auth_url="https://keystone.example.com",
        application_credential_id="cred-id",
        application_credential_secret="cred-secret",
    )

    ok = auth.authenticate()

    assert ok is False
    assert auth.get_token() is None


@patch("classes.openstack.auth.auth.requests.post")
def test_authenticate_network_error_returns_false(mock_post):
    """Network-level errors from requests should cause authenticate to return False."""
    mock_post.side_effect = Exception("network error")

    auth = OpenstackAuth(
        auth_url="https://keystone.example.com",
        application_credential_id="cred-id",
        application_credential_secret="cred-secret",
    )

    ok = auth.authenticate()

    assert ok is False
    assert auth.get_token() is None


def test_get_verify_param_with_missing_cert_file(tmp_path, caplog):
    """_get_verify_param should fail-fast when a cert path does not exist."""
    non_existing = tmp_path / "missing.pem"

    auth = OpenstackAuth(
        auth_url="https://keystone.example.com",
        application_credential_id="cred-id",
        application_credential_secret="cred-secret",
        verify_ssl=str(non_existing),
    )

    try:
        auth._get_verify_param()
    except FileNotFoundError as exc:
        assert "Certificate file not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected FileNotFoundError for missing certificate path")


def test_is_token_valid_and_check_and_refresh_token(monkeypatch):
    """Token validity and proactive refresh logic should behave as expected."""
    # Create auth with already-populated timing fields
    auth = OpenstackAuth(
        auth_url="https://keystone.example.com",
        application_credential_id="cred-id",
        application_credential_secret="cred-secret",
    )

    now = datetime.now(timezone.utc)
    auth.token = "token-xyz"
    auth.token_refresh_at = now + timedelta(minutes=5)

    # Before refresh time → token valid
    assert auth.is_token_valid() is True

    # When token is valid, check_and_refresh_token should not call authenticate
    called = {"authenticate": False}

    def fake_authenticate():
        called["authenticate"] = True
        return True

    auth.authenticate = fake_authenticate  # type: ignore[assignment]
    assert auth.check_and_refresh_token() is True
    assert called["authenticate"] is False

    # Make token stale and ensure authenticate is called
    auth.token_refresh_at = now - timedelta(minutes=1)
    assert auth.is_token_valid() is False
    assert auth.check_and_refresh_token() is True
    assert called["authenticate"] is True


def test_parse_datetime_handles_z_suffix_and_invalid():
    """_parse_datetime should support 'Z' suffix and return None on bad input."""
    auth = OpenstackAuth(
        auth_url="https://keystone.example.com",
        application_credential_id="cred-id",
        application_credential_secret="cred-secret",
    )

    dt = auth._parse_datetime("2026-03-03T10:00:00Z")
    assert isinstance(dt, datetime)
    assert dt.tzinfo == timezone.utc

    # Invalid string should log warning and return None
    bad = auth._parse_datetime("not-a-datetime")
    assert bad is None
