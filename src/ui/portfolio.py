"""
Portfolio Analysis — institutional-quality page rendering.

Structure:
  1. Description
  2. User inputs (tickers, weights, preset, benchmark, rebalance frequency)
  3. KPI summary (7 metrics)
  4. Equity curve vs benchmark
  5. Allocation donut + drawdown charts
  6. Return attribution bar chart
  7. Risk diagnostics table (beta, tracking error, IR)
  8. Correlation matrix
  9. Rolling volatility
  10. Insight summary
"""
import pandas as pd
import streamlit as st

from src.data.loader import download_prices
from src.analytics.returns import cumulative_returns_series
from src.analytics.risk import (
    drawdown_series,
    rolling_volatility,
    summary_stats,
    beta,
    tracking_error,
    information_ratio,
)
from src.analytics.portfolio import (
    build_portfolio_returns,
    correlation_matrix,
    contribution_to_return,
)
from src.visualization.charts import (
    plot_cumulative_returns,
    plot_drawdown,
    plot_rolling_metric,
    plot_allocation_pie,
    plot_correlation_heatmap,
    plot_contribution_bar,
)
from src.utils.formatting import format_pct, format_number, parse_tickers, parse_weights

# ── Portfolio presets ──────────────────────────────────────────────────────────

PRESETS: dict[str, dict | None] = {
    "Custom": None,
    "60/40 (SPY / IEF)": {"tickers": "SPY, IEF", "weights": "0.60, 0.40"},
    "Growth (SPY / QQQ / IEF)": {"tickers": "SPY, QQQ, IEF", "weights": "0.50, 0.30, 0.20"},
    "Defensive (SPY / TLT / AGG)": {"tickers": "SPY, TLT, AGG", "weights": "0.30, 0.40, 0.30"},
}


def render_portfolio(cfg: dict, start_str: str, end_str: str, rf: float, lang: str = "en") -> None:
    """
    Render the Portfolio Analysis page.

    Args:
        cfg:       Loaded config dict.
        start_str: Start date string 'YYYY-MM-DD'.
        end_str:   End date string 'YYYY-MM-DD'.
        rf:        Annual risk-free rate.
    """
    st.header("Portfolio Analysis")
    st.caption(
        "Build a custom portfolio, compare it against a benchmark, "
        "and evaluate risk-adjusted performance with institutional-grade metrics."
    )

    # ── 1. Inputs ──────────────────────────────────────────────────────────────
    st.subheader("Portfolio Configuration")

    col_preset, col_rebal, col_bench = st.columns([2, 1, 1])
    with col_preset:
        preset = st.selectbox("Preset", list(PRESETS.keys()), index=0)
    with col_rebal:
        rebal = st.selectbox("Rebalance", ["monthly", "quarterly", "none"], index=0)
    with col_bench:
        bench = st.text_input(
            "Benchmark",
            value=cfg["default_portfolio"]["benchmark"],
        ).strip().upper()

    # Default values — change when preset changes (key includes preset name)
    if preset != "Custom" and PRESETS[preset] is not None:
        preset_data = PRESETS[preset]
        default_tickers = preset_data["tickers"]
        default_weights = preset_data["weights"]
    else:
        default_tickers = ", ".join(cfg["default_portfolio"]["tickers"])
        default_weights = ", ".join(str(w) for w in cfg["default_portfolio"]["weights"])

    col_t, col_w = st.columns(2)
    with col_t:
        pt_str = st.text_input(
            "Tickers (comma-separated)",
            value=default_tickers,
            key=f"pt_{preset}",
        )
    with col_w:
        pw_str = st.text_input(
            "Weights (comma-separated, will be normalized)",
            value=default_weights,
            key=f"pw_{preset}",
            help="Use decimals (0.6, 0.4) or integers (60, 40)",
        )

    # ── 2. Parse & validate ────────────────────────────────────────────────────
    pt = parse_tickers(pt_str)
    pw = parse_weights(pw_str, len(pt)) if pt else None

    if not pt:
        st.info("Enter portfolio tickers to continue.")
        return
    if pw is None:
        st.error(f"Provide exactly {len(pt)} weights matching the number of tickers.")
        return

    weights_dict = dict(zip(pt, pw))

    # ── 3. Download ────────────────────────────────────────────────────────────
    all_dl = list({*pt, bench} if bench else set(pt))
    with st.spinner("Downloading portfolio data..."):
        prices_p = download_prices(tuple(all_dl), start_str, end_str)

    if prices_p.empty:
        st.error("Failed to download data.")
        return

    # Drop tickers with no data and re-normalize weights
    missing_p = [t for t in pt if t not in prices_p.columns]
    if missing_p:
        st.warning(f"No data for: {', '.join(missing_p)} — excluded from portfolio.")
        weights_dict = {t: w for t, w in weights_dict.items() if t in prices_p.columns}
        if not weights_dict:
            st.error("No valid tickers in portfolio.")
            return
        total = sum(weights_dict.values())
        weights_dict = {t: w / total for t, w in weights_dict.items()}

    # ── 4. Build portfolio ─────────────────────────────────────────────────────
    port_ret = build_portfolio_returns(prices_p, weights_dict, rebal)
    if port_ret.empty:
        st.error("Could not build portfolio. Check ticker data availability.")
        return

    port_cum = cumulative_returns_series(port_ret)
    port_stats = summary_stats(port_ret, rf)
    port_dd = drawdown_series(port_ret)

    bench_ret = bench_cum = bench_dd = None
    if bench and bench in prices_p.columns:
        bench_ret = prices_p[bench].pct_change().dropna()
        bench_cum = cumulative_returns_series(bench_ret)
        bench_dd = drawdown_series(bench_ret)

    # ── 5. KPI Cards ───────────────────────────────────────────────────────────
    st.subheader("Portfolio Metrics")

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    r1c1.metric("Period Return", format_pct(port_stats.get("Cumulative Return", 0)))
    r1c2.metric("Ann. Return (CAGR)", format_pct(port_stats.get("Annualized Return", 0)))
    r1c3.metric("Ann. Volatility", format_pct(port_stats.get("Annualized Volatility", 0)))
    r1c4.metric("Max Drawdown", format_pct(port_stats.get("Max Drawdown", 0)))

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    r2c1.metric("Sharpe Ratio", format_number(port_stats.get("Sharpe Ratio", 0)))
    r2c2.metric("Sortino Ratio", format_number(port_stats.get("Sortino Ratio", 0)))
    r2c3.metric("Calmar Ratio", format_number(port_stats.get("Calmar Ratio", 0)))
    num_yrs = port_stats.get("Num Years", 0)
    r2c4.metric("Period Length", f"{num_yrs:.1f} yrs")

    # ── 6. Equity Curve ────────────────────────────────────────────────────────
    st.subheader("Growth of Portfolio vs Benchmark")
    cum_df = pd.DataFrame({"Portfolio": port_cum})
    if bench_cum is not None:
        cum_df[bench] = bench_cum.reindex(port_cum.index).ffill()
    st.plotly_chart(plot_cumulative_returns(cum_df), use_container_width=True)

    # ── 7. Drawdown & Allocation ───────────────────────────────────────────────
    col_dd, col_alloc = st.columns([3, 2])

    with col_dd:
        st.subheader("Drawdown")
        dd_df = pd.DataFrame({"Portfolio": port_dd})
        if bench_dd is not None:
            dd_df[bench] = bench_dd.reindex(port_dd.index).ffill()
        st.plotly_chart(plot_drawdown(dd_df), use_container_width=True)

    with col_alloc:
        st.subheader("Target Allocation")
        st.plotly_chart(plot_allocation_pie(weights_dict), use_container_width=True)

    # ── 8. Return Attribution ──────────────────────────────────────────────────
    st.subheader("Return Contribution by Asset")
    contribs = contribution_to_return(prices_p, weights_dict)
    if contribs:
        col_contr, col_alloc_tbl = st.columns([3, 2])
        with col_contr:
            st.plotly_chart(
                plot_contribution_bar(contribs),
            )
        with col_alloc_tbl:
            st.caption("Allocation & Attribution")
            tbl_rows = []
            for t, w in weights_dict.items():
                tbl_rows.append({
                    "Ticker": t,
                    "Weight": format_pct(w),
                    "Contribution": format_pct(contribs.get(t, 0)),
                })
            st.dataframe(
                pd.DataFrame(tbl_rows).set_index("Ticker"),
            )

    # ── 9. Benchmark-Relative Risk Diagnostics ─────────────────────────────────
    if bench_ret is not None:
        st.subheader(f"Risk Diagnostics vs {bench}")
        port_beta = beta(port_ret, bench_ret)
        te = tracking_error(port_ret, bench_ret)
        ir = information_ratio(port_ret, bench_ret)

        rd1, rd2, rd3 = st.columns(3)
        rd1.metric("Beta", format_number(port_beta) if not pd.isna(port_beta) else "N/A")
        rd2.metric("Tracking Error", format_pct(te) if not pd.isna(te) else "N/A")
        rd3.metric("Information Ratio", format_number(ir) if not pd.isna(ir) else "N/A")

    # ── 10. Correlation Matrix ─────────────────────────────────────────────────
    valid_tickers = list(weights_dict.keys())
    if len(valid_tickers) > 1:
        st.subheader("Correlation Matrix (Daily Returns)")
        corr = correlation_matrix(prices_p[valid_tickers])
        st.plotly_chart(plot_correlation_heatmap(corr), use_container_width=True)

    # ── 11. Rolling Volatility ─────────────────────────────────────────────────
    st.subheader("Rolling 21-Day Volatility (Annualized)")
    rv_df = pd.DataFrame({"Portfolio": rolling_volatility(port_ret, window=21)})
    if bench_ret is not None:
        rv_df[bench] = rolling_volatility(bench_ret, window=21).reindex(rv_df.index).ffill()
    st.plotly_chart(
        plot_rolling_metric(rv_df, as_pct=True, y_label="Annualized Volatility (%)"),
    )

    # ── 12. Insight Summary ────────────────────────────────────────────────────
    st.subheader("Portfolio Insights")
    _render_portfolio_insights(port_stats, bench_ret, bench, port_beta, te, ir)


def _render_portfolio_insights(
    stats: dict,
    bench_ret: pd.Series | None,
    bench_name: str,
    port_beta: float,
    te: float,
    ir: float,
) -> None:
    """Render a short rule-based insight block below the portfolio charts."""
    lines = []

    ann_ret = stats.get("Annualized Return", 0)
    ann_vol = stats.get("Annualized Volatility", 0)
    sharpe = stats.get("Sharpe Ratio", 0)
    mdd = stats.get("Max Drawdown", 0)

    if sharpe > 1.0:
        lines.append(f"- Sharpe ratio of **{sharpe:.2f}** indicates strong risk-adjusted returns.")
    elif sharpe > 0.5:
        lines.append(f"- Sharpe ratio of **{sharpe:.2f}** is acceptable but leaves room for improvement.")
    else:
        lines.append(f"- Sharpe ratio of **{sharpe:.2f}** is low — returns are not well compensating for volatility.")

    if mdd < -0.20:
        lines.append(f"- Max drawdown of **{format_pct(mdd)}** is significant. Consider whether this level of loss is acceptable.")
    else:
        lines.append(f"- Max drawdown of **{format_pct(mdd)}** is within a moderate range.")

    if bench_ret is not None and not pd.isna(port_beta):
        if port_beta > 1.1:
            lines.append(f"- Beta of **{port_beta:.2f}** vs {bench_name} means the portfolio amplifies market moves.")
        elif port_beta < 0.8:
            lines.append(f"- Beta of **{port_beta:.2f}** vs {bench_name} means the portfolio is more defensive than the market.")
        else:
            lines.append(f"- Beta of **{port_beta:.2f}** vs {bench_name} is close to market-like exposure.")

        if not pd.isna(ir):
            if ir > 0.5:
                lines.append(f"- Information ratio of **{ir:.2f}** suggests consistent active value vs {bench_name}.")
            elif ir < 0:
                lines.append(f"- Information ratio of **{ir:.2f}** indicates the portfolio underperformed {bench_name} on a risk-adjusted basis.")

    if not lines:
        lines.append("_Not enough data for insight generation._")

    lines.append("")
    lines.append("_This summary is rule-based and for analytical context only — not investment advice._")

    st.markdown("\n".join(lines))
