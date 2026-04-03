"""
UI — Saxo Bank Connect tab.

PKCE OAuth2 flow (no client secret, RFC 7636 S256):
  1. User clicks "Connect to Saxo Bank" → PKCE session generated, stored in
     session_state, browser directed to Saxo authorize URL.
  2. Saxo redirects back to http://localhost:8501/?code=XXX&state=YYY.
  3. This page detects the callback, validates state, exchanges code for token.
  4. TokenData stored in st.session_state["saxo_token"].
  5. Authenticated view shows token expiry + live account/balance data.
"""
from __future__ import annotations

import streamlit as st

from src.integrations.saxo.auth import (
    PKCESession,
    TokenData,
    build_authorize_url,
    exchange_code,
    new_pkce_session,
)
from src.integrations.saxo.client import SaxoApiClient
from src.integrations.saxo.config import SaxoConfig, is_configured, load_config


# ── Helpers ────────────────────────────────────────────────────────────────────

def _status_badge(label: str, colour: str) -> None:
    colour_map = {
        "green":  ("#16A34A", "#DCFCE7"),
        "orange": ("#D97706", "#FEF3C7"),
        "red":    ("#DC2626", "#FEE2E2"),
        "grey":   ("#64748B", "#F1F5F9"),
    }
    fg, bg = colour_map.get(colour, ("#64748B", "#F1F5F9"))
    st.markdown(
        f"<span style='background:{bg}; color:{fg}; padding:4px 14px; "
        f"border-radius:6px; font-weight:600; font-size:0.95rem;'>{label}</span>",
        unsafe_allow_html=True,
    )


def _token() -> TokenData | None:
    return st.session_state.get("saxo_token")


def _pkce_session() -> PKCESession | None:
    return st.session_state.get("saxo_pkce")


# ── Main render ────────────────────────────────────────────────────────────────

def render_saxo_connect(lang: str = "en") -> None:
    st.header("🔗 Saxo Bank — Connect")
    st.caption(
        "Connect to your Saxo Bank SIM account using PKCE OAuth2 (no client secret required). "
        "All activity is in simulation mode."
    )

    # ── Step 0: Check env configuration ───────────────────────────────────────
    if not is_configured():
        st.error(
            "**SAXO_CLIENT_ID** is not set.\n\n"
            "1. Register your app at [developer.saxobank.com](https://developer.saxobank.com)\n"
            "2. Set redirect URI to `http://localhost:8501/`\n"
            "3. Add `SAXO_CLIENT_ID=your_id` to your `.env` file and restart the app"
        )
        st.subheader("Required environment variables")
        st.code(
            "SAXO_CLIENT_ID=your_app_client_id\n"
            "# Optional overrides (defaults shown):\n"
            "SAXO_REDIRECT_URI=http://localhost:8501/\n"
            "SAXO_AUTH_BASE=https://sim.logonvalidation.net\n"
            "SAXO_OPENAPI_BASE=https://gateway.saxobank.com/sim/openapi",
            language="bash",
        )
        return

    config: SaxoConfig = load_config()

    # ── Step 1: Handle OAuth2 callback (?code=...&state=...) ──────────────────
    params = st.query_params
    if "code" in params:
        code      = params["code"]
        state_got = params.get("state", "")
        st.query_params.clear()

        pkce = _pkce_session()
        if pkce is None:
            st.error(
                "PKCE session not found in browser session. "
                "The login page may have been opened in a different tab or the "
                "session was reset. Please click **Connect to Saxo Bank** again."
            )
            return

        if state_got != pkce.state:
            st.error(
                f"State mismatch — possible CSRF attempt. "
                f"Expected `{pkce.state[:8]}…`, got `{state_got[:8]}…`. "
                "Please try connecting again."
            )
            del st.session_state["saxo_pkce"]
            return

        with st.spinner("Exchanging authorization code for access token…"):
            try:
                token = exchange_code(config, code, pkce.code_verifier)
                st.session_state["saxo_token"] = token
                del st.session_state["saxo_pkce"]
            except Exception as exc:
                st.error(f"Token exchange failed: {exc}")
                return

        st.success("Authentication successful — redirecting…")
        st.rerun()
        return

    # ── Authenticated view ─────────────────────────────────────────────────────
    token = _token()

    if token and not token.is_expired:
        _render_connected(config, token)
        return

    if token and token.is_expired:
        st.warning(
            "Your Saxo token has expired. Please reconnect.",
        )
        del st.session_state["saxo_token"]

    # ── Not connected — show Connect button ───────────────────────────────────
    _render_login(config)


def _render_login(config: SaxoConfig) -> None:
    """Show the PKCE login button and redirect instructions."""
    st.subheader("Connection Status")
    col_badge, _ = st.columns([1, 3])
    with col_badge:
        _status_badge("Not connected", "grey")

    st.divider()
    st.subheader("OAuth2 Login (PKCE)")
    st.write(
        "Click the button below to open the Saxo Bank login page. "
        "After logging in you will be redirected back here automatically."
    )
    st.caption(
        f"Redirect URI: `{config.redirect_uri}` — "
        "must match your app registration at developer.saxobank.com"
    )

    # Generate a fresh PKCE session each time the button might be shown
    if "saxo_pkce" not in st.session_state:
        st.session_state["saxo_pkce"] = new_pkce_session()

    pkce: PKCESession = st.session_state["saxo_pkce"]
    authorize_url = build_authorize_url(config, pkce)

    st.link_button(
        "🔐 Connect to Saxo Bank",
        url=authorize_url,
        type="primary",
        use_container_width=True,
    )

    with st.expander("How this works"):
        st.markdown("""
**PKCE OAuth2 flow (RFC 7636):**

1. A random `code_verifier` is generated and stored in your browser session.
2. A `code_challenge` = SHA-256(code_verifier) is sent to Saxo in the authorize URL.
3. After you log in, Saxo redirects back here with `?code=...&state=...`.
4. This app exchanges the code + original verifier for an access token.
5. No client secret is needed — your identity is proven by the verifier.

**Token lifetime:** ~20 minutes (Saxo SIM). You will be asked to reconnect when it expires.
        """)


def _render_connected(config: SaxoConfig, token: TokenData) -> None:
    """Show connected status, token expiry, and a live API test call."""
    mins, secs = divmod(token.seconds_remaining, 60)
    expiry_colour = "green" if token.seconds_remaining > 120 else "orange"

    st.subheader("Connection Status")
    col_badge, col_expiry = st.columns([1, 2])
    with col_badge:
        _status_badge("Connected ✓", "green")
        st.write("")
        st.caption(f"Gateway: `{config.openapi_base}`")
    with col_expiry:
        st.metric(
            "Token expires at",
            token.expires_at_local,
            delta=f"{mins}m {secs}s remaining",
            delta_color="normal" if expiry_colour == "green" else "inverse",
        )

    if st.button("🔓 Disconnect", type="secondary"):
        del st.session_state["saxo_token"]
        st.rerun()

    st.divider()

    # ── Live API test call ─────────────────────────────────────────────────────
    client = SaxoApiClient(token, config.openapi_base)

    st.subheader("Account Overview")
    try:
        user_info = client.get_user_info()
        accounts  = client.get_accounts()
        balance   = client.get_balance()

        # User info row
        u1, u2, u3 = st.columns(3)
        u1.metric("Name",       user_info.get("Name", "—"))
        u2.metric("Client key", user_info.get("ClientKey", "—")[:12] + "…"
                  if len(user_info.get("ClientKey", "")) > 12
                  else user_info.get("ClientKey", "—"))
        u3.metric("Accounts",   len(accounts))

        # Balance row
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Cash balance",    f"{balance.get('CashBalance', 0):,.2f}")
        b2.metric("Net equity",      f"{balance.get('NetEquityForMargin', balance.get('TotalValue', 0)):,.2f}")
        b3.metric("Margin available",f"{balance.get('MarginAvailableForTrading', 0):,.2f}")
        b4.metric("Currency",        balance.get("Currency", "—"))

        # Accounts table
        if accounts:
            st.write("**Accounts**")
            rows = [
                {
                    "Account ID":  a.get("AccountId", "—"),
                    "Account key": a.get("AccountKey", "—"),
                    "Currency":    a.get("Currency", "—"),
                    "Type":        a.get("AccountType", "—"),
                    "Active":      "✅" if a.get("Active", True) else "❌",
                }
                for a in accounts
            ]
            st.dataframe(rows, use_container_width=True)

        # Open positions
        with st.expander("Open positions"):
            try:
                positions = client.get_positions()
                if positions:
                    st.dataframe(positions, use_container_width=True)
                else:
                    st.info("No open positions.")
            except Exception as exc:
                st.warning(f"Could not load positions: {exc}")

    except Exception as exc:
        st.error(
            f"API call failed: {exc}\n\n"
            "Your token may be invalid or the SIM gateway may be unreachable."
        )
