"""
Data ingestion — Yahoo Finance via yfinance.
Results are cached in Streamlit for 1 hour to avoid redundant network calls.
"""
import pandas as pd
import yfinance as yf
import streamlit as st


@st.cache_data(ttl=3600, show_spinner=False)
def download_prices(tickers: tuple[str, ...], start: str, end: str) -> pd.DataFrame:
    """
    Download adjusted close prices from Yahoo Finance.

    Args:
        tickers: Tuple of ticker symbols (tuple, not list, for Streamlit cache compatibility).
        start:   Start date string 'YYYY-MM-DD'.
        end:     End date string 'YYYY-MM-DD'.

    Returns:
        DataFrame with tickers as columns and dates as index.
        Columns with no data at all are silently dropped.
    """
    if not tickers:
        return pd.DataFrame()

    tickers_list = list(tickers)

    try:
        raw = yf.download(
            tickers_list,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        st.error(f"Download failed: {exc}")
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    # yfinance returns a MultiIndex for multiple tickers, flat for a single ticker.
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
        if len(tickers_list) == 1 and isinstance(prices, pd.Series):
            prices = prices.to_frame(name=tickers_list[0])
    else:
        prices = raw[["Close"]].rename(columns={"Close": tickers_list[0]})

    # Forward-fill minor gaps (weekends, public holidays), drop fully empty rows
    prices = prices.ffill().dropna(how="all")

    # Drop columns that are entirely NaN (invalid tickers)
    prices = prices.dropna(axis=1, how="all")

    return prices


def get_available_tickers(tickers: list[str], start: str, end: str) -> list[str]:
    """Return only those tickers that have price data in the given period."""
    prices = download_prices(tuple(tickers), start, end)
    return list(prices.columns)
