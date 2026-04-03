"""
UI — Engine 3: Hybrid Allocation Model.
Blends cross-sectional momentum with macro regime allocation.
The user controls the blend via an alpha slider.
"""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data.loader import download_prices
from src.engines.hybrid import backtest_hybrid_strategy, run_alpha_sensitivity
from src.engines.macro_regime import PREFERRED_PROXIES
from src.analytics.risk import drawdown_series
from src.analytics.returns import cumulative_returns_series
from src.visualization.charts import (
    plot_cumulative_returns,
    plot_drawdown,
    plot_allocation_pie,
    plot_bar_returns,
    COLORS,
    _layout,
)
from src.utils.formatting import format_pct


_DEFAULT_UNIVERSE = ["SPY", "QQQ", "IEF", "GLD", "AGG", "SHY"]


def _plot_weight_evolution(monthly_weights: pd.DataFrame, title: str = "Monthly Portfolio Weights") -> go.Figure:
    """Stacked area chart showing how blended weights evolve over time."""
    if monthly_weights.empty:
        return go.Figure()

    fig = go.Figure(layout=_layout(title))
    tickers = [c for c in monthly_weights.columns if c not in ("regime",)]
    data_cols = monthly_weights[tickers].fillna(0)

    for i, ticker in enumerate(tickers):
        fig.add_trace(go.Bar(
            x=data_cols.index,
            y=data_cols[ticker] * 100,
            name=ticker,
            marker_color=COLORS[i % len(COLORS)],
            hovertemplate=f"<b>{ticker}</b>: %{{y:.1f}}%<extra></extra>",
        ))

    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Weight (%)", ticksuffix="%")
    return fig


def render_engine_hybrid(
    cfg: dict,
    start_str: str,
    end_str: str,
    rf_annual: float,
    lang: str = "en",
) -> None:
    st.header("⚗️ Engine 3 — Hybrid Allocation Model")
    st.caption(
        "Combines backward-looking momentum signals with forward-looking macro regime allocation. "
        "The alpha slider lets you express how much weight to place on each signal source."
    )

    # ── Configuration ─────────────────────────────────────────────────────────
    with st.expander("⚙️ Configuration", expanded=True):
        all_tickers = (
            cfg["tickers"].get("equities", [])
            + cfg["tickers"].get("bonds", [])
            + cfg["tickers"].get("alternatives", [])
        )
        col_a, col_b = st.columns([2, 1])
        with col_a:
            universe = st.multiselect(
                "Asset universe (investable tickers)",
                options=sorted(set(all_tickers)),
                default=_DEFAULT_UNIVERSE,
                help="The set of ETFs the hybrid strategy can hold.",
            )
        with col_b:
            lookback = st.slider("Momentum lookback (months)", 3, 12, 6)
            top_n    = st.slider("Top-N momentum assets", 1, min(8, len(universe) if universe else 5), 3)

    if not universe:
        st.warning("Select at least 2 tickers.")
        return

    # Alpha slider — outside expander so it's prominent
    st.subheader("Signal Blend")
    alpha = st.slider(
        "Macro alpha (α)  ← pure momentum | pure macro regime →",
        min_value=0.0, max_value=1.0, value=0.5, step=0.05,
        format="%.2f",
        help="0 = 100% momentum signal, 1 = 100% macro regime, 0.5 = equal blend.",
    )

    col_m, col_r = st.columns(2)
    col_m.metric("Momentum weight", f"{(1-alpha)*100:.0f}%")
    col_r.metric("Macro regime weight", f"{alpha*100:.0f}%")

    # ── Download data ─────────────────────────────────────────────────────────
    all_needed = tuple(sorted(set(universe + PREFERRED_PROXIES)))
    with st.spinner("Downloading data…"):
        prices = download_prices(all_needed, start_str, end_str)

    if prices.empty:
        st.error("No price data returned.")
        return

    # ── Run selected alpha ────────────────────────────────────────────────────
    with st.spinner("Running hybrid strategy…"):
        result = backtest_hybrid_strategy(
            prices, universe,
            macro_alpha=alpha,
            lookback_months=lookback,
            top_n=top_n,
            rf_annual=rf_annual,
        )

    if not result:
        st.warning("Strategy returned no results. Extend the date range or adjust settings.")
        return

    # KPIs
    s = result["stats"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ann. Return",  format_pct(s.get("Annualized Return", 0)))
    k2.metric("Ann. Vol",     format_pct(s.get("Annualized Volatility", 0)))
    k3.metric("Sharpe",       f"{s.get('Sharpe Ratio', 0):.2f}")
    k4.metric("Max Drawdown", format_pct(s.get("Max Drawdown", 0)))

    st.divider()

    # ── Cumulative chart ──────────────────────────────────────────────────────
    cum_dict: dict[str, pd.Series] = {result["returns"].name: result["cumulative"]}
    if "SPY" in prices.columns:
        spy_ret = prices["SPY"].pct_change().dropna()
        spy_aligned = spy_ret.loc[result["cumulative"].index[0]:]
        cum_dict["SPY B&H"] = cumulative_returns_series(spy_aligned)

    st.plotly_chart(
        plot_cumulative_returns(pd.DataFrame(cum_dict), title="Hybrid Strategy — Cumulative Returns"),
        use_container_width=True,
    )

    dd_dict: dict[str, pd.Series] = {result["returns"].name: drawdown_series(result["returns"])}
    if "SPY" in prices.columns:
        spy_ret = prices["SPY"].pct_change().dropna()
        dd_dict["SPY"] = drawdown_series(spy_ret.loc[result["returns"].index[0]:])

    st.plotly_chart(
        plot_drawdown(pd.DataFrame(dd_dict), title="Drawdown"),
        use_container_width=True,
    )

    # ── Weight evolution ──────────────────────────────────────────────────────
    if not result.get("monthly_weights", pd.DataFrame()).empty:
        st.subheader("Portfolio Weight Evolution")
        st.plotly_chart(
            _plot_weight_evolution(result["monthly_weights"], "Blended Monthly Weights"),
            use_container_width=True,
        )

    st.divider()

    # ── Sensitivity analysis ──────────────────────────────────────────────────
    st.subheader("Alpha Sensitivity Analysis")
    st.caption("Compare returns across the full spectrum of macro alpha values (0 to 1).")

    run_sensitivity = st.button("Run sensitivity analysis (5 alpha values)", type="secondary")
    if run_sensitivity:
        with st.spinner("Running sensitivity sweep…"):
            sensitivity = run_alpha_sensitivity(
                prices, universe,
                lookback_months=lookback,
                top_n=top_n,
                rf_annual=rf_annual,
            )

        if sensitivity:
            # Cumulative chart
            cum_sens = pd.DataFrame({name: r["cumulative"] for name, r in sensitivity.items()})
            st.plotly_chart(
                plot_cumulative_returns(cum_sens, title="Alpha Sensitivity — Cumulative Returns"),
                use_container_width=True,
            )

            # Stats table
            st.plotly_chart(
                plot_bar_returns(
                    {n: r["stats"] for n, r in sensitivity.items()},
                    metric="Sharpe Ratio",
                    title="Sharpe Ratio by Alpha",
                ),
                use_container_width=True,
            )

            rows = []
            for name, res in sensitivity.items():
                ss = res["stats"]
                rows.append({
                    "Alpha":       name,
                    "Ann. Return": format_pct(ss.get("Annualized Return", 0)),
                    "Ann. Vol":    format_pct(ss.get("Annualized Volatility", 0)),
                    "Sharpe":      f"{ss.get('Sharpe Ratio', 0):.2f}",
                    "Max DD":      format_pct(ss.get("Max Drawdown", 0)),
                })
            st.dataframe(pd.DataFrame(rows).set_index("Alpha"), use_container_width=True)

    with st.expander("📖 Methodology"):
        st.markdown("""
**Blending logic**

Each calendar month:
1. **Momentum weight** — rank assets by trailing 6-month (configurable) return; go
   equal-weight long in the top-N.
2. **Regime weight** — detect macro regime from market proxies; apply the regime's
   pre-defined ETF allocation template (Engine 2).
3. **Blend** — `w = (1-α) × momentum_weight + α × regime_weight` (normalized to 1).

**Why blend?**

- Momentum is purely backward-looking: it works well in trending markets but reverses sharply.
- Macro regime is forward-looking: it adjusts before sentiment turns but may be noisy.
- A blend captures both: momentum provides high-frequency signal; regime provides context.

**Optimal alpha** varies by market environment and is not stable over time.
The sensitivity analysis helps you understand the trade-off for your selected universe and period.
        """)
