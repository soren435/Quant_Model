"""
Trade Engine — pure functions for investment plan and rebalancing calculations.

No Streamlit dependency; all functions are independently testable.

Public API:
    detect_currency(ticker)
    get_fx_rate(from_ccy, to_ccy)           → float
    fetch_latest_prices(tickers)             → dict[ticker, price]
    compute_trade_plan(...)                  → (DataFrame, leftover_dkk)
    compute_rebalance_plan(...)              → DataFrame
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

# ── Module-level logger (writes to logs/execution_log.jsonl) ──────────────────

_LOG_DIR  = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "execution_log.jsonl")

os.makedirs(_LOG_DIR, exist_ok=True)

_file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(message)s"))

logger = logging.getLogger("trade_engine")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_file_handler)


def _log(event_type: str, payload: dict[str, Any]) -> str:
    """Write a JSON-Lines entry to execution_log.jsonl and return the log string."""
    entry = {
        "timestamp": pd.Timestamp.now().isoformat(timespec="seconds"),
        "type":      event_type,
        **payload,
    }
    logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    return f"[{entry['timestamp']}] {event_type.upper()}: {json.dumps(payload, default=str)}"


# ── Currency detection ─────────────────────────────────────────────────────────

# Maps Yahoo Finance ticker suffix → ISO currency code
_SUFFIX_CCY: dict[str, str] = {
    ".AS": "EUR",   # Amsterdam (Euronext)
    ".DE": "EUR",   # Frankfurt / XETRA
    ".PA": "EUR",   # Paris (Euronext)
    ".BR": "EUR",   # Brussels
    ".MI": "EUR",   # Milan
    ".CO": "DKK",   # Copenhagen (Nasdaq Nordic)
    ".ST": "SEK",   # Stockholm
    ".HE": "EUR",   # Helsinki
    ".OL": "NOK",   # Oslo
    ".L":  "GBP",   # London (LSE)
    ".SW": "CHF",   # Swiss Exchange
}

def detect_currency(ticker: str) -> str:
    """
    Infer the trading currency from the Yahoo Finance ticker suffix.
    US-listed tickers (no dot suffix) default to USD.
    """
    for suffix, ccy in _SUFFIX_CCY.items():
        if ticker.upper().endswith(suffix.upper()):
            return ccy
    return "USD"


# ── FX rates ───────────────────────────────────────────────────────────────────

# Fallback rates (used when Yahoo Finance is unavailable)
_FX_FALLBACKS: dict[tuple[str, str], float] = {
    ("USD", "DKK"): 6.90,
    ("EUR", "DKK"): 7.46,
    ("GBP", "DKK"): 8.75,
    ("SEK", "DKK"): 0.63,
    ("NOK", "DKK"): 0.61,
    ("CHF", "DKK"): 7.82,
    ("USD", "USD"): 1.0,
    ("DKK", "DKK"): 1.0,
    ("EUR", "EUR"): 1.0,
}


def get_fx_rate(from_ccy: str, to_ccy: str) -> float:
    """
    Fetch the latest FX rate from Yahoo Finance (from_ccy → to_ccy).
    Falls back to a hardcoded approximate rate if the feed is unavailable.

    Args:
        from_ccy: Source currency ISO code (e.g. "USD").
        to_ccy:   Target currency ISO code (e.g. "DKK").

    Returns:
        Float rate: 1 unit of from_ccy expressed in to_ccy.
    """
    if from_ccy == to_ccy:
        return 1.0

    sym = f"{from_ccy}{to_ccy}=X"
    try:
        end   = date.today()
        start = end - timedelta(days=5)
        hist  = yf.download(sym, start=start.isoformat(), end=end.isoformat(),
                            progress=False, auto_adjust=True)
        if not hist.empty:
            close_col = "Close" if "Close" in hist.columns else hist.columns[0]
            col_data = hist[close_col]
            if isinstance(col_data, pd.DataFrame):
                col_data = col_data.iloc[:, 0]
            rate = float(col_data.dropna().iloc[-1])
            if rate > 0:
                return rate
    except Exception:
        pass

    fallback = _FX_FALLBACKS.get((from_ccy, to_ccy))
    if fallback:
        return fallback

    # Try inverse
    inv = _FX_FALLBACKS.get((to_ccy, from_ccy))
    if inv and inv > 0:
        return 1.0 / inv

    return 1.0  # last resort


# ── Price fetching ─────────────────────────────────────────────────────────────

def fetch_latest_prices(tickers: list[str]) -> dict[str, float]:
    """
    Download the most recent closing price for each ticker.
    Returns a dict mapping ticker → price (in the instrument's native currency).
    Tickers with no data are omitted from the result.
    """
    if not tickers:
        return {}

    end   = date.today()
    start = end - timedelta(days=10)   # small window to get the last close

    try:
        raw = yf.download(
            tickers,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
        )
    except Exception:
        return {}

    if raw.empty:
        return {}

    if isinstance(raw.columns, pd.MultiIndex):
        prices_df = raw["Close"]
    else:
        # Single ticker — flat columns
        prices_df = raw[["Close"]].rename(columns={"Close": tickers[0]})

    result: dict[str, float] = {}
    for t in tickers:
        if t in prices_df.columns:
            series = prices_df[t].dropna()
            if not series.empty:
                result[t] = float(series.iloc[-1])

    return result


# ── Trade plan ─────────────────────────────────────────────────────────────────

def compute_trade_plan(
    capital: float,
    weights: dict[str, float],
    latest_prices: dict[str, float],
    target_ccy: str = "DKK",
) -> tuple[pd.DataFrame, float, str]:
    """
    Convert a capital amount and portfolio weights into a concrete buy order list.

    Assumes whole-share purchases only (fractional shares not supported).

    Args:
        capital:       Total investment amount in target_ccy.
        weights:       Dict of ticker → weight (must sum to ≈ 1.0).
        latest_prices: Dict of ticker → price in the instrument's native currency.
        target_ccy:    Currency of the capital input (default "DKK").

    Returns:
        (trade_df, leftover, log_entry)
        - trade_df:  DataFrame with one row per ticker.
        - leftover:  Cash not deployed (due to whole-share constraint), in target_ccy.
        - log_entry: Log string written to execution_log.jsonl.
    """
    rows: list[dict] = []
    total_invested = 0.0

    for ticker, weight in weights.items():
        price_native = latest_prices.get(ticker)
        if not price_native:
            continue

        inst_ccy  = detect_currency(ticker)
        fx_rate   = get_fx_rate(inst_ccy, target_ccy)
        price_tgt = price_native * fx_rate     # price in target currency

        allocation  = capital * weight         # target_ccy
        shares      = int(allocation / price_tgt) if price_tgt > 0 else 0
        cost        = shares * price_tgt
        unused      = allocation - cost

        total_invested += cost

        fx_display = f"{fx_rate:.4f}" if inst_ccy != target_ccy else "—"
        rows.append({
            "Ticker":               ticker,
            "Weight":               f"{weight * 100:.1f}%",
            f"Allocation ({target_ccy})":  round(allocation, 2),
            f"Price ({inst_ccy})":  round(price_native, 2),
            f"FX → {target_ccy}":  fx_display,
            f"Price ({target_ccy})": round(price_tgt, 2),
            "Shares to Buy":        shares,
            f"Est. Cost ({target_ccy})":  round(cost, 2),
            f"Unused ({target_ccy})":     round(unused, 2),
        })

    leftover = round(capital - total_invested, 2)
    df = pd.DataFrame(rows)

    log_entry = _log("trade_plan", {
        "capital": capital,
        "currency": target_ccy,
        "trades": [
            {"ticker": r["Ticker"], "shares": r["Shares to Buy"]}
            for r in rows
        ],
        "total_invested": round(total_invested, 2),
        "leftover": leftover,
    })

    return df, leftover, log_entry


# ── Rebalancing plan ───────────────────────────────────────────────────────────

def compute_rebalance_plan(
    current_shares: dict[str, float],
    target_weights: dict[str, float],
    latest_prices: dict[str, float],
    threshold_pct: float = 5.0,
    target_ccy: str = "DKK",
) -> tuple[pd.DataFrame, str]:
    """
    Compare current holdings to target weights and generate rebalancing trades.

    Trades are only suggested when portfolio drift exceeds threshold_pct.

    Args:
        current_shares:  Dict of ticker → number of shares currently held.
        target_weights:  Dict of ticker → target weight (should sum to ≈ 1.0).
        latest_prices:   Dict of ticker → latest price in native currency.
        threshold_pct:   Minimum absolute drift (% of portfolio) to trigger a trade.
        target_ccy:      Currency for value calculations.

    Returns:
        (rebalance_df, log_entry)
    """
    # Step 1 — compute current portfolio value
    current_values: dict[str, float] = {}
    for ticker, shares in current_shares.items():
        price_native = latest_prices.get(ticker, 0.0)
        inst_ccy     = detect_currency(ticker)
        fx_rate      = get_fx_rate(inst_ccy, target_ccy)
        current_values[ticker] = shares * price_native * fx_rate

    total_value = sum(current_values.values())
    if total_value <= 0:
        return pd.DataFrame(), _log("rebalance_plan", {"error": "zero portfolio value"})

    rows: list[dict] = []
    for ticker, weight in target_weights.items():
        current_val = current_values.get(ticker, 0.0)
        target_val  = total_value * weight
        delta_val   = target_val - current_val
        drift_pct   = (current_val - target_val) / total_value * 100

        price_native = latest_prices.get(ticker, 0.0)
        inst_ccy     = detect_currency(ticker)
        fx_rate      = get_fx_rate(inst_ccy, target_ccy)
        price_tgt    = price_native * fx_rate

        if abs(drift_pct) >= threshold_pct and price_tgt > 0:
            shares_delta = delta_val / price_tgt
            action       = "BUY" if delta_val > 0 else "SELL"
            shares_str   = f"{abs(shares_delta):.2f}"
        else:
            action     = "— (within band)"
            shares_str = "—"

        rows.append({
            "Ticker":                    ticker,
            "Target Weight":             f"{weight * 100:.1f}%",
            f"Current Value ({target_ccy})": round(current_val, 2),
            f"Target Value ({target_ccy})":  round(target_val, 2),
            "Drift":                     f"{drift_pct:+.1f}%",
            "Action":                    action,
            "Shares to Trade":           shares_str,
        })

    df = pd.DataFrame(rows)
    log_entry = _log("rebalance_plan", {
        "total_value": round(total_value, 2),
        "currency": target_ccy,
        "threshold_pct": threshold_pct,
        "trades": [
            {"ticker": r["Ticker"], "action": r["Action"], "shares": r["Shares to Trade"]}
            for r in rows if r["Action"] not in ("— (within band)",)
        ],
    })

    return df, log_entry
