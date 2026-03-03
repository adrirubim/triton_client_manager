"""
Overlay environment variables onto config dicts.
Use for secrets and runtime overrides without editing YAML.

Env vars (OpenStack):
  OPENSTACK_AUTH_URL
  OPENSTACK_APPLICATION_CREDENTIAL_ID
  OPENSTACK_APPLICATION_CREDENTIAL_SECRET
  OPENSTACK_REGION_NAME
  OPENSTACK_VERIFY_SSL (true|false)
"""

import os
from typing import Any


def _bool_env(val: str) -> bool:
    return str(val).lower() in ("1", "true", "yes", "on")


def overlay_openstack_config(config: dict[str, Any]) -> dict[str, Any]:
    """Merge OPENSTACK_* env vars into openstack config."""
    out = dict(config)
    if url := os.environ.get("OPENSTACK_AUTH_URL"):
        out["auth_url"] = url
    if cid := os.environ.get("OPENSTACK_APPLICATION_CREDENTIAL_ID"):
        out["application_credential_id"] = cid
    if secret := os.environ.get("OPENSTACK_APPLICATION_CREDENTIAL_SECRET"):
        out["application_credential_secret"] = secret
    if region := os.environ.get("OPENSTACK_REGION_NAME"):
        out["region_name"] = region
    if v := os.environ.get("OPENSTACK_VERIFY_SSL"):
        out["verify_ssl"] = _bool_env(v)
    return out
