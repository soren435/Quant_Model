"""
Strategy backtesting.

Supports:
- Multiple buy-and-hold / fixed-allocation strategies via `run_strategies`
- A simple risk-on/risk-off trend filter via `trend_filter_returns`
"""
import pandas as pd
import numpy as np

from src.analytics.portfolio import build_portfolio_returns
from src.analytics.returns import cumulative_returns_series
from src.analytics.risk import summary_stats


def run_strategies(
    prices: pd.DataFrame,
    strategies: dict[str, dict[str, float]],
    rebalance_freq: str = "monthly",
    rf_annual: float = 0.04,
) -> dict:
    """
    Run a set of named allocation strategies and collect performance results.

    Args:
        prices:         Price DataFrame with all required tickers as columns.
        strategies:     Dict of {strategy_name: {ticker: weight}}.
        rebalance_freq: Applied uniformly to all strategies.
        rf_annual:      Annual risk-free rate for Sharpe calculation.

    Returns:
        Dict with keys:
          'returns'    → aligned DataFrame of daily returns (one column per strategy)
          'cumulative' → cumulative value index (1.0 = start)
          'stats'      → dict of summary stats per strategy
    """
    returns_dict: dict[str, pd.Series] = {}

    for name, weights in strategies.items():
        port_ret = build_portfolio_returns(prices, weights, rebalance_freq)
        if not port_ret.empty:
            returns_dict[name] = port_ret

    if not returns_dict:
        return {}

    all_returns = pd.DataFrame(returns_dict).dropna()
    cumulative = cumulative_returns_series(all_returns)

    stats = {
        col: summary_stats(all_returns[col], rf_annual)
        for col in all_returns.columns
    }

    return {
        "returns": all_returns,
        "cumulative": cumulative,
        "stats": stats,
    }


def trend_filter_returns(
    prices: pd.DataFrame,
    equity_ticker: str,
    bond_ticker: str,
    risk_ticker: str,
    ma_window: int = 200,
    equity_weight: float = 0.6,
    bond_weight: float = 0.4,
) -> pd.Series:
    """
    Risk-on / risk-off strategy driven by a moving-average crossover signal.

    Logic:
        Risk-on  (price > MA):  hold equity_weight / bond_weight split.
        Risk-off (price ≤ MA):  rotate fully into bonds (0% equity).

    Args:
        prices:        Price DataFrame.
        equity_ticker: Equity ETF used when risk-on.
        bond_ticker:   Bond ETF used as safe haven.
        risk_ticker:   Ticker whose price vs MA determines the regime signal.
        ma_window:     Look-back window for the moving average (days).
        equity_weight: Target equity weight during risk-on.
        bond_weight:   Target bond weight during risk-on.

    Returns:
        Daily portfolio return Series.
    """
    name = f"Trend Filter ({ma_window}MA)"
    required = list({equity_ticker, bond_ticker, risk_ticker})
    available = [t for t in required if t in prices.columns]

    if equity_ticker not in available or bond_ticker not in available:
        return pd.Series(dtype=float, name=name)

    prices_sub = prices[available].ffill().dropna()
    ma = prices_sub[risk_ticker].rolling(ma_window).mean()
    risk_on = prices_sub[risk_ticker] > ma

    returns = prices_sub.pct_change().dropna()
    risk_on = risk_on.reindex(returns.index)

    total_w = equity_weight + bond_weight
    eq_w = equity_weight / total_w
    bd_w = bond_weight / total_w

    port_returns: list[float] = []
    for date, row in returns.iterrows():
        eq_ret = float(row.get(equity_ticker, 0.0))
        bond_ret = float(row.get(bond_ticker, 0.0))

        if risk_on.get(date, False):
            port_ret = eq_w * eq_ret + bd_w * bond_ret
        else:
            port_ret = bond_ret

        port_returns.append(port_ret)

    return pd.Series(port_returns, index=returns.index, name=name)
