"""
Engine 2 — Macro Regime Model.
Market-based regime detection using liquid ETF proxies (all via yfinance).

Regime framework: 2×2 Growth / Inflation quadrant (Bridgewater-inspired).
  ─────────────────────────────────────
          │ Inflation ↑  │ Inflation ↓
  ────────┼──────────────┼──────────────
  Growth↑ │  Expansion   │  Goldilocks
  Growth↓ │ Stagflation  │  Recession
  ─────────────────────────────────────

Signals derived entirely from market prices — no proprietary macro data required.
Optional: upload a CSV with official PMI/CPI data for enhanced precision.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum

from src.analytics.returns import cumulative_returns_series
from src.analytics.risk import summary_stats


# ── Regime taxonomy ───────────────────────────────────────────────────────────

class Regime(str, Enum):
    EXPANSION   = "Expansion"
    GOLDILOCKS  = "Goldilocks"
    STAGFLATION = "Stagflation"
    RECESSION   = "Recession"
    UNKNOWN     = "Unknown"


@dataclass
class RegimeState:
    regime:           Regime
    growth_signal:    float   # positive = growing; negative = contracting
    inflation_signal: float   # positive = rising inflation; negative = falling
    credit_signal:    float   # positive = risk-on; negative = risk-off
    description:      str


REGIME_COLORS: dict[Regime, str] = {
    Regime.EXPANSION:   "#16A34A",  # green
    Regime.GOLDILOCKS:  "#2563EB",  # blue
    Regime.STAGFLATION: "#F59E0B",  # amber
    Regime.RECESSION:   "#DC2626",  # red
    Regime.UNKNOWN:     "#94A3B8",  # slate
}

REGIME_DESCRIPTIONS: dict[Regime, str] = {
    Regime.EXPANSION:   "Growth accelerating, inflation moderate. Risk assets and real assets favored.",
    Regime.GOLDILOCKS:  "Growth positive, inflation low. Equities and long-duration bonds optimal.",
    Regime.STAGFLATION: "Growth slowing, inflation elevated. Real assets and short-duration cash.",
    Regime.RECESSION:   "Growth contracting, deflation pressure. Long bonds and gold dominate.",
}

# ── Proxy tickers required for regime detection ───────────────────────────────

#: Minimum required for basic signal computation
REQUIRED_PROXIES = ["SPY", "IEF"]

#: Full list used when available; missing tickers fall back gracefully
PREFERRED_PROXIES = ["SPY", "QQQ", "TLT", "IEF", "SHY", "GLD", "TIP", "HYG", "DJP"]

# ── Regime allocation templates ───────────────────────────────────────────────

REGIME_ALLOCATIONS: dict[Regime, dict[str, float]] = {
    Regime.EXPANSION: {
        "SPY": 0.40,   # US equities (growth)
        "QQQ": 0.10,   # Tech / growth equities
        "GLD": 0.15,   # Gold (real asset)
        "DJP": 0.10,   # Commodities
        "IEF": 0.25,   # Medium bonds (inflation hedge buffer)
    },
    Regime.GOLDILOCKS: {
        "SPY": 0.45,   # US equities
        "QQQ": 0.15,   # Growth equities
        "TLT": 0.25,   # Long bonds (favorable in low-inflation growth)
        "IEF": 0.10,   # Medium bonds
        "GLD": 0.05,   # Minimal gold hedge
    },
    Regime.STAGFLATION: {
        "GLD": 0.25,   # Gold (real asset, inflation hedge)
        "DJP": 0.20,   # Commodities (direct inflation exposure)
        "TIP": 0.20,   # TIPS (inflation-protected bonds)
        "SHY": 0.25,   # Short-duration / near-cash
        "SPY": 0.10,   # Minimal equity exposure
    },
    Regime.RECESSION: {
        "TLT": 0.35,   # Long bonds (flight to safety + rate cuts benefit)
        "IEF": 0.25,   # Medium bonds
        "GLD": 0.20,   # Gold (safe haven)
        "SHY": 0.15,   # Cash equivalent
        "SPY": 0.05,   # Minimal equity (tactical bottom-picking)
    },
}


# ── Signal computation ────────────────────────────────────────────────────────

def _pct_change_months(series: pd.Series, months: int) -> pd.Series:
    """Approximate n-month return using 21 trading days per month."""
    return series.pct_change(periods=months * 21)


def compute_regime_signals(
    prices: pd.DataFrame,
    smoothing_days: int = 21,
) -> pd.DataFrame:
    """
    Compute daily regime classification signals from market proxy prices.

    Signals:
      growth_signal    : SPY 6-month return (positive → expansion)
      inflation_signal : TIP/IEF ratio 3-month change (positive → rising inflation)
                         Fallback: DJP momentum if TIP unavailable
      credit_signal    : HYG/IEF ratio 3-month change (positive → risk-on)
                         Fallback: growth_signal if HYG unavailable

    Each signal is smoothed by a rolling mean to reduce noise.

    Returns:
        DataFrame with columns ['growth_signal', 'inflation_signal', 'credit_signal', 'regime'].
        Only rows with all signals valid (no NaN) are returned.
    """
    cols = prices.columns.tolist()
    out = pd.DataFrame(index=prices.index)

    # ── Growth signal ──
    if "SPY" in cols:
        raw = _pct_change_months(prices["SPY"], 6)
        out["growth_signal"] = raw.rolling(smoothing_days).mean()
    else:
        out["growth_signal"] = 0.0

    # ── Inflation signal ──
    if "TIP" in cols and "IEF" in cols:
        ratio = prices["TIP"] / prices["IEF"]
        out["inflation_signal"] = _pct_change_months(ratio, 3).rolling(smoothing_days).mean()
    elif "DJP" in cols:
        out["inflation_signal"] = _pct_change_months(prices["DJP"], 3).rolling(smoothing_days).mean()
    else:
        out["inflation_signal"] = 0.0

    # ── Credit signal ──
    if "HYG" in cols and "IEF" in cols:
        ratio = prices["HYG"] / prices["IEF"]
        out["credit_signal"] = _pct_change_months(ratio, 3).rolling(smoothing_days).mean()
    else:
        out["credit_signal"] = out["growth_signal"].copy()

    out = out.dropna()

    # ── Regime classification ──
    def _classify(row: pd.Series) -> str:
        growth_pos    = row["growth_signal"] > 0
        inflation_pos = row["inflation_signal"] > 0
        if growth_pos and inflation_pos:
            return Regime.EXPANSION.value
        elif growth_pos:
            return Regime.GOLDILOCKS.value
        elif inflation_pos:
            return Regime.STAGFLATION.value
        else:
            return Regime.RECESSION.value

    out["regime"] = out.apply(_classify, axis=1)
    return out


def current_regime_state(prices: pd.DataFrame) -> RegimeState:
    """Detect and return the most recent regime state."""
    signals = compute_regime_signals(prices)
    if signals.empty:
        return RegimeState(Regime.UNKNOWN, 0.0, 0.0, 0.0, "Insufficient data to determine regime.")

    latest = signals.iloc[-1]
    regime = Regime(latest["regime"])
    return RegimeState(
        regime=regime,
        growth_signal=float(latest["growth_signal"]),
        inflation_signal=float(latest["inflation_signal"]),
        credit_signal=float(latest["credit_signal"]),
        description=REGIME_DESCRIPTIONS.get(regime, ""),
    )


def regime_allocation(regime: Regime) -> dict[str, float]:
    """Return target allocation weights for a given regime."""
    return REGIME_ALLOCATIONS.get(regime, REGIME_ALLOCATIONS[Regime.RECESSION])


# ── Regime strategy backtest ──────────────────────────────────────────────────

def backtest_regime_strategy(
    prices: pd.DataFrame,
    rf_annual: float = 0.04,
) -> dict:
    """
    Backtest the macro regime strategy (vectorized).

    Each calendar month: detect the regime from the previous month-end signal,
    apply the corresponding allocation, hold for the full month.

    Returns:
        dict with 'returns', 'cumulative', 'stats', 'signals' — or {} on failure.
    """
    signals = compute_regime_signals(prices)
    if signals.empty:
        return {}

    daily_returns = prices.pct_change().dropna()

    # Forward-fill monthly regime to each trading day
    monthly_regime = signals["regime"].resample("ME").last()
    daily_regime = monthly_regime.reindex(daily_returns.index, method="ffill").dropna()

    common_idx = daily_returns.index.intersection(daily_regime.index)
    if common_idx.empty:
        return {}

    port_returns = pd.Series(0.0, index=common_idx)

    for regime_str in [r.value for r in Regime if r != Regime.UNKNOWN]:
        regime = Regime(regime_str)
        alloc = {t: w for t, w in regime_allocation(regime).items() if t in daily_returns.columns}
        if not alloc:
            continue

        total = sum(alloc.values())
        alloc = {t: w / total for t, w in alloc.items()}

        bool_mask = (daily_regime.loc[common_idx] == regime_str).values
        regime_idx = common_idx[bool_mask]
        if regime_idx.empty:
            continue

        for t, w in alloc.items():
            port_returns.loc[regime_idx] += w * daily_returns.loc[regime_idx, t]

    port_returns.name = "Macro Regime"
    port_returns = port_returns[port_returns != 0]  # drop unassigned days at start

    if port_returns.empty:
        return {}

    return {
        "returns":    port_returns,
        "cumulative": cumulative_returns_series(port_returns),
        "stats":      summary_stats(port_returns, rf_annual),
        "signals":    signals,
    }
