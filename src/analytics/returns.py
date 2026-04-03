"""
Return calculations — pure functions, no Streamlit dependency.
Inputs are pandas Series/DataFrames of daily returns or prices unless stated otherwise.
"""
import pandas as pd
import numpy as np

TRADING_DAYS = 252  # standard annualisation assumption


# ── Core return functions ──────────────────────────────────────────────────────

def daily_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Daily percentage returns from a price series or DataFrame."""
    return prices.pct_change().dropna()


def cumulative_returns_series(
    returns: pd.Series | pd.DataFrame,
) -> pd.Series | pd.DataFrame:
    """
    Cumulative return index starting at 1.0.
    A value of 1.25 means the investment grew 25% from inception.
    """
    return (1 + returns).cumprod()


def total_return(returns: pd.Series) -> float:
    """Total compounded return over the full period."""
    if returns.empty:
        return 0.0
    return float((1 + returns).prod() - 1)


def annualized_return(
    returns: pd.Series,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """
    Annualized geometric return (CAGR).
    Uses compounded growth; assumes daily returns as input.
    """
    if returns.empty or len(returns) < 2:
        return 0.0
    n_years = len(returns) / periods_per_year
    compounded = float((1 + returns).prod())
    if compounded <= 0:
        return -1.0
    return float(compounded ** (1.0 / n_years) - 1)


# ── Period returns (require price series, not daily returns) ──────────────────

def period_return(prices: pd.Series, days: int) -> float:
    """
    Return over the last N trading days.
    Falls back to full period if fewer observations are available.

    Args:
        prices: Adjusted close price series.
        days:   Number of trailing trading days (e.g. 21 for 1M, 63 for 3M).
    """
    prices = prices.dropna()
    if prices.empty:
        return 0.0
    if len(prices) <= days:
        return float(prices.iloc[-1] / prices.iloc[0] - 1)
    return float(prices.iloc[-1] / prices.iloc[-(days + 1)] - 1)


def ytd_return(prices: pd.Series) -> float:
    """
    Year-to-date return: from January 1 of the last observation's year.
    Returns 0.0 if fewer than 2 observations exist after the year boundary.
    """
    prices = prices.dropna()
    if prices.empty:
        return 0.0
    year_start = pd.Timestamp(prices.index[-1].year, 1, 1)
    ytd = prices[prices.index >= year_start]
    if len(ytd) < 2:
        return 0.0
    return float(ytd.iloc[-1] / ytd.iloc[0] - 1)


# ── Rolling metrics ────────────────────────────────────────────────────────────

def rolling_return(
    returns: pd.Series,
    window: int = TRADING_DAYS,
    periods_per_year: int = TRADING_DAYS,
) -> pd.Series:
    """Rolling annualized return over a given window of daily returns."""
    return returns.rolling(window).apply(
        lambda x: (1 + x).prod() ** (periods_per_year / len(x)) - 1,
        raw=True,
    )
