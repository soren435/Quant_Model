"""
Fact Box component — reusable educational panel for the Portfolio Builder.

Renders inside a Streamlit expander with four metric definitions and
realistic historical ranges for return, volatility, drawdown, and Sharpe Ratio.
"""
import streamlit as st


def render_fact_box() -> None:
    """
    Render an educational fact box explaining the four key portfolio metrics
    with realistic historical ranges grouped by asset class / risk profile.
    """
    with st.expander("📖 What do these metrics mean?", expanded=False):

        col_ret, col_vol, col_dd, col_sr = st.columns(4)

        with col_ret:
            st.markdown("**📈 Return**")
            st.markdown(
                "The annualized gain on your investment over time — often expressed as "
                "compound annual growth rate (CAGR). Higher targets require taking more risk."
            )
            st.markdown(
                """
| Asset class | Typical range |
|-------------|--------------|
| Cash / short bonds | 1–3 % |
| Bonds (investment grade) | 2–5 % |
| Broad equities | 7–10 % |
| US Tech / Growth | 10–15 % |
                """
            )

        with col_vol:
            st.markdown("**〰️ Volatility**")
            st.markdown(
                "Annualized standard deviation of daily returns. Measures how much the "
                "portfolio value fluctuates — not just losses, but all price swings."
            )
            st.markdown(
                """
| Risk level | Typical range |
|------------|--------------|
| Low (bonds, cash) | 5–10 % |
| Medium (balanced) | 10–15 % |
| High (equity heavy) | 15–25 % |
| Very high (tech/EM) | 25 %+ |
                """
            )

        with col_dd:
            st.markdown("**📉 Max Drawdown**")
            st.markdown(
                "The largest peak-to-trough decline in portfolio value before recovery. "
                "A practical measure of the worst-case loss an investor would have experienced."
            )
            st.markdown(
                """
| Risk profile | Typical range |
|--------------|--------------|
| Conservative | −5 % to −10 % |
| Moderate | −10 % to −20 % |
| Balanced | −20 % to −35 % |
| Aggressive | −35 % to −55 % |
                """
            )

        with col_sr:
            st.markdown("**⚖️ Sharpe Ratio**")
            st.markdown(
                "Return earned per unit of volatility, above the risk-free rate. "
                "A higher Sharpe means better risk-adjusted performance."
            )
            st.markdown(
                """
| Sharpe Ratio | Interpretation |
|--------------|---------------|
| < 0.5 | Poor |
| 0.5 – 1.0 | Acceptable |
| 1.0 – 1.5 | Good |
| > 1.5 | Excellent |
                """
            )

        st.caption(
            "Ranges are approximate long-run historical averages and will vary "
            "significantly across time periods and market regimes."
        )
