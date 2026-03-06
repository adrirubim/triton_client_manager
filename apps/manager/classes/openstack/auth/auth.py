import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import requests

from .catalog import Catalog

logger = logging.getLogger(__name__)


class OpenstackAuth:
    """OpenStack authentication using application credentials with proactive token refresh"""

    def __init__(
        self,
        auth_url: str = None,
        application_credential_id: str = None,
        application_credential_secret: str = None,
        region_name: str = "RegionOne",
        verify_ssl: Union[bool, str] = True,
        token_refresh_buffer_minutes: int = 10,
        **kwargs,
    ):
        """
        Initialize OpenStack authentication.

        Args:
            auth_url: Keystone URL - can be base (https://c.c41.ch:5000) or full endpoint
            application_credential_id: Application credential ID
            application_credential_secret: Application credential secret
            region_name: OpenStack region (default: RegionOne)
            verify_ssl: SSL verification - bool or path to certificate file
            token_refresh_buffer_minutes: Minutes before expiration to refresh (default: 10)
        """
        if (
            not auth_url
            or not application_credential_id
            or not application_credential_secret
        ):
            raise ValueError(
                "auth_url, application_credential_id, and application_credential_secret are required"
            )

        # Normalize auth URL - handle both base URL and full endpoint
        auth_url = auth_url.rstrip("/")
        if "/v3/auth/tokens" in auth_url:
            self.auth_url = auth_url  # Full endpoint provided
        else:
            self.auth_url = f"{auth_url}/v3/auth/tokens"  # Base URL, append endpoint

        self.secret = application_credential_secret
        self.region = region_name
        self.verify_ssl = verify_ssl
        if verify_ssl is False:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.credential_id = application_credential_id
        self.token_refresh_buffer = timedelta(minutes=token_refresh_buffer_minutes)

        # Token management
        self.token: Optional[str] = None
        self.project_id: Optional[str] = None
        self.token_issued_at: Optional[datetime] = None
        self.token_expires_at: Optional[datetime] = None
        self.token_refresh_at: Optional[datetime] = None

        # Service catalog
        self.catalog: Optional[Catalog] = None

        # Thread safety
        self.lock = threading.Lock()

    # --------------- AUTHENTICATION ---------------
    def authenticate(self) -> bool:
        """Authenticate with OpenStack and retrieve token"""
        with self.lock:
            try:
                auth_payload = {
                    "auth": {
                        "identity": {
                            "methods": ["application_credential"],
                            "application_credential": {
                                "id": self.credential_id,
                                "secret": self.secret,
                            },
                        }
                    }
                }

                # Determine SSL verification parameter
                verify_param = self._get_verify_param()

                # Make authentication request
                response = requests.post(
                    url=self.auth_url,
                    json=auth_payload,
                    headers={"Accept": "application/json"},
                    verify=verify_param,
                    timeout=30,
                )
                response.raise_for_status()

                # Extract token from header
                self.token = response.headers.get("X-Subject-Token")
                if not self.token:
                    logger.error("X-Subject-Token not found in response")
                    return False

                # Parse response
                token_data = response.json().get("token", {})
                self._parse_token_data(token_data)

                logger.info(
                    "Authenticated | Expires: %s | Refresh: %s",
                    self.token_expires_at,
                    self.token_refresh_at,
                )
                return True

            except requests.exceptions.RequestException as e:
                logger.error("Authentication failed: %s", e)
                return False
            except Exception as e:
                logger.exception("Unexpected error: %s", e)
                return False

    # --------------- TOKEN MANAGEMENT ---------------
    def get_token(self) -> Optional[str]:
        """
        Get current authentication token.
        Token validity is maintained proactively by check_and_refresh_token()
        """
        return self.token

    def is_token_valid(self) -> bool:
        """Check if token is still valid (before proactive refresh time)"""
        if not self.token or not self.token_refresh_at:
            return False
        return datetime.now(timezone.utc) < self.token_refresh_at

    def check_and_refresh_token(self) -> bool:
        """
        Check if token needs refresh and refresh if necessary.
        Call periodically (e.g., every 10 seconds) to maintain token validity.
        """
        if not self.is_token_valid():
            logger.info("Token refresh triggered")
            return self.authenticate()
        return True

    # --------------- UTILS ---------------
    def _get_verify_param(self) -> Union[bool, str]:
        """Get SSL verification parameter for requests"""
        if isinstance(self.verify_ssl, str):
            if not os.path.exists(self.verify_ssl):
                logger.warning("Certificate file not found: %s", self.verify_ssl)
                return False
        return self.verify_ssl

    def _parse_token_data(self, token_data: dict):
        """Parse token data from authentication response"""
        # Extract expiration time
        expires_at_str = token_data.get("expires_at")
        if expires_at_str:
            self.token_expires_at = self._parse_datetime(expires_at_str)
            self.token_refresh_at = self.token_expires_at - self.token_refresh_buffer

        # Extract issued time
        issued_at_str = token_data.get("issued_at")
        if issued_at_str:
            self.token_issued_at = self._parse_datetime(issued_at_str)

        # Extract project ID
        project = token_data.get("project", {})
        self.project_id = project.get("id")

        # Parse service catalog
        catalog_data = token_data.get("catalog", [])
        self.catalog = Catalog(catalog_data, region=self.region)

    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse OpenStack datetime string to datetime object"""
        try:
            # Handle 'Z' suffix for UTC timezone
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"

            dt = datetime.fromisoformat(dt_str)

            # Ensure timezone is set
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt
        except Exception as e:
            logger.warning("Error parsing datetime '%s': %s", dt_str, e)
            return None

    def get_project_id(self) -> Optional[str]:
        """Get the current project ID"""
        return self.project_id

    def __repr__(self) -> str:
        status = "authenticated" if self.is_token_valid() else "not authenticated"
        return f"OpenstackAuth(region={self.region}, status={status})"
