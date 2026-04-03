"""
Saxo OpenAPI — authenticated HTTP client.

Wraps requests with a Bearer token and the configured OpenAPI base URL.
Each method returns a plain dict (the parsed JSON response body).

Usage:
    client = SaxoApiClient(token, config.openapi_base)
    user   = client.get_user_info()
    accs   = client.get_accounts()
    bal    = client.get_balance()

Error handling:
    All methods raise requests.HTTPError on non-2xx responses.
    The caller (UI layer) is responsible for catching and displaying errors.

TODO (future enhancement):
    - Add token expiry check before each call and trigger re-auth if expired.
    - Add POST/ORDER methods when trading is implemented.
"""
from __future__ import annotations

import requests

from src.integrations.saxo.auth import TokenData


class SaxoApiClient:
    """
    Minimal authenticated client for Saxo OpenAPI (SIM or Live).

    Args:
        token:    A valid TokenData obtained via the PKCE flow.
        base_url: OpenAPI base URL (e.g. https://gateway.saxobank.com/sim/openapi).
    """

    def __init__(self, token: TokenData, base_url: str) -> None:
        self._token    = token
        self._base_url = base_url.rstrip("/")

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._token.bearer(),
            "Content-Type":  "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Authenticated GET. Raises requests.HTTPError on failure."""
        url  = f"{self._base_url}/{path.lstrip('/')}"
        resp = requests.get(url, headers=self._headers(), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── Portfolio service endpoints ───────────────────────────────────────────

    def get_user_info(self) -> dict:
        """
        GET /port/v1/users/me
        Returns basic info about the authenticated user (name, client key, etc.)
        """
        return self._get("/port/v1/users/me")

    def get_accounts(self) -> list[dict]:
        """
        GET /port/v1/accounts/me
        Returns a list of accounts belonging to the authenticated user.
        """
        result = self._get("/port/v1/accounts/me")
        return result.get("Data", [result]) if isinstance(result, dict) else result

    def get_balance(self, account_key: str | None = None) -> dict:
        """
        GET /port/v1/balances/me
        Returns the cash balance and margin details for the default account.

        Args:
            account_key: Optional account key to scope the request.
        """
        params = {"AccountKey": account_key} if account_key else None
        return self._get("/port/v1/balances/me", params=params)

    def get_positions(self, account_key: str | None = None) -> list[dict]:
        """
        GET /port/v1/netpositions/me
        Returns open net positions. Returns empty list if none.
        """
        params = {"AccountKey": account_key} if account_key else None
        result = self._get("/port/v1/netpositions/me", params=params)
        return result.get("Data", []) if isinstance(result, dict) else []
