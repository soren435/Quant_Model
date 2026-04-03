"""
Engine 1 — Historical Strategy Model.
Pure analytics; no Streamlit dependency.

Strategies:
- cross_sectional_momentum : monthly rank-based momentum (Jegadeesh & Titman)
- dual_momentum            : Antonacci absolute + relative momentum
- inverse_volatility       : 1/σ weighted, rebalanced monthly
- run_historical_engines   : convenience wrapper returning all strategies
"""
from __future__ import annotations
import pandas as pd
import numpy as np

from src.analytics.returns import cumulative_returns_series
from src.analytics.risk import summary_stats


# ── Cross-sectional momentum ───────────────────────────────────────────────────

def cross_sectional_momentum(
    prices: pd.DataFrame,
    lookback_months: int = 12,
    skip_months: int = 1,
    top_n: int = 3,
    rf_annual: float = 0.04,
) -> dict:
    """
    Each month rank assets by trailing lookback_months return (skipping
    skip_months to avoid the short-term reversal anomaly). Go equal-weight
    long in the top_n performers. Rebalance monthly.

    Args:
        prices:          Daily OHLCV close prices, tickers as columns.
        lookback_months: Formation period in months.
        skip_months:     Months to skip before lookback (typically 1).
        top_n:           Number of assets to hold each month.
        rf_annual:       Annual risk-free rate for stats.

    Returns:
        dict with keys 'returns', 'cumulative', 'stats' — or {} on failure.
    """
    monthly = prices.resample("ME").last()
    lookback_ret = (
        monthly.shift(skip_months) / monthly.shift(lookback_months + skip_months) - 1
    )
    daily_returns = prices.pct_change().dropna()
    months = monthly.index

    port_returns: list[float] = []
    dates: list = []

    for i, month_end in enumerate(months[:-1]):
        next_month_end = months[i + 1]
        if month_end not in lookback_ret.index:
            continue

        signal = lookback_ret.loc[month_end].dropna().sort_values(ascending=False)
        if signal.empty:
            continue

        k = min(top_n, len(signal))
        top_assets = [t for t in signal.index[:k] if t in daily_returns.columns]
        if not top_assets:
            continue

        mask = (daily_returns.index > month_end) & (daily_returns.index <= next_month_end)
        period = daily_returns.loc[mask, top_assets]
        if period.empty:
            continue

        port_returns.extend(period.mean(axis=1).tolist())
        dates.extend(period.index.tolist())

    if not dates:
        return {}

    ret = pd.Series(port_returns, index=pd.DatetimeIndex(dates), name="XS Momentum")
    return {
        "returns": ret,
        "cumulative": cumulative_returns_series(ret),
        "stats": summary_stats(ret, rf_annual),
    }


# ── Dual momentum (Antonacci) ─────────────────────────────────────────────────

def dual_momentum(
    prices: pd.DataFrame,
    risky: str = "SPY",
    safe: str = "AGG",
    cash: str = "SHY",
    lookback_months: int = 12,
    rf_annual: float = 0.04,
) -> dict:
    """
    Gary Antonacci's Dual Momentum (2014).

    Each month:
      1. Absolute momentum: is risky > cash over lookback_months?
      2. Relative momentum: is risky > safe?

    Decision:
      risky > cash AND risky > safe  →  hold risky
      risky > cash AND safe > risky  →  hold safe
      cash > risky                   →  hold cash (defensive)

    Args:
        prices:          Daily close prices. Must contain at minimum risky + one of {safe, cash}.
        risky:           Ticker for risky (growth) asset.
        safe:            Ticker for safe-haven alternative (e.g. bonds).
        cash:            Ticker for cash / very short duration.
        lookback_months: Formation period in months.
        rf_annual:       Annual risk-free rate.

    Returns:
        dict with keys 'returns', 'cumulative', 'stats' — or {} on failure.
    """
    available = [t for t in [risky, safe, cash] if t in prices.columns]
    if risky not in available:
        return {}

    sub = prices[available].ffill()
    monthly = sub.resample("ME").last()
    lookback_ret = monthly / monthly.shift(lookback_months) - 1
    daily_returns = sub.pct_change().dropna()
    months = monthly.index

    port_returns: list[float] = []
    dates: list = []

    for i in range(lookback_months, len(months) - 1):
        month_end = months[i]
        next_month_end = months[i + 1]

        if month_end not in lookback_ret.index:
            continue

        row = lookback_ret.loc[month_end]
        r_ret = float(row.get(risky, float("nan")))
        s_ret = float(row.get(safe, float("nan")))
        c_ret = float(row.get(cash, 0.0))

        if r_ret > c_ret and r_ret > s_ret:
            hold = risky
        elif r_ret > c_ret:
            hold = safe if safe in available else cash
        else:
            hold = cash if cash in available else safe

        if hold not in daily_returns.columns:
            continue

        mask = (daily_returns.index > month_end) & (daily_returns.index <= next_month_end)
        period = daily_returns.loc[mask]
        if period.empty:
            continue

        port_returns.extend(period[hold].tolist())
        dates.extend(period.index.tolist())

    if not dates:
        return {}

    ret = pd.Series(port_returns, index=pd.DatetimeIndex(dates), name="Dual Momentum")
    return {
        "returns": ret,
        "cumulative": cumulative_returns_series(ret),
        "stats": summary_stats(ret, rf_annual),
    }


# ── Inverse-volatility weighting ──────────────────────────────────────────────

def inverse_volatility(
    prices: pd.DataFrame,
    vol_lookback_days: int = 63,
    rebalance_freq: str = "monthly",
    rf_annual: float = 0.04,
) -> dict:
    """
    Inverse-volatility weighted portfolio.

    Each rebalance period: compute trailing volatility per asset, assign weight
    proportional to 1/σ. Lower-volatility assets receive higher allocation.
    Drift-adjusted between rebalances (no daily rebalancing cost).

    Args:
        prices:            Daily close prices.
        vol_lookback_days: Look-back window to estimate volatility (e.g. 63 ≈ 3 months).
        rebalance_freq:    'monthly' | 'quarterly'.
        rf_annual:         Annual risk-free rate.

    Returns:
        dict with keys 'returns', 'cumulative', 'stats'.
    """
    tickers = list(prices.columns)
    n = len(tickers)
    daily_returns = prices[tickers].pct_change().dropna()
    freq_alias = {"monthly": "MS", "quarterly": "QS"}.get(rebalance_freq, "MS")
    rebalance_dates = set(daily_returns.resample(freq_alias).first().index)

    current_weights = np.full(n, 1.0 / n)
    port_returns: list[float] = []

    for idx, (date, row) in enumerate(daily_returns.iterrows()):
        if date in rebalance_dates and idx >= vol_lookback_days:
            trailing = daily_returns.iloc[max(0, idx - vol_lookback_days):idx]
            if len(trailing) >= 20:
                vols = trailing.std().replace(0, np.nan)
                inv_vol = (1.0 / vols).fillna(0)
                total = inv_vol.sum()
                if total > 0:
                    current_weights = inv_vol.reindex(tickers).fillna(0).values / total

        day_ret = float(np.dot(current_weights, row.values))
        port_returns.append(day_ret)

        new_vals = current_weights * (1.0 + row.values)
        total = new_vals.sum()
        if total > 0:
            current_weights = new_vals / total

    ret = pd.Series(port_returns, index=daily_returns.index, name="Inverse Vol")
    return {
        "returns": ret,
        "cumulative": cumulative_returns_series(ret),
        "stats": summary_stats(ret, rf_annual),
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def run_historical_engines(
    prices: pd.DataFrame,
    rf_annual: float = 0.04,
    lookback_months: int = 12,
    top_n: int = 3,
    risky: str = "SPY",
    safe: str = "AGG",
    cash: str = "SHY",
) -> dict[str, dict]:
    """
    Run all historical strategy engines and return unified results.

    Returns:
        Dict keyed by strategy name. Each value has 'returns', 'cumulative', 'stats'.
    """
    from src.analytics.backtest import run_strategies

    results: dict[str, dict] = {}

    xs = cross_sectional_momentum(
        prices, lookback_months=lookback_months, top_n=top_n, rf_annual=rf_annual
    )
    if xs:
        results["XS Momentum"] = xs

    dm = dual_momentum(
        prices, risky=risky, safe=safe, cash=cash,
        lookback_months=lookback_months, rf_annual=rf_annual,
    )
    if dm:
        results["Dual Momentum"] = dm

    if len(prices.columns) >= 2:
        iv = inverse_volatility(prices, rf_annual=rf_annual)
        if iv:
            results["Inverse Vol"] = iv

    # Equal-weight as benchmark
    n = len(prices.columns)
    ew_w = {t: 1.0 / n for t in prices.columns}
    ew = run_strategies(prices, {"Equal Weight": ew_w}, rf_annual=rf_annual)
    if ew and not ew.get("returns", pd.DataFrame()).empty:
        col = "Equal Weight"
        if col in ew["returns"].columns:
            results["Equal Weight"] = {
                "returns":    ew["returns"][col],
                "cumulative": ew["cumulative"][col],
                "stats":      ew["stats"][col],
            }

    return results


# ── Walk-forward validation ───────────────────────────────────────────────────

def walk_forward_validation(
    prices: pd.DataFrame,
    split_date: str,
    rf_annual: float = 0.04,
    lookback_months: int = 12,
    top_n: int = 3,
    risky: str = "SPY",
    safe: str = "AGG",
    cash: str = "SHY",
) -> dict:
    """
    Split the price history at split_date and run all strategies on both halves.

    The in-sample period (before split_date) represents the "training" window —
    the period a researcher would have used to discover and calibrate the strategy.
    The out-of-sample period (from split_date onward) is the honest test: how did
    the strategy perform on data it never saw?

    A strategy is considered robust if its out-of-sample Sharpe is meaningfully
    positive, even if lower than in-sample (some decay is expected and normal).
    A strategy whose OOS Sharpe collapses to near zero or negative is likely
    over-fitted to the training period.

    Args:
        prices:          Full price history DataFrame.
        split_date:      ISO date string 'YYYY-MM-DD' separating train / test.
        rf_annual:       Annual risk-free rate.
        lookback_months: Momentum lookback window (applied identically in both periods).
        top_n:           Top-N assets for XS Momentum.
        risky/safe/cash: Dual Momentum asset tickers.

    Returns:
        Dict with keys:
          'in_sample'      → {strategy: {returns, cumulative, stats}}
          'out_of_sample'  → {strategy: {returns, cumulative, stats}}
          'split_date'     → the split date string
          'is_months'      → approximate in-sample length in months
          'oos_months'     → approximate out-of-sample length in months
    """
    prices_is  = prices.loc[:split_date]
    prices_oos = prices.loc[split_date:]

    is_results  = run_historical_engines(prices_is,  rf_annual, lookback_months, top_n, risky, safe, cash)
    oos_results = run_historical_engines(prices_oos, rf_annual, lookback_months, top_n, risky, safe, cash)

    is_months  = max(0, round(len(prices_is)  / 21))
    oos_months = max(0, round(len(prices_oos) / 21))

    return {
        "in_sample":     is_results,
        "out_of_sample": oos_results,
        "split_date":    split_date,
        "is_months":     is_months,
        "oos_months":    oos_months,
    }
