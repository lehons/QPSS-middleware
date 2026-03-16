"""
UPS API client for retrieving per-package tracking numbers.

Handles OAuth 2.0 token management and calls the UPS Tracking API
to get individual tracking numbers for multi-package shipments.
"""

import logging
import uuid
from datetime import datetime, timedelta

import requests

logger = logging.getLogger("qpss")

TOKEN_URL = "https://onlinetools.ups.com/security/v1/oauth/token"
TRACKING_URL = "https://onlinetools.ups.com/api/track/v1/shipment/details"


class UPSClient:
    """UPS API client with OAuth 2.0 token caching."""

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires: datetime | None = None

    def _get_token(self) -> str:
        """Get a valid OAuth token, refreshing if expired."""
        if self._token and self._token_expires and datetime.now() < self._token_expires:
            return self._token

        logger.debug("UPS | Requesting OAuth token")
        try:
            resp = requests.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            # UPS tokens typically last 4 hours; use expires_in if provided,
            # otherwise default to 3.5 hours to be safe.
            expires_in = int(data.get("expires_in", 12600))
            self._token_expires = datetime.now() + timedelta(seconds=expires_in - 60)
            logger.debug("UPS | Token acquired (expires in %ds)", expires_in)
            return self._token
        except Exception as e:
            logger.error("UPS | OAuth token request failed: %s", e)
            raise

    def get_child_tracking(self, master_tracking: str) -> list[str]:
        """Look up per-package tracking numbers for a multi-package shipment.

        Args:
            master_tracking: The master tracking number from ShipStation.

        Returns:
            List of individual package tracking numbers. Empty list on any error.
        """
        try:
            token = self._get_token()
        except Exception:
            return []

        try:
            resp = requests.get(
                f"{TRACKING_URL}/{master_tracking}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "transId": str(uuid.uuid4()),
                    "transactionSrc": "QPSS-middleware",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            shipment = data.get("trackResponse", {}).get("shipment", [{}])[0]

            # Check for warnings (e.g., "Tracking Information Not Found")
            warnings = shipment.get("warnings", [])
            if warnings:
                for w in warnings:
                    logger.warning("UPS | Tracking warning for %s: %s",
                                   master_tracking, w.get("message", ""))
                return []

            packages = shipment.get("package", [])
            if not packages:
                logger.warning("UPS | No packages in tracking response for %s",
                               master_tracking)
                return []

            tracking_numbers = [
                pkg.get("trackingNumber", "")
                for pkg in packages
                if pkg.get("trackingNumber")
            ]

            logger.info("UPS | %s: got %d tracking number(s)",
                        master_tracking, len(tracking_numbers))
            return tracking_numbers

        except Exception as e:
            logger.error("UPS | Tracking lookup failed for %s: %s",
                         master_tracking, e)
            return []
