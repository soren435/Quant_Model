"""
UI — Engine 1: Historical Strategy Model.
Tab renders cross-sectional momentum, dual momentum, and inverse-vol strategies
against an equal-weight benchmark.
"""
from __future__ import annotations
import pandas as pd
import streamlit as st

from src.data.loader import download_prices
from src.engines.historical import run_historical_engines, walk_forward_validation
from src.analytics.risk import drawdown_series
from src.visualization.charts import (
    plot_cumulative_returns,
    plot_drawdown,
    plot_bar_returns,
    plot_monthly_returns_heatmap,
)
from src.utils.formatting import format_pct, format_number


# ── Defaults ───────────────────────────────────────────────────────────────────

_DEFAULT_UNIVERSE = ["SPY", "QQQ", "IEF", "GLD", "AGG"]
_STAT_LABELS = {
    "Annualized Return":     "Ann. Return",
    "Annualized Volatility": "Ann. Vol",
    "Sharpe Ratio":          "Sharpe",
    "Sortino Ratio":         "Sortino",
    "Max Drawdown":          "Max DD",
    "Calmar Ratio":          "Calmar",
    "Cumulative Return":     "Total Return",
}


def render_engine_historical(
    cfg: dict,
    start_str: str,
    end_str: str,
    rf_annual: float,
    lang: str = "en",
) -> None:
    st.header("📈 Engine 1 — Historical Strategy Model")
    st.caption(
        "Systematic strategies driven entirely by historical price data. "
        "No look-ahead bias — signals are always formed on past data and applied to the next period."
    )

    # ── Sidebar controls ───────────────────────────────────────────────────────
    with st.expander("⚙️ Strategy Configuration", expanded=True):
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            all_tickers = (
                cfg["tickers"].get("equities", [])
                + cfg["tickers"].get("bonds", [])
                + cfg["tickers"].get("alternatives", [])
            )
            universe = st.multiselect(
                "Asset universe",
                options=sorted(set(all_tickers)),
                default=_DEFAULT_UNIVERSE,
                help="Tickers the strategies can invest in.",
            )

        with col_b:
            lookback = st.slider(
                "Momentum lookback (months)", min_value=3, max_value=24, value=12, step=1
            )
            top_n = st.slider(
                "Top-N assets to hold", min_value=1, max_value=min(10, len(universe) if universe else 5), value=3
            )

        with col_c:
            risky = st.selectbox("Dual Momentum — risky asset", options=universe or ["SPY"], index=0)
            safe  = st.selectbox(
                "Dual Momentum — safe asset",
                options=[t for t in universe if t != risky] or ["AGG"],
                index=0,
            )
            cash  = st.selectbox(
                "Dual Momentum — cash asset",
                options=[t for t in universe if t not in {risky, safe}] or ["SHY"],
                index=0,
            )

    if not universe:
        st.warning("Select at least 2 tickers to run the strategies.")
        return

    if len(universe) < 2:
        st.warning("XS Momentum and Inverse Vol require at least 2 assets. Add more tickers.")

    # ── Data ──────────────────────────────────────────────────────────────────
    with st.spinner("Downloading price data…"):
        prices = download_prices(tuple(sorted(universe)), start_str, end_str)

    if prices.empty:
        st.error("No price data returned. Check your tickers and date range.")
        return

    # ── Run engines ───────────────────────────────────────────────────────────
    with st.spinner("Running strategies…"):
        results = run_historical_engines(
            prices,
            rf_annual=rf_annual,
            lookback_months=lookback,
            top_n=top_n,
            risky=risky,
            safe=safe,
            cash=cash,
        )

    if not results:
        st.warning("Strategies produced no results. Try a longer date range or different assets.")
        return

    # ── KPI row ───────────────────────────────────────────────────────────────
    st.subheader("Strategy Comparison")
    kpi_cols = st.columns(len(results))

    for col, (name, res) in zip(kpi_cols, results.items()):
        s = res["stats"]
        col.metric(
            label=name,
            value=format_pct(s.get("Annualized Return", 0)),
            delta=f"Sharpe {s.get('Sharpe Ratio', 0):.2f}",
        )

    # ── Cumulative returns ────────────────────────────────────────────────────
    cum_df = pd.DataFrame({name: res["cumulative"] for name, res in results.items()})
    st.plotly_chart(
        plot_cumulative_returns(cum_df, title="Cumulative Returns — Strategy Comparison"),
        use_container_width=True,
    )

    # ── Drawdown ──────────────────────────────────────────────────────────────
    dd_df = pd.DataFrame(
        {name: drawdown_series(res["returns"]) for name, res in results.items()}
    )
    st.plotly_chart(
        plot_drawdown(dd_df, title="Drawdown — Strategy Comparison"),
        use_container_width=True,
    )

    # ── Bar: return comparison ────────────────────────────────────────────────
    col_r, col_s = st.columns(2)
    with col_r:
        st.plotly_chart(
            plot_bar_returns(
                {n: r["stats"] for n, r in results.items()},
                metric="Annualized Return",
                title="Annualized Return",
            ),
            use_container_width=True,
        )
    with col_s:
        st.plotly_chart(
            plot_bar_returns(
                {n: r["stats"] for n, r in results.items()},
                metric="Sharpe Ratio",
                title="Sharpe Ratio",
            ),
            use_container_width=True,
        )

    # ── Performance table ─────────────────────────────────────────────────────
    st.subheader("Full Performance Statistics")
    rows = []
    for name, res in results.items():
        s = res["stats"]
        rows.append({
            "Strategy":     name,
            "Total Return": format_pct(s.get("Cumulative Return", 0)),
            "Ann. Return":  format_pct(s.get("Annualized Return", 0)),
            "Ann. Vol":     format_pct(s.get("Annualized Volatility", 0)),
            "Sharpe":       f"{s.get('Sharpe Ratio', 0):.2f}",
            "Sortino":      f"{s.get('Sortino Ratio', 0):.2f}",
            "Max DD":       format_pct(s.get("Max Drawdown", 0)),
            "Calmar":       f"{s.get('Calmar Ratio', 0):.2f}",
            "Yrs":          f"{s.get('Num Years', 0):.1f}",
        })
    st.dataframe(pd.DataFrame(rows).set_index("Strategy"), use_container_width=True)

    # ── Monthly returns heatmap for best Sharpe strategy ─────────────────────
    best = max(results, key=lambda n: results[n]["stats"].get("Sharpe Ratio", -999))
    st.subheader(f"Monthly Returns — {best}")
    st.plotly_chart(
        plot_monthly_returns_heatmap(results[best]["returns"], title=f"Monthly Returns (%) — {best}"),
        use_container_width=True,
    )

    st.divider()

    # ── Walk-forward validation ───────────────────────────────────────────────
    st.subheader("Walk-Forward Validation")
    st.caption(
        "Split the data into in-sample (train) and out-of-sample (test) periods. "
        "A robust strategy should remain profitable on data it was never calibrated on."
    )

    price_start = prices.index[0].date()
    price_end   = prices.index[-1].date()
    mid_approx  = prices.index[len(prices) // 2].date()

    wf_col1, wf_col2 = st.columns([2, 1])
    with wf_col1:
        split_date = st.date_input(
            "Split date (train | test)",
            value=mid_approx,
            min_value=price_start,
            max_value=price_end,
            help="Data before this date = in-sample (train). Data from here = out-of-sample (test).",
        )
    with wf_col2:
        st.write("")
        run_wf = st.button("▶ Run Walk-Forward", type="primary", use_container_width=True)

    if run_wf:
        split_str = split_date.strftime("%Y-%m-%d")
        with st.spinner("Running walk-forward validation…"):
            wf = walk_forward_validation(
                prices,
                split_date=split_str,
                rf_annual=rf_annual,
                lookback_months=lookback,
                top_n=top_n,
                risky=risky,
                safe=safe,
                cash=cash,
            )

        is_res  = wf["in_sample"]
        oos_res = wf["out_of_sample"]

        if not is_res or not oos_res:
            st.warning("One or both periods produced no results — try adjusting the split date.")
        else:
            st.markdown(
                f"**In-sample:** {price_start} → {split_date} "
                f"({wf['is_months']} months) &nbsp;|&nbsp; "
                f"**Out-of-sample:** {split_date} → {price_end} "
                f"({wf['oos_months']} months)"
            )

            # Side-by-side Sharpe comparison
            st.markdown("##### Sharpe Ratio: In-sample vs Out-of-sample")
            strategies = sorted(set(list(is_res.keys()) + list(oos_res.keys())))
            sharpe_rows = []
            for name in strategies:
                is_sharpe  = is_res.get(name,  {}).get("stats", {}).get("Sharpe Ratio", None)
                oos_sharpe = oos_res.get(name, {}).get("stats", {}).get("Sharpe Ratio", None)
                decay = None
                if is_sharpe is not None and oos_sharpe is not None and is_sharpe != 0:
                    decay = (oos_sharpe - is_sharpe) / abs(is_sharpe) * 100
                sharpe_rows.append({
                    "Strategy":        name,
                    "In-sample":       f"{is_sharpe:.2f}"  if is_sharpe  is not None else "—",
                    "Out-of-sample":   f"{oos_sharpe:.2f}" if oos_sharpe is not None else "—",
                    "Decay":           f"{decay:+.0f}%" if decay is not None else "—",
                    "Verdict":         (
                        "✅ Robust"   if oos_sharpe is not None and oos_sharpe > 0.3 else
                        "⚠️ Marginal" if oos_sharpe is not None and oos_sharpe > 0.0 else
                        "❌ Weak"
                    ),
                })
            st.dataframe(pd.DataFrame(sharpe_rows).set_index("Strategy"), use_container_width=True)

            # Full stats comparison table
            with st.expander("Full statistics comparison"):
                full_rows = []
                for name in strategies:
                    for period_label, period_res in [("In-sample", is_res), ("Out-of-sample", oos_res)]:
                        s = period_res.get(name, {}).get("stats", {})
                        if s:
                            full_rows.append({
                                "Strategy":    name,
                                "Period":      period_label,
                                "Ann. Return": format_pct(s.get("Annualized Return", 0)),
                                "Ann. Vol":    format_pct(s.get("Annualized Volatility", 0)),
                                "Sharpe":      f"{s.get('Sharpe Ratio', 0):.2f}",
                                "Max DD":      format_pct(s.get("Max Drawdown", 0)),
                                "Yrs":         f"{s.get('Num Years', 0):.1f}",
                            })
                st.dataframe(
                    pd.DataFrame(full_rows).set_index(["Strategy", "Period"]),
                    use_container_width=True,
                )

            # OOS cumulative chart
            oos_cum = pd.DataFrame({n: r["cumulative"] for n, r in oos_res.items()})
            st.plotly_chart(
                plot_cumulative_returns(oos_cum, title="Out-of-Sample Cumulative Returns"),
                use_container_width=True,
            )

    # ── Methodology note ──────────────────────────────────────────────────────
    with st.expander("📖 Methodology"):
        st.markdown("""
**XS Momentum** (cross-sectional / relative momentum)
- Each month-end, rank all assets by their trailing *lookback* return (skipping 1 month to avoid reversal).
- Go equal-weight long in the top-N ranked assets for the next calendar month.
- Academic basis: Jegadeesh & Titman (1993). Momentum premium documented across 200+ years.

**Dual Momentum** (Antonacci 2014)
- Combines *relative* momentum (which asset wins?) with *absolute* momentum (is it beating cash?).
- If the risky asset beats cash AND beats the safe asset → hold risky.
- If risky beats cash but not safe → hold safe. Otherwise → hold cash.
- Aims to capture equity upside while rotating out before large drawdowns.

**Inverse Volatility**
- Each month, estimate each asset's trailing volatility. Weight by 1/σ, normalized to 100%.
- Lower-volatility assets receive higher weight → improves risk-adjusted returns without explicit optimization.
- Naturally defensive during market stress (safe assets have low vol → get higher weight).

**Equal Weight** (benchmark)
- Equal weight all assets in the universe, rebalanced monthly.
- A classic, difficult-to-beat benchmark for momentum and risk models.
        """)
