from __future__ import annotations

from classes.job.management.management import JobManagement
from utils.config_env import _bool_env, overlay_minio_payload, overlay_openstack_config


def test_bool_env_parses_truthy_and_falsy_values():
    for v in ("1", "true", "TRUE", "Yes", "on", "On"):
        assert _bool_env(v) is True
    for v in ("0", "false", "no", "off", ""):
        assert _bool_env(v) is False


def test_overlay_openstack_config_overrides_and_preserves_base(monkeypatch):
    base = {
        "auth_url": "http://original",
        "application_credential_id": "orig-id",
        "application_credential_secret": "orig-secret",
        "region_name": "orig-region",
        "verify_ssl": True,
    }

    env = {
        "OPENSTACK_AUTH_URL": "http://env-auth",
        "OPENSTACK_APPLICATION_CREDENTIAL_ID": "env-id",
        "OPENSTACK_APPLICATION_CREDENTIAL_SECRET": "env-secret",
        "OPENSTACK_REGION_NAME": "env-region",
        "OPENSTACK_VERIFY_SSL": "false",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    out = overlay_openstack_config(base)
    # Base dict must not be mutated
    assert base["auth_url"] == "http://original"
    # Output must reflect env overrides
    assert out["auth_url"] == "http://env-auth"
    assert out["application_credential_id"] == "env-id"
    assert out["application_credential_secret"] == "env-secret"
    assert out["region_name"] == "env-region"
    assert out["verify_ssl"] is False


def test_overlay_minio_payload_fills_missing_fields_without_overwriting(monkeypatch):
    monkeypatch.setenv("MINIO_ACCESS_KEY", "AK")
    monkeypatch.setenv("MINIO_SECRET_KEY", "SK")
    monkeypatch.setenv("MINIO_REGION", "eu-west-1")

    # Empty payload -> filled from env
    out = overlay_minio_payload({})
    assert out["access_key"] == "AK"
    assert out["secret_key"] == "SK"
    assert out["region"] == "eu-west-1"

    # Explicit payload values must not be overwritten
    out2 = overlay_minio_payload({"access_key": "X", "region": "us-east-1"})
    assert out2["access_key"] == "X"
    assert out2["secret_key"] == "SK"
    assert out2["region"] == "us-east-1"


def test_job_management_wraps_unknown_action_and_selected_errors():
    # Set up a minimal JobManagement with no real dependencies.
    jm = JobManagement(
        docker=None,
        triton=None,
        openstack=None,
        websocket=lambda _uuid, _payload: None,
        management_actions_available=["creation", "deletion"],
    )

    # Unknown action -> JobActionNotFound path
    msg = {"uuid": "u1", "type": "management", "payload": {"action": "does_not_exist"}}
    # websocket is a lambda that does nothing; we just confirm it doesn't raise.
    jm.handle_management(msg)

    # Known action but with malformed payloads to trigger specific exceptions.
    # deletion without required fields triggers JobDeletionMissingField.
    bad_deletion = {
        "uuid": "u2",
        "type": "management",
        "payload": {"action": "deletion"},
    }
    jm.handle_management(bad_deletion)
