"""
Engine 4 — Investor Profile / Risk Model.
Maps a questionnaire-based risk score to a target portfolio allocation,
then backtests it over the selected historical window.

Risk score scale: 1 (most conservative) → 10 (most aggressive).
Five named profiles: Conservative / Moderate / Balanced / Growth / Aggressive.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from src.analytics.portfolio import build_portfolio_returns
from src.analytics.returns import cumulative_returns_series, TRADING_DAYS
from src.analytics.risk import summary_stats


# ── Profile definitions ───────────────────────────────────────────────────────

@dataclass
class InvestorProfile:
    risk_score:             int
    label:                  str
    target_allocation:      dict[str, float]
    description:            str
    max_drawdown_tolerance: float     # e.g. -0.15 means "I can accept 15% loss"
    time_horizon_years:     int = 10
    score_range:            tuple[int, int] = field(default=(1, 10), repr=False)


# Target allocations use the same ETF universe as the rest of the platform
PROFILE_TEMPLATES: list[InvestorProfile] = [
    InvestorProfile(
        risk_score=2,
        label="Conservative",
        score_range=(1, 3),
        target_allocation={"TLT": 0.35, "IEF": 0.25, "AGG": 0.20, "GLD": 0.10, "SPY": 0.10},
        description=(
            "Capital preservation above all else. "
            "Primarily long-duration bonds with a small equity sleeve. "
            "Suitable for short horizons or near-retirement investors."
        ),
        max_drawdown_tolerance=-0.10,
    ),
    InvestorProfile(
        risk_score=5,
        label="Moderate",
        score_range=(4, 5),
        target_allocation={"SPY": 0.30, "IEF": 0.30, "AGG": 0.15, "GLD": 0.10, "QQQ": 0.10, "SHY": 0.05},
        description=(
            "Balanced between growth and income. "
            "Equal split between equities and fixed income. "
            "Suitable for medium-horizon investors with moderate loss tolerance."
        ),
        max_drawdown_tolerance=-0.20,
    ),
    InvestorProfile(
        risk_score=6,
        label="Balanced",
        score_range=(6, 6),
        target_allocation={"SPY": 0.45, "QQQ": 0.10, "IEF": 0.25, "GLD": 0.10, "DJP": 0.10},
        description=(
            "Growth-tilted with meaningful bond buffer. "
            "60/40-style with diversification into real assets. "
            "Classic long-term allocation for most investors."
        ),
        max_drawdown_tolerance=-0.25,
    ),
    InvestorProfile(
        risk_score=8,
        label="Growth",
        score_range=(7, 8),
        target_allocation={"SPY": 0.50, "QQQ": 0.20, "IEF": 0.15, "GLD": 0.10, "DJP": 0.05},
        description=(
            "Equity-dominant portfolio with small defensive buffer. "
            "Accepts significant drawdowns in exchange for long-term capital growth. "
            "Suitable for long-horizon investors with stable income."
        ),
        max_drawdown_tolerance=-0.35,
    ),
    InvestorProfile(
        risk_score=10,
        label="Aggressive",
        score_range=(9, 10),
        target_allocation={"SPY": 0.50, "QQQ": 0.35, "GLD": 0.05, "DJP": 0.10},
        description=(
            "Maximum equity concentration. "
            "Minimal diversification — targeting highest long-run CAGR. "
            "Suitable only for investors with very high risk tolerance and long horizons."
        ),
        max_drawdown_tolerance=-0.50,
    ),
]


# ── Questionnaire scoring ─────────────────────────────────────────────────────

def score_questionnaire(
    time_horizon_years: int,
    loss_tolerance_pct: int,
    income_need: str,
    experience: str,
    primary_goal: str,
) -> int:
    """
    Compute a risk score from 1-10 based on questionnaire inputs.

    Args:
        time_horizon_years: Investment horizon in years.
        loss_tolerance_pct: Maximum acceptable portfolio loss in percent (e.g. 20 = "-20%").
        income_need:        How much income the portfolio must generate: 'none'|'low'|'medium'|'high'.
        experience:         Investor experience level: 'beginner'|'intermediate'|'advanced'.
        primary_goal:       'preserve'|'income'|'balanced'|'grow'|'aggressive'.

    Returns:
        Integer risk score from 1 (conservative) to 10 (aggressive).
    """
    score = 0.0

    # Time horizon: 0–3 pts (longer horizon = higher score)
    if time_horizon_years >= 20:
        score += 3.0
    elif time_horizon_years >= 10:
        score += 2.5
    elif time_horizon_years >= 5:
        score += 2.0
    elif time_horizon_years >= 3:
        score += 1.0
    else:
        score += 0.0

    # Loss tolerance: 0–3 pts
    if loss_tolerance_pct >= 50:
        score += 3.0
    elif loss_tolerance_pct >= 30:
        score += 2.5
    elif loss_tolerance_pct >= 20:
        score += 2.0
    elif loss_tolerance_pct >= 10:
        score += 1.0
    else:
        score += 0.0

    # Income need: 0–2 pts (high income need → conservative → low score)
    score += {"none": 2.0, "low": 1.5, "medium": 1.0, "high": 0.0}.get(income_need, 1.0)

    # Experience: 0–1 pt
    score += {"beginner": 0.0, "intermediate": 0.5, "advanced": 1.0}.get(experience, 0.5)

    # Primary goal: 0–1 pt
    score += {
        "preserve":   0.0,
        "income":     0.25,
        "balanced":   0.5,
        "grow":       0.75,
        "aggressive": 1.0,
    }.get(primary_goal, 0.5)

    return max(1, min(10, round(score)))


# ── Profile lookup ────────────────────────────────────────────────────────────

def profile_from_score(risk_score: int, time_horizon_years: int = 10) -> InvestorProfile:
    """
    Return the InvestorProfile whose score_range contains risk_score.
    Falls back to 'Balanced' for any unmatched score.
    """
    for p in PROFILE_TEMPLATES:
        low, high = p.score_range
        if low <= risk_score <= high:
            return InvestorProfile(
                risk_score=risk_score,
                label=p.label,
                target_allocation=p.target_allocation.copy(),
                description=p.description,
                max_drawdown_tolerance=p.max_drawdown_tolerance,
                time_horizon_years=time_horizon_years,
                score_range=p.score_range,
            )
    # Default
    fallback = PROFILE_TEMPLATES[2]  # Balanced
    return InvestorProfile(
        risk_score=risk_score,
        label=fallback.label,
        target_allocation=fallback.target_allocation.copy(),
        description=fallback.description,
        max_drawdown_tolerance=fallback.max_drawdown_tolerance,
        time_horizon_years=time_horizon_years,
    )


def all_profile_labels() -> list[str]:
    return [p.label for p in PROFILE_TEMPLATES]


# ── Backtest ──────────────────────────────────────────────────────────────────

def backtest_profile_allocation(
    prices: pd.DataFrame,
    profile: InvestorProfile,
    rf_annual: float = 0.04,
) -> dict:
    """
    Backtest the investor profile's target allocation over the available price history.
    Rebalances monthly to target weights.

    Returns:
        dict with 'returns', 'cumulative', 'stats', 'allocation' — or {} on failure.
    """
    available = {t: w for t, w in profile.target_allocation.items() if t in prices.columns}
    if not available:
        return {}

    total = sum(available.values())
    alloc = {t: w / total for t, w in available.items()}

    ret = build_portfolio_returns(prices, alloc, rebalance_freq="monthly")
    ret.name = f"{profile.label} Portfolio"

    return {
        "returns":    ret,
        "cumulative": cumulative_returns_series(ret),
        "stats":      summary_stats(ret, rf_annual),
        "allocation": alloc,
    }


def compare_all_profiles(
    prices: pd.DataFrame,
    rf_annual: float = 0.04,
) -> dict[str, dict]:
    """
    Backtest all five profile allocations and return results keyed by label.
    Useful for the comparison chart in the UI.
    """
    results: dict[str, dict] = {}
    for template in PROFILE_TEMPLATES:
        res = backtest_profile_allocation(prices, template, rf_annual)
        if res:
            results[template.label] = res
    return results


# ── Efficient Frontier (Mean-Variance Optimisation) ───────────────────────────

def efficient_frontier(
    prices: pd.DataFrame,
    rf_annual: float = 0.04,
    n_portfolios: int = 300,
    target_vol: float | None = None,
) -> dict:
    """
    Compute the efficient frontier using mean-variance optimisation.

    Samples `n_portfolios` random portfolios, then finds:
      - Minimum variance portfolio
      - Maximum Sharpe portfolio
      - (Optional) Minimum variance portfolio at or below `target_vol`

    All weights are long-only and sum to 1.

    Args:
        prices:       Daily close prices, tickers as columns.
        rf_annual:    Annual risk-free rate (for Sharpe calculation).
        n_portfolios: Number of random portfolios to sample for the frontier.
        target_vol:   If set, also find the max-Sharpe portfolio with ann. vol ≤ target_vol.

    Returns:
        dict with keys:
          'frontier'        → DataFrame(vol, ret, sharpe, weights...)
          'max_sharpe'      → dict(weights, vol, ret, sharpe)
          'min_vol'         → dict(weights, vol, ret, sharpe)
          'target_vol'      → dict(weights, vol, ret, sharpe) | None
          'tickers'         → list of ticker names
    """
    try:
        from scipy.optimize import minimize
    except ImportError:
        raise ImportError("scipy is required for efficient frontier. Run: pip install scipy")

    tickers = list(prices.columns)
    n = len(tickers)
    if n < 2:
        return {}

    daily_returns = prices.pct_change().dropna()
    if len(daily_returns) < 60:
        return {}

    # Annualised mean returns and covariance matrix
    mu  = daily_returns.mean() * TRADING_DAYS
    cov = daily_returns.cov()  * TRADING_DAYS

    rf_daily = (1 + rf_annual) ** (1 / TRADING_DAYS) - 1

    def _portfolio_stats(w: np.ndarray) -> tuple[float, float, float]:
        ret = float(w @ mu)
        vol = float(np.sqrt(w @ cov.values @ w))
        sharpe = (ret - rf_annual) / vol if vol > 0 else 0.0
        return ret, vol, sharpe

    # ── Random portfolio sampling ─────────────────────────────────────────────
    rng = np.random.default_rng(42)
    rows = []
    for _ in range(n_portfolios):
        raw = rng.random(n)
        w = raw / raw.sum()
        ret, vol, sharpe = _portfolio_stats(w)
        rows.append({"vol": vol, "ret": ret, "sharpe": sharpe,
                     **{t: float(w[i]) for i, t in enumerate(tickers)}})

    frontier_df = pd.DataFrame(rows)

    # ── Optimised portfolios ──────────────────────────────────────────────────
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    bounds = [(0.0, 1.0)] * n
    w0 = np.full(n, 1.0 / n)

    def _neg_sharpe(w):
        ret, vol, _ = _portfolio_stats(w)
        return -(ret - rf_annual) / vol if vol > 0 else 0.0

    def _portfolio_vol(w):
        return float(np.sqrt(w @ cov.values @ w))

    # Max Sharpe
    res_sharpe = minimize(_neg_sharpe, w0, method="SLSQP",
                          bounds=bounds, constraints=constraints,
                          options={"ftol": 1e-9, "maxiter": 1000})
    w_ms = res_sharpe.x / res_sharpe.x.sum()
    ms_ret, ms_vol, ms_sharpe = _portfolio_stats(w_ms)
    max_sharpe = {
        "weights": {t: float(w_ms[i]) for i, t in enumerate(tickers)},
        "vol": ms_vol, "ret": ms_ret, "sharpe": ms_sharpe,
    }

    # Min Vol
    res_mv = minimize(_portfolio_vol, w0, method="SLSQP",
                      bounds=bounds, constraints=constraints,
                      options={"ftol": 1e-9, "maxiter": 1000})
    w_mv = res_mv.x / res_mv.x.sum()
    mv_ret, mv_vol, mv_sharpe = _portfolio_stats(w_mv)
    min_vol_port = {
        "weights": {t: float(w_mv[i]) for i, t in enumerate(tickers)},
        "vol": mv_vol, "ret": mv_ret, "sharpe": mv_sharpe,
    }

    # Target vol portfolio (max Sharpe subject to vol ≤ target_vol)
    target_port = None
    if target_vol is not None and target_vol > mv_vol:
        vol_constraint = [
            {"type": "eq",  "fun": lambda w: w.sum() - 1},
            {"type": "ineq","fun": lambda w: target_vol - _portfolio_vol(w)},
        ]
        res_tv = minimize(_neg_sharpe, w0, method="SLSQP",
                          bounds=bounds, constraints=vol_constraint,
                          options={"ftol": 1e-9, "maxiter": 1000})
        if res_tv.success:
            w_tv = res_tv.x / res_tv.x.sum()
            tv_ret, tv_vol, tv_sharpe = _portfolio_stats(w_tv)
            target_port = {
                "weights": {t: float(w_tv[i]) for i, t in enumerate(tickers)},
                "vol": tv_vol, "ret": tv_ret, "sharpe": tv_sharpe,
            }

    return {
        "frontier":   frontier_df,
        "max_sharpe": max_sharpe,
        "min_vol":    min_vol_port,
        "target_vol": target_port,
        "tickers":    tickers,
        "rf_annual":  rf_annual,
    }
