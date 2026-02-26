"""
ShipStation V1 API client.

Auth: Basic HTTP auth (Base64 of api_key:api_secret).
Base URL: https://ssapi.shipstation.com
Docs: https://www.shipstation.com/docs/api/
"""

import base64
import json
import time
import logging
import requests
from typing import Optional

logger = logging.getLogger("qpss")


class ShipStationError(Exception):
    """Raised on non-retryable ShipStation API errors."""
    pass


class ShipStationTransientError(Exception):
    """Raised on retryable errors (network, 429, 5xx)."""
    pass


class ShipStationClient:
    """Wrapper for ShipStation V1 REST API."""

    def __init__(self, api_key: str, api_secret: str, base_url: str,
                 retry_attempts: int = 3, retry_delay: int = 5):
        self.base_url = base_url.rstrip("/")
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.session = requests.Session()

        # V1 Basic auth: Base64 encode "api_key:api_secret"
        credentials = base64.b64encode(
            f"{api_key}:{api_secret}".encode()
        ).decode()
        self.session.headers.update({
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        })

    def create_or_update_order(self, order_data: dict) -> dict:
        """Create or update an order in ShipStation.

        V1's POST /orders/createorder will CREATE a new order if the orderKey
        doesn't exist, or UPDATE if it does. This is the built-in upsert.

        Returns the API response dict on success.
        Raises ShipStationError on permanent failure.
        Raises ShipStationTransientError on retryable failure.
        """
        url = f"{self.base_url}/orders/createorder"
        return self._post_with_retry(url, order_data)

    def find_order_by_number(self, order_number: str) -> Optional[dict]:
        """Check if an order with the given orderNumber exists.

        V1's GET /orders?orderNumber= does a "starts with" match.
        We check for an exact match in the results.

        Returns the order dict if found, None if not found.
        """
        url = f"{self.base_url}/orders"
        params = {"orderNumber": order_number, "pageSize": 10}

        try:
            response = self._get_with_retry(url, params)
            orders = response.get("orders", [])
            for order in orders:
                if order.get("orderNumber") == order_number:
                    return order
            return None
        except (ShipStationError, ShipStationTransientError):
            logger.warning(f"Could not check for existing order {order_number}, "
                           "proceeding with create")
            return None

    def list_shipments(self, store_id: int = None,
                        create_date_start: str = None,
                        create_date_end: str = None,
                        page: int = 1,
                        page_size: int = 100) -> dict:
        """List shipments from ShipStation.

        Args:
            store_id: Filter by store (integer ID).
            create_date_start: ISO date string (YYYY-MM-DD). Filters by when the
                shipment record was created (label generated), not the order date.
            create_date_end: ISO date string (YYYY-MM-DD) for end of range.
            page: Page number (1-based).
            page_size: Results per page (max 500).

        Returns dict with keys: shipments (list), total, page, pages.
        """
        url = f"{self.base_url}/shipments"
        params = {"page": page, "pageSize": page_size}
        if store_id is not None:
            params["storeId"] = store_id
        if create_date_start:
            params["createDateStart"] = create_date_start
        if create_date_end:
            params["createDateEnd"] = create_date_end
        return self._get_with_retry(url, params)

    def get_order(self, order_id: int) -> dict:
        """Get a single order by its orderId.

        Returns the order dict including advancedOptions, internalNotes, etc.
        """
        url = f"{self.base_url}/orders/{order_id}"
        return self._get_with_retry(url, {})

    def list_stores(self) -> list[dict]:
        """List all stores in the ShipStation account.

        Returns a list of store dicts with storeId, storeName, etc.
        Useful for finding the integer storeId needed for order creation.
        """
        url = f"{self.base_url}/stores"
        return self._get_with_retry(url, {})

    def _post_with_retry(self, url: str, body: dict) -> dict:
        """POST with retry logic for transient failures."""
        return self._request_with_retry("POST", url, json_body=body)

    def _get_with_retry(self, url: str, params: dict) -> dict:
        """GET with retry logic for transient failures."""
        return self._request_with_retry("GET", url, params=params)

    def _request_with_retry(self, method: str, url: str,
                            json_body: dict = None,
                            params: dict = None) -> dict:
        """Execute an HTTP request with retry logic.

        Retries on: network errors, HTTP 429, HTTP 5xx.
        Does NOT retry on: HTTP 4xx (except 429).
        """
        last_error = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                if method == "POST":
                    resp = self.session.post(url, json=json_body, timeout=30)
                else:
                    resp = self.session.get(url, params=params, timeout=30)

                # Rate limited (40 requests/minute)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", self.retry_delay))
                    logger.warning(f"Rate limited (429). Waiting {retry_after}s "
                                   f"(attempt {attempt}/{self.retry_attempts})")
                    time.sleep(retry_after)
                    last_error = ShipStationTransientError(
                        f"Rate limited after {self.retry_attempts} attempts")
                    continue

                # Server error (retryable)
                if resp.status_code >= 500:
                    logger.warning(f"Server error {resp.status_code}. "
                                   f"Retrying in {self.retry_delay}s "
                                   f"(attempt {attempt}/{self.retry_attempts})")
                    time.sleep(self.retry_delay)
                    last_error = ShipStationTransientError(
                        f"Server error {resp.status_code}: {resp.text[:200]}")
                    continue

                # Client error (permanent, don't retry)
                if resp.status_code >= 400:
                    error_detail = resp.text[:500]
                    logger.error(f"API error {resp.status_code}: {error_detail}")
                    raise ShipStationError(
                        f"HTTP {resp.status_code}: {error_detail}")

                # Success
                return resp.json()

            except requests.RequestException as e:
                logger.warning(f"Network error: {e}. "
                               f"Retrying in {self.retry_delay}s "
                               f"(attempt {attempt}/{self.retry_attempts})")
                time.sleep(self.retry_delay)
                last_error = ShipStationTransientError(f"Network error: {e}")

        # All retries exhausted
        raise last_error
