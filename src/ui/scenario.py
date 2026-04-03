"""
Scenario & Stress Analysis — page rendering.

Structure:
  1. Description
  2a. Custom Shock Calculator (user inputs allocation + shocks)
  2b. Historical Stress Periods (select a known crisis episode)
"""
import pandas as pd
import streamlit as st

from src.data.loader import download_prices
from src.analytics.returns import cumulative_returns_series
from src.analytics.risk import summary_stats
from src.analytics.portfolio import build_portfolio_returns
from src.visualization.charts import plot_cumulative_returns
from src.utils.formatting import format_pct, parse_tickers, parse_weights, get_period_label

SCENARIOS = {
    "2008 Financial Crisis": ("2008-09-01", "2009-03-09"),
    "COVID Crash (Feb–Mar 2020)": ("2020-02-19", "2020-03-23"),
    "2022 Rate Hike Selloff": ("2022-01-03", "2022-10-13"),
    "Tech Crash 2000–2002": ("2000-03-27", "2002-10-09"),
    "2018 Q4 Correction": ("2018-10-01", "2018-12-24"),
}


def render_scenario(cfg: dict, rf: float, lang: str = "en") -> None:
    """
    Render the Scenario & Stress Analysis page.

    Note: This page uses its own fixed date ranges for historical scenarios,
    so it does not use the global start/end dates for Section 2b.

    Args:
        cfg: Loaded config dict.
        rf:  Annual risk-free rate.
    """
    st.header("Scenario & Stress Analysis")
    st.caption(
        "Two tools: a custom shock calculator for hypothetical scenarios, "
        "and a historical stress-period analyser for real drawdown episodes."
    )

    # ════════════════════════════════════════════════════════════════
    # Section 1: Custom Shock Calculator
    # ════════════════════════════════════════════════════════════════
    st.subheader("Custom Shock Calculator")
    st.markdown(
        "Estimate portfolio impact by applying hypothetical return shocks "
        "to equity and bond allocations."
    )

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        sc_eq_alloc = st.slider("Equity Allocation (%)", 0, 100, 60, 5) / 100
        sc_bd_alloc = 1.0 - sc_eq_alloc
        st.caption(f"Bond allocation: **{sc_bd_alloc * 100:.0f}%**")
        portfolio_value = st.number_input(
            "Portfolio Value (€)", value=100_000, min_value=1_000, step=10_000
        )
    with sc2:
        eq_shock = st.slider("Equity Shock (%)", -70, 30, -30, 5) / 100
    with sc3:
        bd_shock = st.slider("Bond Shock (%)", -40, 20, -10, 5) / 100

    eq_impact = portfolio_value * sc_eq_alloc * eq_shock
    bd_impact = portfolio_value * sc_bd_alloc * bd_shock
    total_impact = eq_impact + bd_impact
    new_value = portfolio_value + total_impact

    res_col, tbl_col = st.columns(2)

    with res_col:
        m_a, m_b = st.columns(2)
        m_a.metric("Value Before", f"€{portfolio_value:,.0f}")
        m_b.metric(
            "Value After",
            f"€{new_value:,.0f}",
            delta=f"€{total_impact:,.0f}",
            delta_color="inverse",
        )
        st.markdown(f"""
| Component | Allocation | Shock | Impact |
|-----------|-----------|-------|--------|
| Equity | {sc_eq_alloc * 100:.0f}% | {eq_shock * 100:.0f}% | €{eq_impact:,.0f} |
| Bonds | {sc_bd_alloc * 100:.0f}% | {bd_shock * 100:.0f}% | €{bd_impact:,.0f} |
| **Total** | | | **€{total_impact:,.0f}** ({format_pct(total_impact / portfolio_value)}) |
""")

    with tbl_col:
        shocks_range = [-0.50, -0.40, -0.30, -0.20, -0.10, 0.0, 0.10, 0.20]
        sensitivity = []
        for sh in shocks_range:
            imp = portfolio_value * sc_eq_alloc * sh + portfolio_value * sc_bd_alloc * bd_shock
            sensitivity.append({
                "Equity Shock": format_pct(sh),
                "Portfolio Impact": f"€{imp:,.0f}",
                "Total Return": format_pct(imp / portfolio_value),
            })
        st.caption(f"Sensitivity to equity shocks (bond shock fixed at {bd_shock * 100:.0f}%)")
        st.dataframe(pd.DataFrame(sensitivity), hide_index=True)

    st.divider()

    # ════════════════════════════════════════════════════════════════
    # Section 2: Historical Stress Periods
    # ════════════════════════════════════════════════════════════════
    st.subheader("Historical Stress Periods")
    st.caption(
        "Analyse a portfolio across a real historical drawdown episode. "
        "Useful for stress-testing diversification assumptions."
    )

    hs_col1, hs_col2 = st.columns([2, 3])

    with hs_col1:
        scenario = st.selectbox("Select Scenario", list(SCENARIOS.keys()))
        hs_tickers_str = st.text_input("Tickers", value="SPY, IEF", key="hs_t")
        hs_weights_str = st.text_input("Weights", value="0.6, 0.4", key="hs_w")

    hs_tickers = parse_tickers(hs_tickers_str)
    hs_weights = parse_weights(hs_weights_str, len(hs_tickers)) if hs_tickers else None

    if not hs_tickers or hs_weights is None:
        with hs_col2:
            st.info("Enter tickers and matching weights to run the scenario.")
        with hs_col1:
            sc_start, sc_end = SCENARIOS[scenario]
            st.caption(f"Period: **{sc_start}** → **{sc_end}**")
            st.caption(f"Duration: **{get_period_label(sc_start, sc_end)}**")
        return

    sc_start, sc_end = SCENARIOS[scenario]

    with st.spinner(f"Loading data for '{scenario}'..."):
        hs_prices = download_prices(tuple(hs_tickers), sc_start, sc_end)

    if hs_prices.empty:
        with hs_col2:
            st.warning(f"No data available for the {scenario} period.")
    else:
        hs_wd = {
            t: w
            for t, w in zip(hs_tickers, hs_weights)
            if t in hs_prices.columns
        }
        if not hs_wd:
            with hs_col2:
                st.error("None of the specified tickers have data for this period.")
        else:
            tot = sum(hs_wd.values())
            hs_wd = {t: w / tot for t, w in hs_wd.items()}

            hs_ret = build_portfolio_returns(hs_prices, hs_wd, "none")
            hs_cum = cumulative_returns_series(hs_ret)
            hs_stats = summary_stats(hs_ret, rf)

            with hs_col2:
                h1, h2, h3 = st.columns(3)
                h1.metric("Period Return", format_pct(hs_stats.get("Cumulative Return", 0)))
                h2.metric("Max Drawdown", format_pct(hs_stats.get("Max Drawdown", 0)))
                h3.metric("Ann. Volatility", format_pct(hs_stats.get("Annualized Volatility", 0)))

                cum_compare = {
                    t: cumulative_returns_series(hs_prices[t].pct_change().dropna())
                    for t in hs_wd
                }
                cum_compare["Portfolio"] = hs_cum

                st.plotly_chart(
                    plot_cumulative_returns(
                        pd.DataFrame(cum_compare),
                        title=f"{scenario} — Cumulative Returns",
                    ),
                )

    with hs_col1:
        st.caption(f"Period: **{sc_start}** → **{sc_end}**")
        st.caption(f"Duration: **{get_period_label(sc_start, sc_end)}**")
