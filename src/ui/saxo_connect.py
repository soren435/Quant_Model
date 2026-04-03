"""
UI — Saxo Bank Connect tab.

Guides the user through the full OAuth2 authorization-code flow:
  1. Enter client_id / client_secret (or confirm they are in .env)
  2. Click "Connect" → open Saxo login page
  3. Saxo redirects back to http://localhost:8501/?code=XXX
  4. This page auto-detects the code, exchanges it for tokens, persists them
  5. Shows live account info + balance + token expiry countdown

Also supports manual token entry (paste from Saxo Developer Portal) as a
quick fallback when client credentials are not available.
"""
from __future__ import annotations
import os
import time
from pathlib import Path

import streamlit as st

from src.integrations.saxo_auth import SaxoAuth
from src.integrations.saxo_client import SaxoClient

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_env_pair(key: str, value: str) -> None:
    """Write/update a key in .env without disturbing other lines."""
    try:
        from dotenv import set_key
        set_key(str(_ENV_FILE), key, value, quote_mode="never")
        os.environ[key] = value
    except Exception:
        pass


def _get_auth() -> SaxoAuth:
    """Return a cached SaxoAuth instance stored in Streamlit session state."""
    if "saxo_auth" not in st.session_state:
        st.session_state.saxo_auth = SaxoAuth()
    return st.session_state.saxo_auth


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


# ── Main render ────────────────────────────────────────────────────────────────

def render_saxo_connect(lang: str = "en") -> None:
    st.header("🔗 Saxo Bank — Connect")
    st.caption(
        "Connect to your Saxo Bank account via OAuth2. "
        "All trades remain in simulation mode unless you explicitly switch to live."
    )

    auth = _get_auth()

    # ── Handle OAuth2 callback (code in URL) ──────────────────────────────────
    params = st.query_params
    if "code" in params:
        code  = params["code"]
        state = params.get("state", None)
        st.query_params.clear()

        with st.spinner("Exchanging authorization code for tokens…"):
            try:
                tokens = auth.exchange_code(code, state)
                st.success(
                    f"✅ Connected! Token valid until **{tokens.expires_at_str}** "
                    f"({tokens.seconds_remaining}s remaining). "
                    f"Refresh token {'stored ✓' if tokens.refresh_token else 'not returned'}."
                )
                st.session_state.saxo_auth = auth
                st.rerun()
            except Exception as exc:
                st.error(f"Token exchange failed: {exc}")
        return

    # ── Current status ────────────────────────────────────────────────────────
    status = auth.status()
    client = SaxoClient()
    conn   = client.status()

    st.subheader("Connection Status")
    s_col, i_col = st.columns([1, 2])

    with s_col:
        if conn["authenticated"]:
            _status_badge(conn["label"], "green")
        elif conn["state"] == "not_connected":
            _status_badge(conn["label"], "grey")
        elif conn["state"] == "auth_error":
            _status_badge(conn["label"], "red")
        else:
            _status_badge(conn["label"], "orange")

        st.write("")
        st.caption(f"Environment: **{status['env'].upper()}**")
        st.caption(f"Gateway: `{conn['base_url']}`")

    with i_col:
        if auth.has_tokens():
            t = auth._tokens
            remaining = t.seconds_remaining if t else 0
            mins, secs = divmod(remaining, 60)
            if remaining > 120:
                st.metric("Token expires", t.expires_at_str if t else "—",
                          delta=f"{mins}m {secs}s remaining")
            else:
                st.metric("Token expires", "Refreshing…", delta=f"{remaining}s left",
                          delta_color="inverse")

            has_refresh = bool(t and t.refresh_token)
            st.caption(f"Refresh token: {'✅ stored' if has_refresh else '❌ not available (manual token)'}")
        else:
            st.info("No token loaded. Complete the OAuth2 flow below.")

    st.divider()

    # ── Account + balance (when connected) ────────────────────────────────────
    if conn["authenticated"] or conn["state"] == "sim_api":
        st.subheader("Account")
        account = client.get_account_info()
        balance = client.get_cash_balance()

        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Account ID", account.get("AccountId", "—"))
        a2.metric("Currency",   account.get("Currency", "—"))
        a3.metric(
            "Cash Balance",
            f"{balance.get('cash') or balance['raw'].get('CashBalance', 0):,.0f}",
            delta=balance.get("currency", ""),
        )
        a4.metric("Mode", conn["state"].upper().replace("_", " "))

        if conn["state"] != "sim_api":
            st.warning(
                "⚠️ You are connected to the **live** gateway. "
                "Orders placed here will involve real money."
            )

        st.divider()

    # ── OAuth2 flow ────────────────────────────────────────────────────────────
    st.subheader("OAuth2 Authorization")

    tab_oauth, tab_manual, tab_setup = st.tabs(
        ["🔐 OAuth2 Login", "📋 Paste Token", "⚙️ App Setup"]
    )

    # ── Tab 1: Full OAuth2 flow ────────────────────────────────────────────────
    with tab_oauth:
        if not status["configured"]:
            st.warning(
                "**SAXO_CLIENT_ID** and **SAXO_CLIENT_SECRET** are not set. "
                "Register your app at [developer.saxobank.com](https://developer.saxobank.com) "
                "or paste your credentials in the **App Setup** tab."
            )
        else:
            st.write(
                "Click the button below to open the Saxo login page. "
                "After logging in, Saxo will redirect back here automatically."
            )
            st.caption(
                f"Redirect URI: `{status['redirect_uri']}` "
                "(must match your app registration)"
            )

            if st.button("🔐 Connect to Saxo Bank", type="primary", use_container_width=True):
                url, state = auth.get_authorization_url()
                st.session_state.saxo_auth = auth  # persist pending_state
                st.markdown(
                    f"**[→ Click here to log in to Saxo Bank]({url})**\n\n"
                    "_After logging in you will be redirected back to this page._",
                    unsafe_allow_html=False,
                )
                st.info(
                    "If the redirect does not happen automatically, copy the full "
                    "URL from the browser after login and paste it into the "
                    "address bar as `http://localhost:8501/?code=...`"
                )

            # Manual refresh button
            if auth.has_tokens() and auth._tokens and auth._tokens.refresh_token:
                st.write("")
                if st.button("🔄 Refresh token now", type="secondary"):
                    try:
                        tokens = auth.refresh()
                        st.success(
                            f"Token refreshed. New expiry: **{tokens.expires_at_str}** "
                            f"({tokens.seconds_remaining}s remaining)."
                        )
                        st.session_state.saxo_auth = auth
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Refresh failed: {exc}")

    # ── Tab 2: Manual token paste ─────────────────────────────────────────────
    with tab_manual:
        st.caption(
            "Use this if you have a fresh token from "
            "[developer.saxobank.com](https://developer.saxobank.com) "
            "or a custom auth flow. Note: no refresh token — expires in ~20 minutes."
        )
        with st.form("manual_token_form"):
            pasted = st.text_area(
                "Paste access token",
                height=120,
                placeholder="eyJhbGciOiJFUzI1NiIsIn...",
                help="Bearer token from Saxo Developer Portal or your own OAuth flow.",
            )
            submitted = st.form_submit_button("Apply token", type="primary")

        if submitted and pasted.strip():
            try:
                auth.set_manual_token(pasted.strip())
                st.session_state.saxo_auth = auth
                t = auth._tokens
                st.success(
                    f"Token applied. Expires at **{t.expires_at_str}** "
                    f"({t.seconds_remaining}s remaining). "
                    "No refresh token — re-paste when it expires."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Could not parse token: {exc}")

    # ── Tab 3: App setup ──────────────────────────────────────────────────────
    with tab_setup:
        st.markdown("""
**How to register a Saxo app** (one-time setup):

1. Go to [developer.saxobank.com](https://developer.saxobank.com) → **My Apps** → **Create app**
2. Set the redirect URI to: `http://localhost:8501/`
3. Copy **Client ID** and **Client Secret**
4. Paste them below — they will be saved to your `.env` file
        """)

        with st.form("app_credentials_form"):
            env_opt = st.radio(
                "Environment",
                options=["sim", "live"],
                index=0 if os.getenv("SAXO_ENV", "sim") == "sim" else 1,
                horizontal=True,
                help="'sim' = simulation gateway, no real money. 'live' = real account.",
            )
            client_id = st.text_input(
                "Client ID",
                value=os.getenv("SAXO_CLIENT_ID", ""),
                type="password",
            )
            client_secret = st.text_input(
                "Client Secret",
                value=os.getenv("SAXO_CLIENT_SECRET", ""),
                type="password",
            )
            redirect_uri = st.text_input(
                "Redirect URI",
                value=os.getenv("SAXO_REDIRECT_URI", "http://localhost:8501/"),
                help="Must exactly match the redirect URI in your Saxo app registration.",
            )
            save = st.form_submit_button("💾 Save to .env", type="primary")

        if save:
            if client_id:
                _write_env_pair("SAXO_CLIENT_ID", client_id)
            if client_secret:
                _write_env_pair("SAXO_CLIENT_SECRET", client_secret)
            if redirect_uri:
                _write_env_pair("SAXO_REDIRECT_URI", redirect_uri)
            _write_env_pair("SAXO_ENV", env_opt)

            # Reinitialise auth with new credentials
            st.session_state.saxo_auth = SaxoAuth()
            st.success("Credentials saved to `.env`. Ready to connect.")
            st.rerun()

        st.divider()
        st.subheader("Current .env values")
        env_display = {
            "SAXO_ENV":          os.getenv("SAXO_ENV", "—"),
            "SAXO_CLIENT_ID":    "✅ set" if os.getenv("SAXO_CLIENT_ID") else "❌ not set",
            "SAXO_CLIENT_SECRET":"✅ set" if os.getenv("SAXO_CLIENT_SECRET") else "❌ not set",
            "SAXO_REDIRECT_URI": os.getenv("SAXO_REDIRECT_URI", "—"),
            "SAXO_ACCESS_TOKEN": "✅ set" if os.getenv("SAXO_ACCESS_TOKEN") else "❌ not set",
            "SAXO_REFRESH_TOKEN":"✅ set" if os.getenv("SAXO_REFRESH_TOKEN") else "❌ not set",
            "SAXO_TOKEN_EXPIRY": os.getenv("SAXO_TOKEN_EXPIRY", "—"),
        }
        for k, v in env_display.items():
            st.caption(f"`{k}`: {v}")
