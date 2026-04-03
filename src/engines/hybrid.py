"""
Engine 3 — Hybrid Allocation Model.
Blends cross-sectional momentum signals with macro regime allocations.

The macro_alpha parameter controls the blend:
  alpha = 0.0  →  pure historical momentum
  alpha = 1.0  →  pure macro regime
  alpha = 0.5  →  equal blend (default)

This allows the user to express a view on how much forward-looking
macro information should override the purely backward-looking momentum model.
"""
from __future__ import annotations
import pandas as pd
import numpy as np

from src.analytics.returns import cumulative_returns_series
from src.analytics.risk import summary_stats
from src.engines.macro_regime import (
    compute_regime_signals,
    regime_allocation,
    Regime,
    PREFERRED_PROXIES,
)


# ── Signal computation ────────────────────────────────────────────────────────

def compute_momentum_scores(
    prices: pd.DataFrame,
    lookback_months: int = 6,
    smoothing_days: int = 5,
) -> pd.DataFrame:
    """
    Compute cross-sectional momentum rank score per asset (0=weakest, 1=strongest).
    Uses trailing lookback_month return, smoothed and cross-sectionally ranked.

    Returns:
        DataFrame of percentile rank scores, same shape as prices (with NaN at start).
    """
    days = lookback_months * 21
    raw = prices.pct_change(periods=days).rolling(smoothing_days).mean()
    return raw.rank(axis=1, pct=True).dropna()


def blend_weights(
    momentum_weights: dict[str, float],
    regime_weights: dict[str, float],
    macro_alpha: float,
) -> dict[str, float]:
    """
    Linearly blend two weight dicts by macro_alpha.
    The union of both ticker sets is covered; missing weights default to 0.
    The result is renormalized to sum to 1.

    Args:
        momentum_weights: Weights from the historical momentum model.
        regime_weights:   Weights from the macro regime allocation.
        macro_alpha:      Weight on macro (0 = pure momentum, 1 = pure macro).

    Returns:
        Normalized blended weight dict.
    """
    all_tickers = set(momentum_weights) | set(regime_weights)
    blended = {
        t: (1.0 - macro_alpha) * momentum_weights.get(t, 0.0)
         + macro_alpha         * regime_weights.get(t, 0.0)
        for t in all_tickers
    }
    total = sum(blended.values())
    if total > 0:
        blended = {t: w / total for t, w in blended.items()}
    return blended


# ── Backtest ──────────────────────────────────────────────────────────────────

def backtest_hybrid_strategy(
    prices: pd.DataFrame,
    asset_universe: list[str],
    macro_alpha: float = 0.5,
    lookback_months: int = 6,
    top_n: int = 3,
    rf_annual: float = 0.04,
) -> dict:
    """
    Backtest the hybrid strategy.

    Each calendar month:
      1. Momentum weight  : equal-weight top_n assets by trailing momentum score.
      2. Regime weight    : use the detected macro regime's allocation template.
      3. Blend            : hybrid = (1-α) × momentum_weight + α × regime_weight.
      4. Apply            : hold blended portfolio for the full next month.

    Args:
        prices:         Full price DataFrame (may include proxy tickers beyond asset_universe).
        asset_universe: List of investable tickers (subset of prices.columns).
        macro_alpha:    Blend parameter (0=momentum only, 1=macro only).
        lookback_months: Momentum formation window in months.
        top_n:          Number of assets to long in momentum leg.
        rf_annual:      Annual risk-free rate for performance stats.

    Returns:
        dict with 'returns', 'cumulative', 'stats', 'monthly_weights' — or {} on failure.
    """
    available = [t for t in asset_universe if t in prices.columns]
    if not available:
        return {}

    # Regime signals — use all proxy tickers present in prices
    proxy_cols = [t for t in PREFERRED_PROXIES if t in prices.columns]
    proxy_prices = prices[proxy_cols] if proxy_cols else prices[available]
    regime_signals = compute_regime_signals(proxy_prices)
    if regime_signals.empty:
        return {}

    monthly_regime = regime_signals["regime"].resample("ME").last()

    # Momentum scores — only from investable universe
    momentum_scores = compute_momentum_scores(prices[available], lookback_months=lookback_months)
    monthly_momentum = momentum_scores.resample("ME").last()

    daily_returns = prices[available].pct_change().dropna()
    months = monthly_regime.index

    # Build a daily weight DataFrame (vectorized approach)
    weight_matrix = pd.DataFrame(0.0, index=daily_returns.index, columns=available)
    monthly_weights_log: list[dict] = []

    for i, month_end in enumerate(months[:-1]):
        next_month_end = months[i + 1]

        # ── Regime weights ──
        regime = Regime(monthly_regime.loc[month_end])
        raw_mac_w = {t: w for t, w in regime_allocation(regime).items() if t in available}
        if raw_mac_w:
            total = sum(raw_mac_w.values())
            mac_w = {t: w / total for t, w in raw_mac_w.items()}
        else:
            mac_w = {}

        # ── Momentum weights ──
        if month_end in monthly_momentum.index:
            scores = monthly_momentum.loc[month_end].dropna()
            k = min(top_n, len(scores))
            top_assets = scores.nlargest(k).index.tolist()
            mom_w = {t: 1.0 / k for t in top_assets}
        else:
            mom_w = {t: 1.0 / len(available) for t in available}

        # ── Blend ──
        blended = blend_weights(mom_w, mac_w, macro_alpha)
        blended = {t: w for t, w in blended.items() if t in available and w > 1e-6}
        if not blended:
            continue

        total = sum(blended.values())
        blended = {t: w / total for t, w in blended.items()}

        # Apply to next month's trading days
        mask = (daily_returns.index > month_end) & (daily_returns.index <= next_month_end)
        for t, w in blended.items():
            weight_matrix.loc[mask, t] = w

        monthly_weights_log.append({"date": month_end, "regime": regime.value, **blended})

    # Compute portfolio returns (fully vectorized)
    port_returns = (weight_matrix * daily_returns).sum(axis=1)
    port_returns = port_returns[port_returns != 0]
    port_returns.name = f"Hybrid (α={macro_alpha:.2f})"

    if port_returns.empty:
        return {}

    return {
        "returns":         port_returns,
        "cumulative":      cumulative_returns_series(port_returns),
        "stats":           summary_stats(port_returns, rf_annual),
        "monthly_weights": pd.DataFrame(monthly_weights_log).set_index("date") if monthly_weights_log else pd.DataFrame(),
    }


def run_alpha_sensitivity(
    prices: pd.DataFrame,
    asset_universe: list[str],
    alpha_values: list[float] | None = None,
    lookback_months: int = 6,
    top_n: int = 3,
    rf_annual: float = 0.04,
) -> dict[str, dict]:
    """
    Run the hybrid strategy for multiple alpha values to show sensitivity.
    Returns dict keyed by alpha label, each with 'returns', 'cumulative', 'stats'.
    """
    if alpha_values is None:
        alpha_values = [0.0, 0.25, 0.5, 0.75, 1.0]

    results: dict[str, dict] = {}
    for alpha in alpha_values:
        label = f"α={alpha:.2f}"
        res = backtest_hybrid_strategy(
            prices, asset_universe,
            macro_alpha=alpha,
            lookback_months=lookback_months,
            top_n=top_n,
            rf_annual=rf_annual,
        )
        if res:
            res["returns"].name = label
            results[label] = res

    return results
