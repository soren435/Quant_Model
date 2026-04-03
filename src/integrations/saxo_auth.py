"""
Saxo Bank OAuth2 token manager.

Implements the Authorization Code flow used by Saxo OpenAPI.
Handles token exchange, refresh, expiry detection, and persistence to .env.

OAuth2 endpoints:
  Sim:  https://sim.logonvalidation.net/authorize  |  /token
  Live: https://live.logonvalidation.net/authorize |  /token

Required environment variables:
  SAXO_CLIENT_ID      — app client ID from developer.saxobank.com
  SAXO_CLIENT_SECRET  — app client secret
  SAXO_REDIRECT_URI   — must match what is registered in the Saxo app config
                        (e.g. http://localhost:8501/)
  SAXO_ENV            — "sim" | "live"

Optional (written here after a successful auth):
  SAXO_ACCESS_TOKEN   — current bearer token
  SAXO_REFRESH_TOKEN  — refresh token (valid for 1 hour on sim, longer on live)
  SAXO_TOKEN_EXPIRY   — Unix timestamp when the access token expires
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv, set_key, dotenv_values
    _DOTENV_OK = True
except ImportError:
    _DOTENV_OK = False

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False


# ── Constants ──────────────────────────────────────────────────────────────────

_AUTH_URLS = {
    "sim":  "https://sim.logonvalidation.net/authorize",
    "live": "https://live.logonvalidation.net/authorize",
}
_TOKEN_URLS = {
    "sim":  "https://sim.logonvalidation.net/token",
    "live": "https://live.logonvalidation.net/token",
}

# Refresh a token when less than this many seconds remain
_REFRESH_BUFFER_SECS = 120

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _decode_jwt_payload(token: str) -> dict:
    """
    Decode the payload section of a JWT without verifying the signature.
    Used only to read the 'exp' claim.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def _expiry_from_token(access_token: str, expires_in: int | None = None) -> int:
    """
    Return Unix timestamp when the token expires.
    Prefers the JWT 'exp' claim; falls back to now + expires_in.
    """
    payload = _decode_jwt_payload(access_token)
    if "exp" in payload:
        try:
            return int(payload["exp"])
        except (TypeError, ValueError):
            pass
    if expires_in:
        return int(time.time()) + expires_in
    return int(time.time()) + 1200  # default: 20 minutes


def _write_env_key(key: str, value: str) -> None:
    """Persist a single key=value pair to the .env file."""
    if not _DOTENV_OK or not _ENV_FILE.exists():
        return
    set_key(str(_ENV_FILE), key, value, quote_mode="never")


# ── Token dataclass ────────────────────────────────────────────────────────────

@dataclass
class OAuthTokens:
    access_token:  str
    refresh_token: str
    expiry:        int          # Unix timestamp
    token_type:    str = "Bearer"

    @property
    def seconds_remaining(self) -> int:
        return max(0, self.expiry - int(time.time()))

    @property
    def is_expired(self) -> bool:
        return self.seconds_remaining < _REFRESH_BUFFER_SECS

    @property
    def expires_at_str(self) -> str:
        dt = datetime.fromtimestamp(self.expiry, tz=timezone.utc).astimezone()
        return dt.strftime("%H:%M:%S")


# ── Main auth manager ──────────────────────────────────────────────────────────

class SaxoAuth:
    """
    OAuth2 authorization-code token manager for Saxo OpenAPI.

    Usage (Streamlit flow):
        auth = SaxoAuth()

        # 1. Send user to login
        url, state = auth.get_authorization_url()
        # → redirect user to `url`

        # 2. Handle redirect callback (read from st.query_params)
        tokens = auth.exchange_code(code, state)

        # 3. On every API call — get a fresh token (auto-refreshes if needed)
        token = auth.get_valid_token()   # raises if no tokens loaded

        # 4. Check status
        auth.status()                    # dict for UI display
    """

    def __init__(self) -> None:
        if _DOTENV_OK and _ENV_FILE.exists():
            load_dotenv(str(_ENV_FILE), override=True)

        self._env         = os.getenv("SAXO_ENV", "sim").strip().lower()
        self._client_id   = os.getenv("SAXO_CLIENT_ID", "").strip()
        self._client_secret = os.getenv("SAXO_CLIENT_SECRET", "").strip()
        self._redirect_uri  = os.getenv("SAXO_REDIRECT_URI", "http://localhost:8501/").strip()

        # Load persisted tokens (may be None if not yet authenticated)
        self._tokens: OAuthTokens | None = self._load_persisted_tokens()

        # State nonce for CSRF protection (stored in session, validated on callback)
        self._pending_state: str | None = None

    # ── App config status ──────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        """True if client_id and client_secret are set (app is registered)."""
        return bool(self._client_id and self._client_secret)

    def has_tokens(self) -> bool:
        """True if we have a token pair (may be expired)."""
        return self._tokens is not None

    def is_authenticated(self) -> bool:
        """True if we have a valid, non-expired access token."""
        return self._tokens is not None and not self._tokens.is_expired

    def status(self) -> dict:
        """
        Return a UI-friendly status dict.
        Keys: configured, has_tokens, authenticated, seconds_remaining,
              expires_at, env, redirect_uri, client_id_set
        """
        t = self._tokens
        return {
            "configured":        self.is_configured(),
            "has_tokens":        self.has_tokens(),
            "authenticated":     self.is_authenticated(),
            "seconds_remaining": t.seconds_remaining if t else 0,
            "expires_at":        t.expires_at_str if t else "—",
            "env":               self._env,
            "redirect_uri":      self._redirect_uri,
            "client_id_set":     bool(self._client_id),
        }

    # ── Step 1: Authorization URL ──────────────────────────────────────────────

    def get_authorization_url(self) -> tuple[str, str]:
        """
        Build the Saxo OAuth2 authorization URL and a random state nonce.

        Returns:
            (url, state) — redirect the user to `url`; store `state` for validation.
        """
        state = secrets.token_urlsafe(24)
        self._pending_state = state

        params = {
            "response_type": "code",
            "client_id":     self._client_id,
            "redirect_uri":  self._redirect_uri,
            "state":         state,
        }
        base = _AUTH_URLS.get(self._env, _AUTH_URLS["sim"])
        url = f"{base}?{urllib.parse.urlencode(params)}"
        return url, state

    # ── Step 2: Code exchange ──────────────────────────────────────────────────

    def exchange_code(self, code: str, state: str | None = None) -> OAuthTokens:
        """
        Exchange an authorization code for access + refresh tokens.
        Persists the tokens to .env immediately.

        Args:
            code:  The code received in the OAuth callback query parameter.
            state: The state value from the callback (validated if pending_state is set).

        Returns:
            OAuthTokens dataclass.

        Raises:
            ValueError: on state mismatch or invalid response.
            RuntimeError: if requests is not available.
        """
        if self._pending_state and state and state != self._pending_state:
            raise ValueError("OAuth state mismatch — possible CSRF. Restart the auth flow.")

        if not _REQUESTS_OK:
            raise RuntimeError("`requests` is required for OAuth2 token exchange.")

        token_url = _TOKEN_URLS.get(self._env, _TOKEN_URLS["sim"])
        resp = _requests.post(
            token_url,
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  self._redirect_uri,
                "client_id":     self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            raise ValueError(f"Unexpected token response: {data}")

        tokens = OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expiry=_expiry_from_token(data["access_token"], data.get("expires_in")),
            token_type=data.get("token_type", "Bearer"),
        )
        self._tokens = tokens
        self._pending_state = None
        self._persist_tokens(tokens)
        return tokens

    # ── Token refresh ──────────────────────────────────────────────────────────

    def refresh(self) -> OAuthTokens:
        """
        Use the refresh token to obtain a new access token.
        Persists the new tokens to .env.

        Raises:
            RuntimeError: if no refresh token is available or requests missing.
        """
        if not _REQUESTS_OK:
            raise RuntimeError("`requests` is required for token refresh.")
        if not self._tokens or not self._tokens.refresh_token:
            raise RuntimeError("No refresh token available. Re-authenticate via the Connect tab.")

        token_url = _TOKEN_URLS.get(self._env, _TOKEN_URLS["sim"])
        resp = _requests.post(
            token_url,
            data={
                "grant_type":    "refresh_token",
                "refresh_token": self._tokens.refresh_token,
                "client_id":     self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            raise ValueError(f"Unexpected refresh response: {data}")

        tokens = OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", self._tokens.refresh_token),
            expiry=_expiry_from_token(data["access_token"], data.get("expires_in")),
            token_type=data.get("token_type", "Bearer"),
        )
        self._tokens = tokens
        self._persist_tokens(tokens)
        return tokens

    # ── Get a valid access token (auto-refresh) ────────────────────────────────

    def get_valid_token(self) -> str:
        """
        Return a valid access token, auto-refreshing if it is close to expiry.

        Raises:
            RuntimeError: if no tokens are loaded or refresh fails.
        """
        if not self._tokens:
            raise RuntimeError("Not authenticated. Complete the OAuth2 flow in the Connect tab.")

        if self._tokens.is_expired:
            self.refresh()

        return self._tokens.access_token

    # ── Persistence ────────────────────────────────────────────────────────────

    def _persist_tokens(self, tokens: OAuthTokens) -> None:
        """Write tokens to the .env file so they survive app restarts."""
        _write_env_key("SAXO_ACCESS_TOKEN",  tokens.access_token)
        _write_env_key("SAXO_REFRESH_TOKEN", tokens.refresh_token)
        _write_env_key("SAXO_TOKEN_EXPIRY",  str(tokens.expiry))
        # Keep environment up to date in this process too
        os.environ["SAXO_ACCESS_TOKEN"]  = tokens.access_token
        os.environ["SAXO_REFRESH_TOKEN"] = tokens.refresh_token
        os.environ["SAXO_TOKEN_EXPIRY"]  = str(tokens.expiry)

    def _load_persisted_tokens(self) -> OAuthTokens | None:
        """Load tokens from environment variables (populated from .env by load_dotenv)."""
        access  = os.getenv("SAXO_ACCESS_TOKEN", "").strip()
        refresh = os.getenv("SAXO_REFRESH_TOKEN", "").strip()
        expiry_str = os.getenv("SAXO_TOKEN_EXPIRY", "").strip()

        if not access:
            return None

        if expiry_str:
            try:
                expiry = int(expiry_str)
            except ValueError:
                expiry = _expiry_from_token(access)
        else:
            expiry = _expiry_from_token(access)

        return OAuthTokens(
            access_token=access,
            refresh_token=refresh,
            expiry=expiry,
        )

    # ── Manual token injection (backward compat) ───────────────────────────────

    def set_manual_token(self, access_token: str) -> None:
        """
        Accept a manually pasted token (e.g. from Saxo Developer Portal).
        Derives expiry from JWT payload; sets refresh_token to empty string.
        """
        expiry = _expiry_from_token(access_token)
        self._tokens = OAuthTokens(
            access_token=access_token,
            refresh_token="",
            expiry=expiry,
        )
        self._persist_tokens(self._tokens)
