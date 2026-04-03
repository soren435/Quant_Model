"""
Risk calculations — pure functions, no Streamlit dependency.
All functions expect daily return Series as input unless stated otherwise.
"""
import pandas as pd
import numpy as np

from src.analytics.returns import total_return, annualized_return, TRADING_DAYS


# ── Volatility ─────────────────────────────────────────────────────────────────

def annualized_volatility(
    returns: pd.Series,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """Annualized standard deviation of daily returns."""
    if returns.empty or len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(periods_per_year))


def rolling_volatility(
    returns: pd.Series,
    window: int = 21,
    periods_per_year: int = TRADING_DAYS,
) -> pd.Series:
    """Rolling annualized volatility. Default window = 21 trading days (~1 month)."""
    return returns.rolling(window).std() * np.sqrt(periods_per_year)


# ── Risk-adjusted return ratios ────────────────────────────────────────────────

def sharpe_ratio(
    returns: pd.Series,
    rf_annual: float = 0.04,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """
    Annualized Sharpe ratio.
    The risk-free rate is converted from annual to daily before computing excess returns.
    """
    if returns.empty or len(returns) < 2:
        return 0.0
    rf_daily = (1 + rf_annual) ** (1.0 / periods_per_year) - 1
    excess = returns - rf_daily
    vol = annualized_volatility(returns, periods_per_year)
    if vol == 0:
        return 0.0
    return float(excess.mean() * periods_per_year / vol)


def sortino_ratio(
    returns: pd.Series,
    rf_annual: float = 0.04,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """
    Sortino ratio using downside deviation below the risk-free rate.
    Penalizes only negative excess returns rather than all volatility.
    """
    if returns.empty or len(returns) < 10:
        return 0.0
    rf_daily = (1 + rf_annual) ** (1.0 / periods_per_year) - 1
    excess = returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) < 2:
        return 0.0
    downside_vol = float(downside.std() * np.sqrt(periods_per_year))
    if downside_vol == 0:
        return 0.0
    ann_excess = annualized_return(excess, periods_per_year)
    return float(ann_excess / downside_vol)


def calmar_ratio(returns: pd.Series) -> float:
    """Calmar ratio: annualized return divided by absolute max drawdown."""
    ann_ret = annualized_return(returns)
    mdd = max_drawdown(returns)
    if mdd == 0:
        return 0.0
    return float(ann_ret / abs(mdd))


# ── Drawdown ───────────────────────────────────────────────────────────────────

def max_drawdown(returns: pd.Series) -> float:
    """
    Maximum peak-to-trough drawdown as a negative fraction.
    E.g. -0.35 means the portfolio fell 35% from its peak.
    """
    if returns.empty:
        return 0.0
    cum = (1 + returns).cumprod()
    return float((cum / cum.cummax() - 1).min())


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Time series of current drawdown from peak (negative values, e.g. -0.12 = -12%)."""
    if returns.empty:
        return pd.Series(dtype=float)
    cum = (1 + returns).cumprod()
    return (cum / cum.cummax() - 1).rename("Drawdown")


# ── Benchmark-relative metrics ─────────────────────────────────────────────────

def beta(returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """
    Market beta: sensitivity of the portfolio to the benchmark's daily moves.
    Beta > 1 means more volatile than benchmark; < 1 means more defensive.
    """
    combined = pd.concat([returns, benchmark_returns], axis=1).dropna()
    if len(combined) < 10:
        return float("nan")
    cov_matrix = combined.cov()
    bench_var = float(combined.iloc[:, 1].var())
    if bench_var == 0:
        return float("nan")
    return float(cov_matrix.iloc[0, 1] / bench_var)


def tracking_error(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """
    Annualized tracking error: standard deviation of active (portfolio minus benchmark) returns.
    Lower values indicate the portfolio tracks the benchmark more closely.
    """
    combined = pd.concat([returns, benchmark_returns], axis=1).dropna()
    if len(combined) < 2:
        return float("nan")
    active = combined.iloc[:, 0] - combined.iloc[:, 1]
    return float(active.std() * np.sqrt(periods_per_year))


def information_ratio(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """
    Information ratio: annualized active return divided by tracking error.
    Measures consistency of outperformance relative to the benchmark.
    """
    combined = pd.concat([returns, benchmark_returns], axis=1).dropna()
    if len(combined) < 10:
        return float("nan")
    active = combined.iloc[:, 0] - combined.iloc[:, 1]
    te = float(active.std() * np.sqrt(periods_per_year))
    if te == 0:
        return float("nan")
    ann_active = float(active.mean() * periods_per_year)
    return float(ann_active / te)


# ── Summary ────────────────────────────────────────────────────────────────────

def summary_stats(returns: pd.Series, rf_annual: float = 0.04) -> dict:
    """
    Compute all standard performance statistics in a single call.
    Returns a dict suitable for st.metric() or a summary DataFrame.
    """
    returns = returns.dropna()
    if returns.empty or len(returns) < 5:
        return {}

    return {
        "Cumulative Return": total_return(returns),
        "Annualized Return": annualized_return(returns),
        "Annualized Volatility": annualized_volatility(returns),
        "Sharpe Ratio": sharpe_ratio(returns, rf_annual),
        "Sortino Ratio": sortino_ratio(returns, rf_annual),
        "Max Drawdown": max_drawdown(returns),
        "Calmar Ratio": calmar_ratio(returns),
        "Num Years": round(len(returns) / TRADING_DAYS, 1),
    }
