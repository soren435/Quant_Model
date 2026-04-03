"""
Portfolio construction, rebalancing, and return attribution.

Core function `build_portfolio_returns` simulates a daily portfolio
with optional periodic rebalancing back to target weights.
"""
import pandas as pd
import numpy as np

from src.analytics.returns import total_return


def build_portfolio_returns(
    prices: pd.DataFrame,
    weights: dict[str, float],
    rebalance_freq: str = "monthly",
) -> pd.Series:
    """
    Build a daily portfolio return series with optional periodic rebalancing.

    Args:
        prices:         DataFrame with tickers as columns (adjusted close).
        weights:        Dict mapping ticker → target weight. Will be normalized.
        rebalance_freq: 'monthly', 'quarterly', or 'none' (buy-and-hold drift).

    Returns:
        Daily portfolio returns as a named Series indexed by date.
    """
    valid_tickers = [t for t in weights if t in prices.columns]
    if not valid_tickers:
        return pd.Series(dtype=float, name="Portfolio")

    w = np.array([weights[t] for t in valid_tickers], dtype=float)
    w = w / w.sum()

    prices_sub = prices[valid_tickers].ffill().dropna()
    returns = prices_sub.pct_change().dropna()

    if rebalance_freq == "none":
        return returns.dot(w).rename("Portfolio")

    freq_alias = {"monthly": "MS", "quarterly": "QS"}.get(rebalance_freq, "MS")
    rebalance_dates = set(returns.resample(freq_alias).first().index)

    current_weights = w.copy()
    port_returns: list[float] = []

    for date, row in returns.iterrows():
        if date in rebalance_dates:
            current_weights = w.copy()

        day_ret = float(np.dot(current_weights, row.values))
        port_returns.append(day_ret)

        new_vals = current_weights * (1.0 + row.values)
        total = new_vals.sum()
        if total > 0:
            current_weights = new_vals / total

    return pd.Series(port_returns, index=returns.index, name="Portfolio")


def correlation_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    """Pearson correlation matrix of daily returns across all columns."""
    return prices.pct_change().dropna().corr()


def weights_over_time(
    prices: pd.DataFrame,
    initial_weights: dict[str, float],
    rebalance_freq: str = "none",
) -> pd.DataFrame:
    """
    Track how portfolio weights drift over time (buy-and-hold drift vs rebalanced).

    Returns:
        DataFrame with tickers as columns and daily weight values as rows.
    """
    valid_tickers = [t for t in initial_weights if t in prices.columns]
    if not valid_tickers:
        return pd.DataFrame()

    w = np.array([initial_weights[t] for t in valid_tickers], dtype=float)
    w = w / w.sum()

    prices_sub = prices[valid_tickers].ffill().dropna()
    returns = prices_sub.pct_change().dropna()

    freq_alias = {"monthly": "MS", "quarterly": "QS"}.get(rebalance_freq, "MS")
    rebalance_dates: set = set()
    if rebalance_freq != "none":
        rebalance_dates = set(returns.resample(freq_alias).first().index)

    current_weights = w.copy()
    history: list[np.ndarray] = []

    for date, row in returns.iterrows():
        if date in rebalance_dates:
            current_weights = w.copy()
        history.append(current_weights.copy())
        new_vals = current_weights * (1.0 + row.values)
        total = new_vals.sum()
        if total > 0:
            current_weights = new_vals / total

    return pd.DataFrame(history, index=returns.index, columns=valid_tickers)


def contribution_to_return(
    prices: pd.DataFrame,
    weights: dict[str, float],
) -> dict[str, float]:
    """
    Simple return attribution: each asset's contribution = initial_weight × asset_total_return.

    This is an approximation (ignores compounding across assets) but is intuitive
    and appropriate for exploratory analysis.

    Returns:
        Dict mapping ticker → return contribution (e.g. 0.04 = 4 percentage points).
    """
    result: dict[str, float] = {}
    for ticker, w in weights.items():
        if ticker in prices.columns:
            asset_ret = prices[ticker].pct_change().dropna()
            if not asset_ret.empty:
                result[ticker] = w * total_return(asset_ret)
    return result
