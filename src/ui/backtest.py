"""
Strategy Backtest — page rendering.

Structure:
  1. Description
  2. User inputs (assets, rebalance frequency, trend filter settings)
  3. Cumulative returns chart (strategy comparison)
  4. Performance summary table
  5. Drawdown comparison chart
  6. Annualized return bar chart
"""
import pandas as pd
import streamlit as st

from src.data.loader import download_prices
from src.analytics.returns import cumulative_returns_series
from src.analytics.risk import drawdown_series, summary_stats
from src.analytics.backtest import run_strategies, trend_filter_returns
from src.visualization.charts import (
    plot_cumulative_returns,
    plot_drawdown,
    plot_bar_returns,
)
from src.utils.formatting import format_pct, format_number


def render_backtest(cfg: dict, start_str: str, end_str: str, rf: float, lang: str = "en") -> None:
    """
    Render the Strategy Backtest page.

    Args:
        cfg:       Loaded config dict.
        start_str: Start date string 'YYYY-MM-DD'.
        end_str:   End date string 'YYYY-MM-DD'.
        rf:        Annual risk-free rate.
    """
    st.header("Strategy Backtest")
    st.caption(
        "Compare fixed-allocation strategies and a simple trend-following filter "
        "over the selected date range."
    )

    # ── 1. Inputs ──────────────────────────────────────────────────────────────
    col_bt1, col_bt2 = st.columns(2)

    with col_bt1:
        st.subheader("Assets")
        bt_eq = st.text_input(
            "Equity ETF", value=cfg["default_backtest"]["equity_ticker"], key="bt_eq"
        ).strip().upper()
        bt_bond = st.text_input(
            "Bond ETF", value=cfg["default_backtest"]["bond_ticker"], key="bt_bond"
        ).strip().upper()
        bt_rebal = st.selectbox("Rebalance Freq", ["monthly", "quarterly", "none"], key="bt_rb")

    with col_bt2:
        st.subheader("Trend Filter (Moving Average)")
        bt_risk = st.text_input(
            "Signal Ticker",
            value=cfg["default_backtest"]["risk_ticker"],
            help="Ticker whose price vs. MA determines risk-on/off.",
            key="bt_risk",
        ).strip().upper()
        bt_ma = st.number_input(
            "MA Window (days)",
            value=cfg["default_backtest"]["ma_window"],
            min_value=20, max_value=500, step=10,
        )
        bt_eq_w = st.slider("Equity weight (risk-on)", 0.0, 1.0, 0.6, 0.05)

    # ── 2. Download ────────────────────────────────────────────────────────────
    bt_tickers = list({bt_eq, bt_bond, bt_risk})
    with st.spinner("Downloading backtest data..."):
        bt_prices = download_prices(tuple(bt_tickers), start_str, end_str)

    if bt_prices.empty:
        st.error("Could not download backtest data.")
        return
    if bt_eq not in bt_prices.columns or bt_bond not in bt_prices.columns:
        st.error(f"Missing data for equity ({bt_eq}) or bond ({bt_bond}) ticker.")
        return

    # ── 3. Run Strategies ──────────────────────────────────────────────────────
    strategies = {
        f"100% {bt_eq}": {bt_eq: 1.0},
        f"80/20 {bt_eq}/{bt_bond}": {bt_eq: 0.8, bt_bond: 0.2},
        f"60/40 {bt_eq}/{bt_bond}": {bt_eq: 0.6, bt_bond: 0.4},
        f"40/60 {bt_eq}/{bt_bond}": {bt_eq: 0.4, bt_bond: 0.6},
        f"100% {bt_bond}": {bt_bond: 1.0},
    }

    bt_results = run_strategies(bt_prices, strategies, bt_rebal, rf)

    if bt_risk in bt_prices.columns:
        trend_ret = trend_filter_returns(
            bt_prices, bt_eq, bt_bond, bt_risk,
            ma_window=bt_ma,
            equity_weight=bt_eq_w,
            bond_weight=1.0 - bt_eq_w,
        )
        if not trend_ret.empty and bt_results:
            aligned = trend_ret.reindex(bt_results["returns"].index)
            bt_results["returns"][trend_ret.name] = aligned
            bt_results["cumulative"][trend_ret.name] = cumulative_returns_series(
                aligned.dropna()
            ).reindex(bt_results["cumulative"].index)
            bt_results["stats"][trend_ret.name] = summary_stats(aligned.dropna(), rf)

    if not bt_results:
        st.error("Backtest failed. Check ticker availability.")
        return

    # ── 4. Cumulative Returns ──────────────────────────────────────────────────
    st.subheader("Cumulative Returns — Strategy Comparison")
    st.plotly_chart(
        plot_cumulative_returns(bt_results["cumulative"], title="Strategy Comparison"),
    )

    # ── 5. Performance Table ───────────────────────────────────────────────────
    st.subheader("Performance Summary")
    table_rows = []
    for name, s in bt_results["stats"].items():
        if s:
            table_rows.append({
                "Strategy": name,
                "Cum. Return": format_pct(s.get("Cumulative Return", 0)),
                "Ann. Return": format_pct(s.get("Annualized Return", 0)),
                "Ann. Vol": format_pct(s.get("Annualized Volatility", 0)),
                "Sharpe": format_number(s.get("Sharpe Ratio", 0)),
                "Sortino": format_number(s.get("Sortino Ratio", 0)),
                "Max DD": format_pct(s.get("Max Drawdown", 0)),
                "Calmar": format_number(s.get("Calmar Ratio", 0)),
            })
    if table_rows:
        st.dataframe(
            pd.DataFrame(table_rows).set_index("Strategy"),
        )

    # ── 6. Drawdown & Return Bar Charts ────────────────────────────────────────
    col_dd, col_bar = st.columns(2)

    with col_dd:
        st.subheader("Drawdown Comparison")
        dd_bt = pd.DataFrame({
            name: drawdown_series(bt_results["returns"][name].dropna())
            for name in bt_results["returns"].columns
        })
        st.plotly_chart(plot_drawdown(dd_bt, title="Drawdown by Strategy"), use_container_width=True)

    with col_bar:
        st.subheader("Annualized Return by Strategy")
        st.plotly_chart(
            plot_bar_returns(bt_results["stats"], metric="Annualized Return"),
        )
