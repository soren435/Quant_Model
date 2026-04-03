"""
Investment Plan + Broker Execution — page rendering.

Page structure:
  1. Portfolio definition (presets or custom tickers/weights)
  2. Investment Plan — capital input, trade table, cost summary
  3. Manual Execution Instructions — step-by-step broker guide
  4. Rebalancing Calculator — holdings input → drift → suggested trades
  5. Saxo Bank Execution — 4-state status panel, credentials, order submission
  6. Portfolio Order Simulation — simulate full portfolio order set
  7. Execution Log — session + file log viewer
  8. Disclaimer
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

from src.execution.trade_engine import (
    compute_trade_plan,
    compute_rebalance_plan,
    detect_currency,
    fetch_latest_prices,
    get_fx_rate,
)
from src.integrations.saxo_client import ConnectionState, SaxoClient
from src.utils.formatting import parse_tickers, parse_weights

# ── Portfolio presets ──────────────────────────────────────────────────────────

_PRESETS: dict[str, dict] = {
    "Custom":                             {"tickers": "",         "weights": ""},
    "Ultra Conservative — 100% Bonds":   {"tickers": "IEF",      "weights": "1.0"},
    "Conservative — 20/80 (SPY/IEF)":   {"tickers": "SPY, IEF", "weights": "0.2, 0.8"},
    "Moderate — 40/60 (SPY/IEF)":       {"tickers": "SPY, IEF", "weights": "0.4, 0.6"},
    "Balanced 60/40":                    {"tickers": "SPY, IEF", "weights": "0.6, 0.4"},
    "Growth — 80/20 (SPY/IEF)":         {"tickers": "SPY, IEF", "weights": "0.8, 0.2"},
    "Aggressive — 100% Equities (SPY)":  {"tickers": "SPY",      "weights": "1.0"},
    "Tech Growth — 70% QQQ / 30% IEF":  {"tickers": "QQQ, IEF", "weights": "0.7, 0.3"},
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _session_log(entry: str) -> None:
    """Append a timestamped entry to the session-level execution log."""
    if "ip_log" not in st.session_state:
        st.session_state.ip_log = []
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.ip_log.append(f"[{ts}] {entry}")


def _get_log() -> list[str]:
    return st.session_state.get("ip_log", [])


def _safe_str(obj: object, key: str, default: str = "—") -> str:
    """
    Safely extract a string value from a dict.
    Returns default if obj is not a dict or the key is absent.
    Never calls .get() on a non-dict.
    """
    if not isinstance(obj, dict):
        return default
    val = obj.get(key, default)
    return str(val) if val is not None else default


def _safe_float(obj: object, key: str, default: float = 0.0) -> float:
    """Safely extract a float value from a dict."""
    if not isinstance(obj, dict):
        return default
    try:
        return float(obj.get(key, default))
    except (TypeError, ValueError):
        return default


def _get_saxo_client() -> SaxoClient:
    """Return the per-session Saxo client, creating it if needed."""
    if "saxo_client" not in st.session_state:
        st.session_state.saxo_client = SaxoClient()
    return st.session_state.saxo_client


# Mode badge shown next to account/balance data
_MODE_BADGES: dict[str, str] = {
    "local_simulation": "🟡 Local Simulation",
    "sim_api":          "🟢 Saxo SIM API",
    "live":             "🔴 Saxo LIVE API",
}


def _mode_badge(data: dict) -> str:
    """Return a display badge string derived from the _mode key in a response dict."""
    return _MODE_BADGES.get(data.get("_mode", ""), "")


# ═══════════════════════════════════════════════════════════════════════════════
# Section renderers
# ═══════════════════════════════════════════════════════════════════════════════

def _render_portfolio_definition() -> tuple[list[str], list[float]] | None:
    """
    Render portfolio definition controls.
    Returns (tickers, weights) or None on invalid input.
    """
    st.subheader("1. Define Your Portfolio")

    col_preset, _ = st.columns([2, 3])
    with col_preset:
        preset_name = st.selectbox(
            "Load a preset",
            list(_PRESETS.keys()),
            index=3,          # Balanced 60/40 default
            key="ip_preset",
        )

    preset = _PRESETS[preset_name]

    col_t, col_w = st.columns(2)
    with col_t:
        tickers_str = st.text_input(
            "Tickers (comma-separated)",
            value=preset["tickers"],
            key=f"ip_tickers_{preset_name}",
        )
    with col_w:
        weights_str = st.text_input(
            "Weights (comma-separated, will be normalised)",
            value=preset["weights"],
            key=f"ip_weights_{preset_name}",
            help="Decimals (0.6, 0.4) or integers (60, 40) — both accepted.",
        )

    tickers = parse_tickers(tickers_str)
    weights = parse_weights(weights_str, len(tickers)) if tickers else None

    if not tickers:
        st.info("Enter at least one ticker to continue.")
        return None
    if weights is None:
        st.error(f"Provide exactly {len(tickers)} weight(s) to match the number of tickers.")
        return None

    # Allocation badge row
    badge_cols = st.columns(min(len(tickers), 5))
    for i, (t, w) in enumerate(zip(tickers, weights)):
        badge_cols[i % len(badge_cols)].metric(t, f"{w * 100:.1f}%")

    return tickers, weights


def _render_investment_plan(
    tickers:    list[str],
    weights:    list[float],
    prices:     dict[str, float],
    target_ccy: str = "DKK",
) -> None:
    """Render the trade plan table and capital summary."""
    st.subheader("2. Investment Plan")

    col_cap, col_ccy = st.columns([2, 1])
    with col_cap:
        capital = st.number_input(
            f"Investment amount ({target_ccy})",
            min_value=1_000.0,
            max_value=100_000_000.0,
            value=100_000.0,
            step=1_000.0,
            format="%.0f",
            key="ip_capital",
        )
    with col_ccy:
        st.metric("Currency", target_ccy)
        st.caption("Prices converted to DKK at live FX rates.")

    # Live FX rate display
    foreign_ccys = sorted({detect_currency(t) for t in tickers} - {target_ccy})
    if foreign_ccys:
        fx_cols = st.columns(len(foreign_ccys))
        for i, ccy in enumerate(foreign_ccys):
            rate = get_fx_rate(ccy, target_ccy)
            fx_cols[i].metric(f"{ccy} → {target_ccy}", f"{rate:.4f}")

    if st.button("📊 Generate Trade Plan", key="ip_generate", type="primary"):
        weights_dict = dict(zip(tickers, weights))
        with st.spinner("Computing trade plan..."):
            plan_df, leftover, log_entry = compute_trade_plan(
                capital, weights_dict, prices, target_ccy
            )
        st.session_state.ip_plan     = plan_df
        st.session_state.ip_leftover = leftover
        st.session_state.ip_capital  = capital
        _session_log(
            f"Trade plan generated — {capital:,.0f} {target_ccy} "
            f"across {tickers}"
        )
        _session_log(log_entry)

    plan_df = st.session_state.get("ip_plan")
    if plan_df is None:
        st.caption("Click **Generate Trade Plan** to calculate buy quantities.")
        return

    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        st.warning("No valid prices found. Check ticker symbols and try again.")
        return

    st.dataframe(plan_df, use_container_width=True)

    leftover = st.session_state.get("ip_leftover", 0.0)
    cap      = st.session_state.get("ip_capital", capital)
    invested = cap - leftover

    s1, s2, s3 = st.columns(3)
    s1.metric("Total Capital",  f"{cap:,.0f} {target_ccy}")
    s2.metric("Total Invested", f"{invested:,.0f} {target_ccy}")
    s3.metric("Leftover Cash",  f"{leftover:,.0f} {target_ccy}",
              help="Undeployed cash due to whole-share constraint.")

    missing = [t for t in tickers if t not in prices]
    if missing:
        st.warning(f"No price data for: {', '.join(missing)} — excluded from plan.")


def _render_manual_instructions(target_ccy: str = "DKK") -> None:
    """Step-by-step manual broker execution guide derived from the trade plan."""
    st.subheader("3. Manual Execution Instructions")

    plan_df = st.session_state.get("ip_plan")
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        st.info("Generate a Trade Plan (step 2) to see execution instructions.")
        return

    with st.expander("📋 How to execute your trades manually", expanded=True):
        st.markdown(
            "Follow these steps for each asset. "
            "Works with any broker — Saxo, Nordnet, Interactive Brokers, etc."
        )
        st.divider()

        shares_col = "Shares to Buy"
        ticker_col = "Ticker"

        if shares_col not in plan_df.columns or ticker_col not in plan_df.columns:
            st.warning("Trade plan does not contain expected columns.")
            return

        step = 1
        for _, row in plan_df.iterrows():
            ticker = str(row.get(ticker_col, ""))
            try:
                shares = int(row.get(shares_col, 0))
            except (ValueError, TypeError):
                shares = 0
            if not ticker or shares <= 0:
                continue

            ccy = detect_currency(ticker)
            col_n, col_i = st.columns([1, 9])
            col_n.markdown(f"**{step}.**")
            col_i.markdown(
                f"Search **`{ticker}`** → Market buy **{shares} share{'s' if shares != 1 else ''}** "
                f"(price quoted in **{ccy}**)"
            )
            step += 1

        st.divider()
        st.markdown(
            "After completing all trades, enter your share counts "
            "in the Rebalancing Calculator (step 4) to track future drift."
        )
        st.caption(
            "⚠️ Actual fill prices may differ. "
            "Always confirm quantities with your broker before executing."
        )


def _render_rebalancing(
    tickers:    list[str],
    weights:    list[float],
    prices:     dict[str, float],
    target_ccy: str = "DKK",
) -> None:
    """Rebalancing calculator — current holdings vs target weights."""
    st.subheader("4. Rebalancing Calculator")
    st.caption(
        "Enter your current share holdings below. "
        "Positions that have drifted beyond the threshold will be flagged."
    )

    threshold = st.slider(
        "Drift threshold (% of portfolio)",
        min_value=1, max_value=20, value=5, step=1,
        help="Only positions with absolute drift above this level trigger a trade.",
        key="ip_threshold",
    )

    holdings_df = pd.DataFrame({
        "Ticker":      tickers,
        "Shares Held": [0.0] * len(tickers),
    })
    edited = st.data_editor(
        holdings_df,
        key="ip_holdings_editor",
        use_container_width=True,
        column_config={
            "Ticker":      st.column_config.TextColumn("Ticker",      disabled=True),
            "Shares Held": st.column_config.NumberColumn("Shares Held",
                                                          min_value=0.0, step=1.0),
        },
    )

    if st.button("🔄 Calculate Rebalancing Trades", key="ip_rebalance"):
        current_shares = dict(zip(edited["Ticker"], edited["Shares Held"]))
        weights_dict   = dict(zip(tickers, weights))
        with st.spinner("Computing rebalancing plan..."):
            rebal_df, log_entry = compute_rebalance_plan(
                current_shares, weights_dict, prices,
                threshold_pct=float(threshold),
                target_ccy=target_ccy,
            )
        st.session_state.ip_rebal_df = rebal_df
        _session_log(f"Rebalancing — threshold {threshold}%, tickers {tickers}")
        _session_log(log_entry)

    rebal_df = st.session_state.get("ip_rebal_df")
    if rebal_df is None:
        return
    if not isinstance(rebal_df, pd.DataFrame) or rebal_df.empty:
        st.info("No rebalancing data — check that portfolio has non-zero value.")
        return

    # Colour-code Action column (pandas >= 2.1 uses .map, older uses .applymap)
    action_col = "Action"
    def _colour(val: str) -> str:
        if val == "BUY":  return "background-color:#d4edda;color:#155724;"
        if val == "SELL": return "background-color:#f8d7da;color:#721c24;"
        return ""

    if action_col in rebal_df.columns:
        try:
            styled = rebal_df.style.map(_colour, subset=[action_col])
        except AttributeError:
            styled = rebal_df.style.applymap(_colour, subset=[action_col])
        st.dataframe(styled, use_container_width=True)
    else:
        st.dataframe(rebal_df, use_container_width=True)

    if action_col in rebal_df.columns:
        trade_count = (rebal_df[action_col].isin(["BUY", "SELL"])).sum()
    else:
        trade_count = 0

    if trade_count == 0:
        st.success(f"✅ All positions within the {threshold}% band — no trades needed.")
    else:
        st.info(f"**{trade_count}** position(s) exceed the {threshold}% threshold.")


def _render_broker_status(client: SaxoClient) -> None:
    """Render a compact broker status banner showing the current connection state."""
    state  = client.get_connection_state()
    status = client.status()   # always returns a dict

    # Colour map → st.success / st.warning / st.info / st.error
    _renderers = {
        ConnectionState.SIMULATION:    st.warning,
        ConnectionState.SIM_API:       st.success,
        ConnectionState.NOT_CONNECTED: st.info,
        ConnectionState.CONNECTED:     st.success,
        ConnectionState.AUTH_ERROR:    st.error,
    }
    renderer = _renderers.get(state, st.info)

    msg_parts = [f"**Broker status: {status['label']}**"]

    if state == ConnectionState.SIMULATION:
        msg_parts.append("Fully functional in simulation — no credentials required.")
    elif state == ConnectionState.SIM_API:
        msg_parts.append(
            "Connected to Saxo SIM gateway — real API calls, no real money."
        )
    elif state == ConnectionState.NOT_CONNECTED:
        msg_parts.append(
            "Live mode is active but no access token has been obtained. "
            "Open the credentials panel below to authenticate."
        )
    elif state == ConnectionState.CONNECTED:
        msg_parts.append("Authenticated and ready to place live orders.")
    elif state == ConnectionState.AUTH_ERROR:
        err = status.get("auth_error") or "Unknown error"
        msg_parts.append(f"Last authentication failed: _{err}_")

    renderer("  \n".join(msg_parts))


def _render_saxo_panel(tickers: list[str]) -> None:
    """Saxo Bank simulation / execution panel with 4-state status management."""
    st.subheader("5. Broker Execution — Saxo Bank")

    client = _get_saxo_client()

    # ── Status banner ──────────────────────────────────────────────────────────
    _render_broker_status(client)
    st.divider()

    # ── Mode toggle ────────────────────────────────────────────────────────────
    new_sim = st.toggle(
        "Force mock simulation (no API calls)",
        value=client.simulation_mode,
        key="ip_sim_toggle",
        help=(
            "ON = internal mock data, no API calls. "
            "OFF = real API calls (SIM gateway with token + SAXO_ENV=sim, "
            "or live gateway with SAXO_ENV=live)."
        ),
    )

    if new_sim != client.simulation_mode:
        st.session_state.saxo_client = SaxoClient(simulation_mode=new_sim)
        client = st.session_state.saxo_client
        _session_log(f"Broker mode → simulation_mode={new_sim}")
        st.rerun()

    current_state = client.get_connection_state()
    if current_state == ConnectionState.CONNECTED:
        st.error(
            "⚠️ **LIVE MODE ACTIVE** — orders will be sent to Saxo Bank "
            "and may result in real trades. Proceed with extreme caution."
        )
    elif current_state == ConnectionState.SIM_API:
        st.info(
            "🟢 **Saxo SIM API** — real API calls to simulation gateway. "
            "No real money involved."
        )

    st.divider()

    # ── Setup instructions ─────────────────────────────────────────────────────
    with st.expander("🔑 Saxo API Setup — Connect Your Account", expanded=False):
        st.markdown(
            "**To connect to Saxo, set up your `.env` file in 3 steps:**\n\n"
            "**Step 1 — Get a bearer token**\n"
            "Log in at [developer.saxobank.com](https://developer.saxobank.com), "
            "create an app, and generate an access token.\n\n"
            "**Step 2 — Create a `.env` file** in the project root:\n"
            "```\n"
            "SAXO_ACCESS_TOKEN=your_token_here\n"
            "SAXO_ENV=sim\n"
            "```\n"
            "| `SAXO_ENV` | Token | Result |\n"
            "|---|---|---|\n"
            "| `sim` | absent | Internal mock data (no API calls) |\n"
            "| `sim` | present | **Real Saxo SIM gateway** — no real money |\n"
            "| `live` | present | **Live trading** — real money |\n\n"
            "**Step 3 — Restart the app.** "
            "The token is loaded automatically at startup.\n\n"
            "> Your token is stored only in your local `.env` file. "
            "It is listed in `.gitignore` and will never be committed to git."
        )

    st.divider()

    # ── Test connection ────────────────────────────────────────────────────────
    if st.button("🔌 Test Saxo Connection", key="ip_test_conn"):
        with st.spinner("Testing connection..."):
            conn_info = client.get_account_info()
        st.session_state.ip_conn_test = conn_info
        _session_log(
            f"Connection test — status={_safe_str(conn_info, 'status')}, "
            f"AccountId={_safe_str(conn_info, 'AccountId')}"
        )

    conn_test = st.session_state.get("ip_conn_test")
    if isinstance(conn_test, dict):
        conn_status = _safe_str(conn_test, "status")
        if conn_test.get("connected"):
            badge = _mode_badge(conn_test)
            st.success(
                f"✅ Connected — "
                f"Account: `{_safe_str(conn_test, 'AccountId')}` "
                f"| Currency: {_safe_str(conn_test, 'Currency')} "
                f"| {badge}"
            )
        elif conn_status == "not_connected":
            st.warning(
                "⚪ No token found — set `SAXO_ACCESS_TOKEN` in your `.env` file "
                "and restart the app."
            )
        elif conn_status == "error":
            st.error(
                f"🔴 Connection failed: {_safe_str(conn_test, 'error', 'Unknown error')}"
            )
        else:
            st.info(f"Status: {conn_status}")

    st.divider()

    # ── Account info & balance (only shown if connected) ───────────────────────
    state = client.get_connection_state()

    if not client.is_connected():
        st.info(
            "Connect to Saxo Bank via the credentials panel above to view "
            "account details and cash balance."
        )
    else:
        col_info, col_bal = st.columns(2)

        with col_info:
            if st.button("📋 Fetch Account Info", key="ip_acct_btn"):
                raw = client.get_account_info()
                # get_account_info() guarantees a dict — guard anyway
                st.session_state.ip_acct_info = raw if isinstance(raw, dict) else {}
                _session_log(f"Account info fetched: {_safe_str(raw, 'AccountId')}")

        with col_bal:
            if st.button("💰 Fetch Cash Balance", key="ip_bal_btn"):
                raw = client.get_cash_balance()
                st.session_state.ip_cash_bal = raw if isinstance(raw, dict) else {}
                _session_log(f"Cash balance fetched: {_safe_str(raw, 'CashAvailableForTrading')}")

        # Display — guarded with isinstance before calling _safe_str
        acct = st.session_state.get("ip_acct_info")
        if isinstance(acct, dict) and acct:
            st.caption(
                f"Account: `{_safe_str(acct, 'AccountId')}` "
                f"| Type: {_safe_str(acct, 'AccountType')} "
                f"| Currency: {_safe_str(acct, 'Currency')} "
                f"| {_mode_badge(acct)}"
            )

        bal = st.session_state.get("ip_cash_bal")
        if isinstance(bal, dict) and bal:
            cash = _safe_float(bal, "CashAvailableForTrading")
            ccy  = _safe_str(bal, "Currency", "DKK")
            st.caption(
                f"Available cash: **{cash:,.2f} {ccy}** | {_mode_badge(bal)}"
            )

    st.divider()

    # ── Order submission ───────────────────────────────────────────────────────
    st.markdown("**Submit orders from your trade plan**")

    plan_df = st.session_state.get("ip_plan")
    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        st.info("Generate a Trade Plan (step 2) first to enable order submission.")
        return

    shares_col = "Shares to Buy"
    ticker_col = "Ticker"

    if shares_col not in plan_df.columns or ticker_col not in plan_df.columns:
        st.warning("Trade plan is missing expected columns — regenerate it.")
        return

    # Order preview table
    preview = (
        plan_df[[ticker_col, shares_col]]
        .rename(columns={ticker_col: "Ticker", shares_col: "Shares"})
        .copy()
    )
    preview = preview[preview["Shares"].apply(
        lambda x: isinstance(x, (int, float)) and x > 0
    )]
    if preview.empty:
        st.info("No shares to buy in the current plan (all quantities are zero).")
        return

    st.dataframe(preview, use_container_width=True, hide_index=True)

    # Payload preview expander
    with st.expander("🔍 Preview order payloads (JSON)", expanded=False):
        for _, row in preview.iterrows():
            ticker = str(row["Ticker"])
            shares = int(row["Shares"])
            instr  = client.lookup_instrument(ticker)
            if isinstance(instr, dict):
                payload = client.build_order_payload(
                    uic=instr.get("Uic", 0),
                    asset_type=_safe_str(instr, "AssetType", "Stock"),
                    buy_sell="Buy",
                    amount=shares,
                )
                st.markdown(f"**{ticker}**")
                st.code(json.dumps(payload, indent=2), language="json")
            else:
                st.warning(f"Could not look up instrument for `{ticker}`.")

    # Confirmation and submit
    mode_label = "Simulation — no real trades" if client.simulation_mode else "LIVE — real money"
    confirmed = st.checkbox(
        f"I confirm I want to submit these orders ({mode_label})",
        key="ip_confirm_orders",
    )

    btn_label = (
        "🚀 Submit Simulated Orders"
        if client.simulation_mode
        else "⚠️  SUBMIT LIVE ORDERS TO SAXO"
    )
    btn_type = "secondary" if client.simulation_mode else "primary"

    if st.button(btn_label, disabled=not confirmed,
                 key="ip_submit_orders", type=btn_type):

        results: list[dict] = []

        for _, row in preview.iterrows():
            ticker = str(row["Ticker"])
            try:
                shares = int(row["Shares"])
            except (ValueError, TypeError):
                continue
            if shares <= 0:
                continue

            instr = client.lookup_instrument(ticker)
            if not isinstance(instr, dict):
                results.append({
                    "Ticker":   ticker,
                    "Shares":   shares,
                    "Order ID": "—",
                    "Status":   "❌ Failed",
                    "Message":  "Instrument not found.",
                })
                continue

            payload = client.build_order_payload(
                uic=instr.get("Uic", 0),
                asset_type=_safe_str(instr, "AssetType", "Stock"),
                buy_sell="Buy",
                amount=shares,
            )
            result = client.place_order(payload, confirmed=confirmed)

            # result is always a dict from place_order()
            if not isinstance(result, dict):
                result = {"success": False, "simulated": True,
                          "order_id": None, "message": "Unexpected result type."}

            status_icon = (
                "✅ Simulated" if result.get("simulated")
                else ("✅ Placed" if result.get("success") else "❌ Failed")
            )
            results.append({
                "Ticker":   ticker,
                "Shares":   shares,
                "Order ID": result.get("order_id") or "—",
                "Status":   status_icon,
                "Message":  result.get("message", ""),
            })
            verb = "simulated" if result.get("simulated") else "placed"
            _session_log(
                f"Order {verb}: {ticker} BUY {shares} | "
                f"ID: {result.get('order_id', '—')}"
            )

        st.session_state.ip_order_results = results
        st.success(f"{len(results)} order(s) processed.")

    order_results = st.session_state.get("ip_order_results")
    if isinstance(order_results, list) and order_results:
        st.dataframe(
            pd.DataFrame(order_results),
            use_container_width=True,
            hide_index=True,
        )


def _simulate_portfolio_orders(
    tickers:    list[str],
    weights:    list[float],
    prices:     dict[str, float],
    target_ccy: str = "DKK",
) -> None:
    """
    Section 6 — Portfolio Order Simulation.

    Generates one Saxo order payload per portfolio asset, runs each through
    simulate_order(), and displays the results in a table.  No live orders
    are ever placed here.
    """
    st.subheader("6. Portfolio Order Simulation")
    st.caption(
        "Simulate the full set of portfolio orders via Saxo Bank. "
        "Results are dry-runs only — no real orders are placed."
    )

    client  = _get_saxo_client()
    plan_df = st.session_state.get("ip_plan")

    if not isinstance(plan_df, pd.DataFrame) or plan_df.empty:
        st.info("Generate a Trade Plan (step 2) first to enable portfolio simulation.")
        return

    capital    = st.session_state.get("ip_capital", 0.0)
    shares_col = "Shares to Buy"
    ticker_col = "Ticker"
    alloc_col  = f"Allocation ({target_ccy})"
    price_col  = f"Price ({target_ccy})"

    if shares_col not in plan_df.columns or ticker_col not in plan_df.columns:
        st.warning("Trade plan is missing expected columns — regenerate it.")
        return

    # Build the list of items to simulate (skip zero-share rows)
    sim_items: list[dict] = []
    for _, row in plan_df.iterrows():
        ticker = str(row.get(ticker_col, ""))
        try:
            shares = int(row.get(shares_col, 0))
        except (ValueError, TypeError):
            shares = 0
        if not ticker or shares <= 0:
            continue

        weight_raw = row.get("Weight", "")
        try:
            weight_pct = float(str(weight_raw).rstrip("%"))
        except (ValueError, TypeError):
            weight_pct = 0.0

        alloc = row.get(alloc_col, 0.0)
        price = row.get(price_col, 0.0)

        sim_items.append({
            "ticker":     ticker,
            "weight_pct": weight_pct,
            "alloc":      alloc,
            "price":      price,
            "shares":     shares,
        })

    if not sim_items:
        st.info("No shares to simulate — all quantities in the trade plan are zero.")
        return

    st.caption(
        f"**{len(sim_items)} asset(s)** ready | "
        f"Capital: **{capital:,.0f} {target_ccy}**"
    )

    if st.button("🧪 Simulate Portfolio Orders", key="ip_sim_portfolio", type="primary"):
        results: list[dict] = []
        progress_bar = st.progress(0, text="Starting simulation…")
        n = len(sim_items)

        for i, item in enumerate(sim_items):
            ticker = item["ticker"]
            shares = item["shares"]
            progress_bar.progress((i) / n, text=f"Looking up {ticker}…")

            # ── Instrument lookup ──────────────────────────────────────────────
            instr = client.lookup_instrument(ticker)

            if not isinstance(instr, dict):
                results.append({
                    "Ticker":              ticker,
                    "Weight":              f"{item['weight_pct']:.1f}%",
                    f"Allocation ({target_ccy})": f"{item['alloc']:,.0f}",
                    f"Price ({target_ccy})":      "—",
                    "Shares":              shares,
                    "Uic":                 "—",
                    "AssetType":           "—",
                    "Status":              "❌ Lookup failed",
                    "Order ID":            "—",
                })
                _session_log(f"Simulation: {ticker} — instrument lookup failed")
                progress_bar.progress((i + 1) / n, text=f"Lookup failed: {ticker}")
                continue

            uic        = instr.get("Uic", 0)
            asset_type = _safe_str(instr, "AssetType", "Stock")

            # ── Build payload ──────────────────────────────────────────────────
            payload = client.build_order_payload(
                uic=uic,
                asset_type=asset_type,
                buy_sell="Buy",
                amount=shares,
            )

            # ── Simulate (always safe — never touches live orders) ─────────────
            progress_bar.progress((i) / n, text=f"Simulating {ticker}…")
            sim_result = client.simulate_order(payload)

            if not isinstance(sim_result, dict):
                sim_result = {"success": False, "order_id": None,
                              "message": "Unexpected result."}

            status   = "✅ Simulated" if sim_result.get("success") else "❌ Failed"
            order_id = sim_result.get("order_id") or "—"

            results.append({
                "Ticker":              ticker,
                "Weight":              f"{item['weight_pct']:.1f}%",
                f"Allocation ({target_ccy})": f"{item['alloc']:,.0f}",
                f"Price ({target_ccy})":      f"{item['price']:,.2f}",
                "Shares":              shares,
                "Uic":                 str(uic),
                "AssetType":           asset_type,
                "Status":              status,
                "Order ID":            order_id,
            })
            _session_log(
                f"Simulation: {ticker} BUY {shares} | "
                f"Uic={uic} | AssetType={asset_type} | "
                f"ID={order_id} | {sim_result.get('message', '')}"
            )
            progress_bar.progress((i + 1) / n, text=f"Done: {ticker}")

        progress_bar.empty()
        st.session_state.ip_sim_results = results

        success_n = sum(1 for r in results if r["Status"].startswith("✅"))
        fail_n    = len(results) - success_n

        if fail_n == 0:
            st.success(f"All {success_n} order(s) simulated successfully.")
        else:
            st.warning(
                f"{success_n} order(s) simulated | "
                f"{fail_n} failed (instrument lookup error — "
                "check ticker symbols or Saxo connection)."
            )

    # ── Results table ──────────────────────────────────────────────────────────
    sim_results = st.session_state.get("ip_sim_results")
    if not (isinstance(sim_results, list) and sim_results):
        return

    st.dataframe(
        pd.DataFrame(sim_results),
        use_container_width=True,
        hide_index=True,
    )

    # Summary metrics row
    total_n   = len(sim_results)
    success_n = sum(1 for r in sim_results if r["Status"].startswith("✅"))
    fail_n    = total_n - success_n

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Orders",    total_n)
    m2.metric("Simulated",       success_n)
    m3.metric("Lookup Failures", fail_n)

    if fail_n > 0:
        failed_tickers = [
            r["Ticker"] for r in sim_results if not r["Status"].startswith("✅")
        ]
        st.caption(
            f"Failed tickers: `{', '.join(failed_tickers)}` — "
            "verify these are supported on Saxo or check your connection."
        )


def _render_execution_log() -> None:
    """Session log + persistent file log viewer."""
    st.subheader("7. Execution Log")

    session_log = _get_log()
    log_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "logs", "execution_log.jsonl")
    )

    with st.expander(f"Session log — {len(session_log)} entries", expanded=False):
        if session_log:
            st.code("\n".join(session_log), language="text")
        else:
            st.caption("No events recorded yet in this session.")

    with st.expander("Persistent log file (execution_log.jsonl)", expanded=False):
        st.caption(f"Location: `{log_path}`")
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()
            recent = lines[-50:]
            st.code("".join(recent), language="json")
            if len(lines) > 50:
                st.caption(f"Showing last 50 of {len(lines)} entries.")
        else:
            st.caption("Log file not yet created.")

    if st.button("🗑️ Clear session log", key="ip_clear_log"):
        st.session_state.ip_log = []
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Page entry point
# ═══════════════════════════════════════════════════════════════════════════════

def render_investment_plan(lang: str = "en") -> None:
    """
    Render the Investment Plan + Broker Execution page.

    Args:
        lang: UI language code (reserved for future localisation).
    """
    st.header("💰 Investment Plan & Execution")
    st.caption(
        "Convert a portfolio into concrete buy orders, check rebalancing needs, "
        "and simulate or execute trades via Saxo Bank."
    )

    TARGET_CCY = "DKK"

    # Step 1: portfolio definition
    result = _render_portfolio_definition()
    if result is None:
        return
    tickers, weights = result

    st.divider()

    # Fetch latest prices once — all sections below share this dict
    with st.spinner("Fetching latest prices..."):
        prices = fetch_latest_prices(tickers)

    if not prices:
        st.error(
            "Could not retrieve prices for any ticker. "
            "Check your internet connection and ticker symbols."
        )
        return

    # Step 2: trade plan
    _render_investment_plan(tickers, weights, prices, TARGET_CCY)
    st.divider()

    # Step 3: manual instructions
    _render_manual_instructions(TARGET_CCY)
    st.divider()

    # Step 4: rebalancing
    _render_rebalancing(tickers, weights, prices, TARGET_CCY)
    st.divider()

    # Step 5: Saxo broker panel
    _render_saxo_panel(tickers)
    st.divider()

    # Step 6: portfolio order simulation
    _simulate_portfolio_orders(tickers, weights, prices, TARGET_CCY)
    st.divider()

    # Step 7: execution log
    _render_execution_log()

    # Disclaimer
    st.divider()
    st.caption(
        "⚠️ **Disclaimer:** This is a decision-support tool, not investment advice. "
        "All results are based on historical data and current market prices. "
        "Past performance does not guarantee future results. "
        "Always verify trade quantities and prices with your broker before executing. "
        "Consult a qualified financial advisor before making investment decisions."
    )
