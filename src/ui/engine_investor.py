"""
UI — Engine 4: Investor Profile / Risk Model.
Guides the user through a 5-question risk questionnaire, maps to a profile,
shows the recommended allocation, and backtests it.
"""
from __future__ import annotations
import pandas as pd
import streamlit as st

from src.data.loader import download_prices
from src.engines.investor_profile import (
    InvestorProfile,
    PROFILE_TEMPLATES,
    score_questionnaire,
    profile_from_score,
    backtest_profile_allocation,
    compare_all_profiles,
    efficient_frontier,
)
from src.analytics.risk import drawdown_series
from src.analytics.returns import cumulative_returns_series
from src.visualization.charts import (
    plot_cumulative_returns,
    plot_drawdown,
    plot_allocation_pie,
    plot_bar_returns,
    plot_efficient_frontier,
    COLORS,
)
from src.utils.formatting import format_pct

# Tickers needed: union of all profile allocations
_ALL_PROFILE_TICKERS = tuple(sorted({
    t for p in PROFILE_TEMPLATES for t in p.target_allocation
}))

_RISK_COLOR = {
    "Conservative": "#2563EB",
    "Moderate":     "#16A34A",
    "Balanced":     "#F59E0B",
    "Growth":       "#9333EA",
    "Aggressive":   "#DC2626",
}


def _score_bar_html(score: int, color: str) -> str:
    """Render an HTML progress bar for the risk score."""
    pct = score * 10
    return (
        f"<div style='margin:8px 0;'>"
        f"<div style='display:flex; justify-content:space-between; font-size:0.85rem; color:#475569;'>"
        f"<span>Conservative (1)</span><span>Aggressive (10)</span></div>"
        f"<div style='background:#E2E8F0; border-radius:6px; height:14px; margin-top:4px;'>"
        f"<div style='background:{color}; width:{pct}%; height:14px; border-radius:6px;'></div>"
        f"</div>"
        f"<div style='text-align:center; font-size:1.8rem; font-weight:700; color:{color}; margin-top:4px;'>"
        f"Risk Score: {score}/10</div>"
        f"</div>"
    )


def render_engine_investor(
    cfg: dict,
    start_str: str,
    end_str: str,
    rf_annual: float,
    lang: str = "en",
) -> None:
    st.header("👤 Engine 4 — Investor Profile & Risk Model")
    st.caption(
        "Answer 5 questions to determine your investor profile. "
        "Receive a personalized portfolio allocation and see its historical performance."
    )

    # ── Step 1: Questionnaire ─────────────────────────────────────────────────
    st.subheader("Step 1 — Risk Questionnaire")

    with st.form("risk_questionnaire"):
        st.markdown("##### How would you describe your investment situation?")

        q_col1, q_col2 = st.columns(2)

        with q_col1:
            time_horizon = st.select_slider(
                "1. Investment time horizon",
                options=[1, 3, 5, 10, 15, 20, 30],
                value=10,
                format_func=lambda x: f"{x} year{'s' if x > 1 else ''}",
                help="How long until you need this money?",
            )

            loss_tolerance = st.select_slider(
                "2. Maximum acceptable loss in a single year",
                options=[5, 10, 15, 20, 30, 40, 50],
                value=20,
                format_func=lambda x: f"-{x}%",
                help="If your portfolio fell by this amount in a year, you would not panic-sell.",
            )

            income_need = st.radio(
                "3. Income requirement from this portfolio",
                options=["none", "low", "medium", "high"],
                index=0,
                format_func=lambda x: x.capitalize(),
                horizontal=True,
                help="'High' = you rely on portfolio income now or soon.",
            )

        with q_col2:
            experience = st.radio(
                "4. Investment experience",
                options=["beginner", "intermediate", "advanced"],
                index=1,
                format_func=lambda x: x.capitalize(),
                help="How familiar are you with financial markets and portfolio management?",
            )

            primary_goal = st.radio(
                "5. Primary investment goal",
                options=["preserve", "income", "balanced", "grow", "aggressive"],
                index=2,
                format_func=lambda x: {
                    "preserve":   "Preserve capital",
                    "income":     "Generate income",
                    "balanced":   "Balanced growth",
                    "grow":       "Long-term growth",
                    "aggressive": "Maximum growth",
                }[x],
                help="What outcome matters most to you?",
            )

        submitted = st.form_submit_button("Calculate my investor profile →", type="primary", use_container_width=True)

    if not submitted:
        # Show all profiles as reference
        st.subheader("Reference: All Investor Profiles")
        for p in PROFILE_TEMPLATES:
            color = _RISK_COLOR.get(p.label, "#94A3B8")
            with st.expander(f"**{p.label}** — Risk Score {p.score_range[0]}–{p.score_range[1]}"):
                st.markdown(
                    f"<span style='color:{color}; font-weight:600;'>{p.description}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    "Allocation: " + " | ".join(f"{t} {w*100:.0f}%" for t, w in p.target_allocation.items())
                )
                st.caption(f"Max drawdown tolerance: {p.max_drawdown_tolerance*100:.0f}%")
        return

    # ── Step 2: Score + profile ────────────────────────────────────────────────
    score = score_questionnaire(
        time_horizon_years=time_horizon,
        loss_tolerance_pct=loss_tolerance,
        income_need=income_need,
        experience=experience,
        primary_goal=primary_goal,
    )
    profile = profile_from_score(score, time_horizon_years=time_horizon)
    color = _RISK_COLOR.get(profile.label, "#94A3B8")

    st.divider()
    st.subheader("Step 2 — Your Investor Profile")

    st.markdown(_score_bar_html(score, color), unsafe_allow_html=True)

    prof_col, alloc_col = st.columns([1, 1])

    with prof_col:
        st.markdown(
            f"<h3 style='color:{color}; margin:0;'>{profile.label}</h3>",
            unsafe_allow_html=True,
        )
        st.write(profile.description)
        st.markdown(f"**Max drawdown tolerance:** {profile.max_drawdown_tolerance*100:.0f}%")
        st.markdown(f"**Investment horizon:** {profile.time_horizon_years} years")

    with alloc_col:
        st.plotly_chart(
            plot_allocation_pie(
                profile.target_allocation,
                title=f"{profile.label} — Target Allocation",
            ),
            use_container_width=True,
        )

    st.divider()

    # ── Step 3: Backtest ──────────────────────────────────────────────────────
    st.subheader("Step 3 — Historical Performance of Your Portfolio")

    with st.spinner("Downloading price data…"):
        prices = download_prices(_ALL_PROFILE_TICKERS, start_str, end_str)

    if prices.empty:
        st.error("Could not download price data.")
        return

    with st.spinner("Backtesting…"):
        result = backtest_profile_allocation(prices, profile, rf_annual=rf_annual)

    if not result:
        st.warning("Backtest returned no data. Try a longer date range.")
        return

    s = result["stats"]
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Return",  format_pct(s.get("Cumulative Return", 0)))
    k2.metric("Ann. Return",   format_pct(s.get("Annualized Return", 0)))
    k3.metric("Ann. Vol",      format_pct(s.get("Annualized Volatility", 0)))
    k4.metric("Sharpe",        f"{s.get('Sharpe Ratio', 0):.2f}")
    k5.metric("Max Drawdown",  format_pct(s.get("Max Drawdown", 0)))

    # Cumulative vs SPY
    cum_dict: dict[str, pd.Series] = {profile.label: result["cumulative"]}
    if "SPY" in prices.columns:
        spy_ret = prices["SPY"].pct_change().dropna()
        spy_aligned = spy_ret.loc[result["cumulative"].index[0]:]
        cum_dict["SPY (Equity benchmark)"] = cumulative_returns_series(spy_aligned)
    if "IEF" in prices.columns:
        ief_ret = prices["IEF"].pct_change().dropna()
        ief_aligned = ief_ret.loc[result["cumulative"].index[0]:]
        cum_dict["IEF (Bond benchmark)"] = cumulative_returns_series(ief_aligned)

    st.plotly_chart(
        plot_cumulative_returns(
            pd.DataFrame(cum_dict),
            title=f"{profile.label} Portfolio — Cumulative Returns",
        ),
        use_container_width=True,
    )

    st.plotly_chart(
        plot_drawdown(
            drawdown_series(result["returns"]).rename(profile.label).to_frame(),
            title=f"{profile.label} — Drawdown",
        ),
        use_container_width=True,
    )

    st.divider()

    # ── Step 4: Compare all profiles ──────────────────────────────────────────
    st.subheader("Step 4 — Profile Comparison")
    st.caption("How does your profile compare to the others over the same period?")

    show_comparison = st.button("Compare all 5 profiles", type="secondary")
    if show_comparison:
        with st.spinner("Backtesting all profiles…"):
            all_results = compare_all_profiles(prices, rf_annual=rf_annual)

        if all_results:
            cum_all = pd.DataFrame({name: r["cumulative"] for name, r in all_results.items()})
            st.plotly_chart(
                plot_cumulative_returns(cum_all, title="All Profiles — Cumulative Returns"),
                use_container_width=True,
            )

            st.plotly_chart(
                plot_bar_returns(
                    {n: r["stats"] for n, r in all_results.items()},
                    metric="Sharpe Ratio",
                    title="Sharpe Ratio by Profile",
                ),
                use_container_width=True,
            )

            rows = []
            for name, res in all_results.items():
                ss = res["stats"]
                is_yours = " ← yours" if name == profile.label else ""
                rows.append({
                    "Profile":     name + is_yours,
                    "Total Return": format_pct(ss.get("Cumulative Return", 0)),
                    "Ann. Return":  format_pct(ss.get("Annualized Return", 0)),
                    "Ann. Vol":     format_pct(ss.get("Annualized Volatility", 0)),
                    "Sharpe":       f"{ss.get('Sharpe Ratio', 0):.2f}",
                    "Max DD":       format_pct(ss.get("Max Drawdown", 0)),
                })
            st.dataframe(pd.DataFrame(rows).set_index("Profile"), use_container_width=True)

    st.divider()

    # ── Step 5: Efficient frontier ────────────────────────────────────────────
    st.subheader("Step 5 — Efficient Frontier")
    st.caption(
        "Where does your profile sit in risk/return space? "
        "The frontier shows every possible combination of your assets. "
        "The optimiser finds the portfolio that maximises Sharpe ratio."
    )

    ef_tickers = list({t for t in profile.target_allocation if t in prices.columns})
    target_vol_input = abs(profile.max_drawdown_tolerance) / 2  # rough proxy

    show_ef = st.button("📐 Run Efficient Frontier", type="primary", use_container_width=False)
    if show_ef:
        with st.spinner("Optimising… (300 portfolios + scipy SLSQP)"):
            try:
                ef = efficient_frontier(
                    prices[ef_tickers],
                    rf_annual=rf_annual,
                    n_portfolios=400,
                    target_vol=target_vol_input,
                )
            except Exception as exc:
                st.error(f"Optimisation failed: {exc}")
                ef = {}

        if ef:
            # Profile's own vol/ret for comparison dot
            profile_vol = s.get("Annualized Volatility")
            profile_ret = s.get("Annualized Return")

            st.plotly_chart(
                plot_efficient_frontier(
                    ef,
                    profile_vol=profile_vol,
                    profile_ret=profile_ret,
                    profile_label=f"{profile.label} (current)",
                    title=f"Efficient Frontier — {', '.join(ef_tickers)}",
                ),
                use_container_width=True,
            )

            # Show optimised allocations
            opt_col1, opt_col2, opt_col3 = st.columns(3)
            for col, key, label in [
                (opt_col1, "max_sharpe", "Max Sharpe"),
                (opt_col2, "min_vol",    "Min Volatility"),
                (opt_col3, "target_vol", f"Target Vol ({target_vol_input*100:.0f}%)"),
            ]:
                port = ef.get(key)
                if not port:
                    col.caption(f"_{label}: not available_")
                    continue
                with col:
                    st.markdown(f"**{label}**")
                    st.metric("Ann. Return", format_pct(port["ret"]))
                    st.metric("Ann. Vol",    format_pct(port["vol"]))
                    st.metric("Sharpe",      f"{port['sharpe']:.2f}")
                    w_clean = {t: w for t, w in port["weights"].items() if w > 0.01}
                    st.plotly_chart(
                        plot_allocation_pie(w_clean, title=""),
                        use_container_width=True,
                    )

    with st.expander("📖 How risk scoring works"):
        st.markdown("""
The questionnaire assigns points across 5 dimensions:

| Question | Max pts | Logic |
|----------|---------|-------|
| Time horizon | 3 | Longer horizon → higher score (can ride out volatility) |
| Loss tolerance | 3 | Higher tolerance → higher score |
| Income need | 2 | Low/no income need → higher score |
| Experience | 1 | Advanced → higher score |
| Primary goal | 1 | Aggressive growth → higher score |

**Total: 10 points → scaled 1–10**

Profile mapping:
- 1–3: Conservative
- 4–5: Moderate
- 6: Balanced
- 7–8: Growth
- 9–10: Aggressive

All allocations use liquid, diversified ETFs available globally via yfinance.
Allocations are rebalanced monthly to target weights.
        """)
