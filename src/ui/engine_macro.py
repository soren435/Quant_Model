"""
UI — Engine 2: Macro Regime Model.
Displays current market regime, signal history, regime-based allocation,
and a backtest of the regime-switching strategy.
"""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data.loader import download_prices
from src.engines.macro_regime import (
    Regime,
    PREFERRED_PROXIES,
    REGIME_COLORS,
    REGIME_ALLOCATIONS,
    REGIME_DESCRIPTIONS,
    backtest_regime_strategy,
    current_regime_state,
    compute_regime_signals,
)
from src.analytics.risk import drawdown_series
from src.visualization.charts import (
    plot_cumulative_returns,
    plot_drawdown,
    plot_allocation_pie,
    COLORS,
    _layout,
)
from src.utils.formatting import format_pct


# ── Chart helpers ─────────────────────────────────────────────────────────────

def _plot_signal_history(signals: pd.DataFrame) -> go.Figure:
    """Stacked area chart of growth and inflation signals over time."""
    fig = go.Figure(layout=_layout("Regime Signals — Growth vs Inflation"))
    fig.add_trace(go.Scatter(
        x=signals.index, y=signals["growth_signal"] * 100,
        name="Growth Signal",
        fill="tozeroy",
        fillcolor="rgba(37,99,235,0.15)",
        line=dict(color=COLORS[0], width=1.5),
        hovertemplate="Growth: %{y:.2f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=signals.index, y=signals["inflation_signal"] * 100,
        name="Inflation Signal",
        fill="tozeroy",
        fillcolor="rgba(245,158,11,0.15)",
        line=dict(color=COLORS[4], width=1.5),
        hovertemplate="Inflation: %{y:.2f}%<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#94A3B8", dash="dash", width=1))
    fig.update_yaxes(title_text="Signal value (×100)", ticksuffix="")
    return fig


def _plot_regime_timeline(prices: pd.Series, signals: pd.DataFrame, ticker: str = "SPY") -> go.Figure:
    """Price chart with colored background bands per detected regime."""
    fig = go.Figure(layout=_layout(f"Regime History — {ticker} (Indexed, Base = 100)"))

    # Normalized price
    normed = prices / prices.iloc[0] * 100
    fig.add_trace(go.Scatter(
        x=normed.index, y=normed,
        name=ticker,
        line=dict(color=COLORS[0], width=2),
        hovertemplate=f"{ticker}: %{{y:.1f}}<extra></extra>",
    ))

    if "regime" not in signals.columns or signals.empty:
        return fig

    regime_daily = signals["regime"].reindex(normed.index, method="ffill").dropna()
    changes = regime_daily[regime_daily != regime_daily.shift()].dropna()

    for i, (start, regime_val) in enumerate(changes.items()):
        end = changes.index[i + 1] if i + 1 < len(changes) else regime_daily.index[-1]
        try:
            regime_obj = Regime(regime_val)
            hex_color = REGIME_COLORS.get(regime_obj, "#94A3B8").lstrip("#")
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            fill = f"rgba({r},{g},{b},0.15)"
            line_color = f"rgba({r},{g},{b},0.0)"
        except ValueError:
            fill = "rgba(148,163,184,0.10)"
            line_color = "rgba(0,0,0,0)"

        fig.add_vrect(
            x0=start, x1=end,
            fillcolor=fill,
            line_color=line_color,
            layer="below",
        )

    # Legend patches (fake scatter traces for regime colors)
    for regime, color in REGIME_COLORS.items():
        if regime == Regime.UNKNOWN:
            continue
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode="markers",
            marker=dict(size=12, color=color, symbol="square"),
            name=regime.value,
            showlegend=True,
        ))

    fig.update_yaxes(title_text="Indexed value (base = 100)")
    return fig


def _regime_badge_html(regime: Regime, color: str) -> str:
    return (
        f"<div style='display:inline-block; padding:10px 22px; border-radius:8px; "
        f"background:{color}20; border:2px solid {color}; color:{color}; "
        f"font-size:1.6rem; font-weight:700; letter-spacing:0.04em;'>"
        f"{regime.value.upper()}</div>"
    )


# ── Main render ───────────────────────────────────────────────────────────────

def render_engine_macro(
    cfg: dict,
    start_str: str,
    end_str: str,
    rf_annual: float,
    lang: str = "en",
) -> None:
    st.header("🌐 Engine 2 — Macro Regime Model")
    st.caption(
        "Detects the current market regime from liquid ETF proxies — no proprietary data required. "
        "Translates regime into a recommended portfolio allocation and backtests the strategy."
    )

    # ── Download proxy data ───────────────────────────────────────────────────
    with st.spinner("Downloading macro proxy data…"):
        prices = download_prices(tuple(PREFERRED_PROXIES), start_str, end_str)

    if prices.empty or "SPY" not in prices.columns:
        st.error("Could not download required proxy data. Check network connection.")
        return

    # ── Current regime ────────────────────────────────────────────────────────
    state = current_regime_state(prices)
    color = REGIME_COLORS.get(state.regime, "#94A3B8")

    st.subheader("Current Regime")
    regime_col, signals_col = st.columns([1, 2])

    with regime_col:
        st.markdown(_regime_badge_html(state.regime, color), unsafe_allow_html=True)
        st.write("")
        st.write(state.description)

    with signals_col:
        s1, s2, s3 = st.columns(3)
        growth_pct  = state.growth_signal * 100
        infl_pct    = state.inflation_signal * 100
        credit_pct  = state.credit_signal * 100

        s1.metric(
            "Growth Signal",
            f"{growth_pct:+.2f}%",
            delta="Positive ↑" if state.growth_signal > 0 else "Negative ↓",
            delta_color="normal" if state.growth_signal > 0 else "inverse",
            help="SPY 6-month return (smoothed). Positive = expanding economy.",
        )
        s2.metric(
            "Inflation Signal",
            f"{infl_pct:+.2f}%",
            delta="Rising ↑" if state.inflation_signal > 0 else "Falling ↓",
            delta_color="inverse" if state.inflation_signal > 0 else "normal",
            help="TIP/IEF ratio 3-month change. Positive = rising inflation expectations.",
        )
        s3.metric(
            "Credit Signal",
            f"{credit_pct:+.2f}%",
            delta="Risk-on" if state.credit_signal > 0 else "Risk-off",
            delta_color="normal" if state.credit_signal > 0 else "inverse",
            help="HYG/IEF ratio 3-month change. Positive = credit markets are risk-on.",
        )

    st.divider()

    # ── Regime allocation ─────────────────────────────────────────────────────
    st.subheader("Recommended Allocation")
    alloc_col, desc_col = st.columns([1, 1])

    with alloc_col:
        alloc = {k: v for k, v in REGIME_ALLOCATIONS.get(state.regime, {}).items()}
        st.plotly_chart(
            plot_allocation_pie(alloc, title=f"{state.regime.value} Allocation"),
            use_container_width=True,
        )

    with desc_col:
        st.write("**All four regime allocations:**")
        for regime, regime_alloc in REGIME_ALLOCATIONS.items():
            hex_c = REGIME_COLORS.get(regime, "#94A3B8")
            active = " ← current" if regime == state.regime else ""
            st.markdown(
                f"<span style='color:{hex_c}; font-weight:600;'>■ {regime.value}{active}</span>",
                unsafe_allow_html=True,
            )
            desc = REGIME_DESCRIPTIONS.get(regime, "")
            parts = ", ".join(f"{t} {w*100:.0f}%" for t, w in regime_alloc.items())
            st.caption(f"{parts}")

    st.divider()

    # ── Signal history ────────────────────────────────────────────────────────
    signals = compute_regime_signals(prices)
    if not signals.empty:
        st.subheader("Signal History")
        st.plotly_chart(_plot_signal_history(signals), use_container_width=True)

        st.subheader("Regime History")
        if "SPY" in prices.columns:
            st.plotly_chart(
                _plot_regime_timeline(prices["SPY"], signals, ticker="SPY"),
                use_container_width=True,
            )

        # Regime distribution pie
        regime_counts = signals["regime"].value_counts()
        regime_pct = (regime_counts / regime_counts.sum()).to_dict()
        regime_col2, _ = st.columns([1, 2])
        with regime_col2:
            st.plotly_chart(
                plot_allocation_pie(regime_pct, title="Time Spent in Each Regime"),
                use_container_width=True,
            )

    st.divider()

    # ── Strategy backtest ─────────────────────────────────────────────────────
    st.subheader("Regime Strategy Backtest")
    st.caption("Each month: detect regime → apply regime allocation → hold for 1 month.")

    with st.spinner("Running regime strategy backtest…"):
        result = backtest_regime_strategy(prices, rf_annual=rf_annual)

    if not result:
        st.warning("Backtest returned no results. Try extending the date range (needs 6+ months of data).")
        return

    # vs SPY benchmark
    spy_ret = prices["SPY"].pct_change().dropna() if "SPY" in prices.columns else None

    # KPIs
    s = result["stats"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ann. Return",  format_pct(s.get("Annualized Return", 0)))
    k2.metric("Ann. Vol",     format_pct(s.get("Annualized Volatility", 0)))
    k3.metric("Sharpe",       f"{s.get('Sharpe Ratio', 0):.2f}")
    k4.metric("Max Drawdown", format_pct(s.get("Max Drawdown", 0)))

    # Cumulative
    cum_dict: dict[str, pd.Series] = {"Macro Regime": result["cumulative"]}
    if spy_ret is not None:
        from src.analytics.returns import cumulative_returns_series
        spy_cum = cumulative_returns_series(spy_ret.loc[result["cumulative"].index[0]:])
        cum_dict["SPY (Buy & Hold)"] = spy_cum

    st.plotly_chart(
        plot_cumulative_returns(pd.DataFrame(cum_dict), title="Macro Regime Strategy vs SPY"),
        use_container_width=True,
    )

    dd_dict: dict[str, pd.Series] = {"Macro Regime": drawdown_series(result["returns"])}
    if spy_ret is not None:
        dd_dict["SPY"] = drawdown_series(spy_ret.loc[result["returns"].index[0]:])

    st.plotly_chart(
        plot_drawdown(pd.DataFrame(dd_dict), title="Drawdown Comparison"),
        use_container_width=True,
    )

    # ── Methodology ───────────────────────────────────────────────────────────
    with st.expander("📖 Methodology"):
        st.markdown("""
**Regime detection** uses three market-based signals:

| Signal | Proxy | Logic |
|--------|-------|-------|
| Growth | SPY 6-month return (smoothed) | Positive → economy expanding |
| Inflation | TIP/IEF ratio 3-month change | Positive → inflation expectations rising |
| Credit | HYG/IEF ratio 3-month change | Positive → credit markets risk-on |

**Regime classification** (2×2 matrix):
- **Expansion**: Growth↑ + Inflation↑ → risk assets + real assets
- **Goldilocks**: Growth↑ + Inflation↓ → equities + long bonds
- **Stagflation**: Growth↓ + Inflation↑ → TIPS + commodities + cash
- **Recession**: Growth↓ + Inflation↓ → bonds + gold

Signals are smoothed with a 21-day rolling mean to reduce noise. Regime is determined
monthly (end of month) and held for the following month — no look-ahead bias.

**Limitations**: Market proxies are imperfect substitutes for actual macro data (PMI, CPI, GDP).
For higher accuracy, use the CSV upload to override signals with official data.
        """)
