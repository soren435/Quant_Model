"""
Saxo OpenAPI — PKCE authorization flow.

Covers:
    1. Building the authorize URL (sent to the user's browser).
    2. Exchanging the authorization code for an access token.
    3. Representing and inspecting token data.

Token refresh is NOT implemented — Saxo SIM tokens are valid for ~20 minutes.
The user must re-authenticate when the token expires.

TODO (future enhancement):
    Implement refresh_token flow once Saxo grants a refresh token in the
    PKCE response. Check the token response for a 'refresh_token' field
    and call POST /token with grant_type=refresh_token.
"""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass

import requests

from src.integrations.saxo.config import SaxoConfig
from src.integrations.saxo.pkce import (
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
)


# ── Token data ─────────────────────────────────────────────────────────────────

@dataclass
class TokenData:
    """
    Holds an access token and its expiry metadata.

    Stored in st.session_state["saxo_token"] after a successful auth flow.
    Intentionally simple — no refresh token logic yet.
    """
    access_token: str
    token_type:   str   # typically "Bearer"
    expires_at:   float  # Unix timestamp

    # ── Expiry helpers ────────────────────────────────────────────────────────

    @property
    def seconds_remaining(self) -> int:
        """Seconds until the token expires (0 if already expired)."""
        return max(0, int(self.expires_at - time.time()))

    @property
    def is_expired(self) -> bool:
        """True if the token has expired or is within 60 seconds of expiry."""
        return time.time() >= (self.expires_at - 60)

    @property
    def expires_at_local(self) -> str:
        """Human-readable local expiry time (HH:MM:SS)."""
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(self.expires_at, tz=timezone.utc).astimezone()
        return dt.strftime("%H:%M:%S")

    def bearer(self) -> str:
        """Return the Authorization header value."""
        return f"{self.token_type} {self.access_token}"


# ── PKCE session state ─────────────────────────────────────────────────────────

@dataclass
class PKCESession:
    """
    Ephemeral data that must survive the browser redirect round-trip.
    Stored in st.session_state["saxo_pkce"] before the authorize redirect.
    Discarded after the code exchange.
    """
    code_verifier: str
    state:         str


# Module-level store so PKCE sessions survive Streamlit session resets
# that happen when the browser redirects away and back during OAuth.
_pkce_store: dict[str, "PKCESession"] = {}


def new_pkce_session() -> PKCESession:
    """Generate a fresh PKCE session and register it in the server-side store."""
    session = PKCESession(
        code_verifier=generate_code_verifier(),
        state=generate_state(),
    )
    _pkce_store[session.state] = session
    return session


def consume_pkce_session(state: str) -> "PKCESession | None":
    """Look up and remove a PKCE session from the server-side store by state."""
    return _pkce_store.pop(state, None)


# ── Step 1: Build authorize URL ────────────────────────────────────────────────

def build_authorize_url(config: SaxoConfig, session: PKCESession) -> str:
    """
    Build the full Saxo PKCE authorize URL.

    The user's browser must be directed to this URL to begin the login flow.
    The code_challenge is derived from the session's code_verifier using S256.

    Args:
        config:  Loaded SaxoConfig (client_id, redirect_uri, auth_base).
        session: A freshly generated PKCESession.

    Returns:
        Full authorize URL string ready for st.link_button() or webbrowser.open().
    """
    params = {
        "response_type":         "code",
        "client_id":             config.client_id,
        "redirect_uri":          config.redirect_uri,
        "code_challenge":        generate_code_challenge(session.code_verifier),
        "code_challenge_method": "S256",
        "state":                 session.state,
    }
    return f"{config.authorize_url}?{urllib.parse.urlencode(params)}"


# ── Step 2: Exchange code for token ───────────────────────────────────────────

def exchange_code(
    config:        SaxoConfig,
    code:          str,
    code_verifier: str,
) -> TokenData:
    """
    Exchange an authorization code for an access token (PKCE, no client secret).

    POST to the Saxo token endpoint with:
        grant_type    = authorization_code
        code          = the code from the callback query parameter
        redirect_uri  = must match the authorize request exactly
        client_id     = app client ID
        code_verifier = the original plain-text verifier (proves identity)

    Args:
        config:        SaxoConfig with token_url, redirect_uri, client_id.
        code:          Authorization code from the callback (?code=...).
        code_verifier: The original code_verifier from the PKCESession.

    Returns:
        TokenData with access_token and expiry.

    Raises:
        requests.HTTPError: on non-2xx response from the token endpoint.
        ValueError:         if the response does not contain an access_token.
    """
    resp = requests.post(
        config.token_url,
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  config.redirect_uri,
            "client_id":     config.client_id,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )

    # Surface a readable error from the Saxo response body if possible
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise requests.HTTPError(
            f"Token exchange failed ({resp.status_code}): {detail}",
            response=resp,
        )

    data = resp.json()

    if "access_token" not in data:
        raise ValueError(f"Unexpected token response — no access_token: {data}")

    expires_in = int(data.get("expires_in", 1200))

    return TokenData(
        access_token=data["access_token"],
        token_type=data.get("token_type", "Bearer"),
        expires_at=time.time() + expires_in,
    )
