"""
Single Asset Analysis v2 — professional page rendering.

Page structure:
  1. Description
  2. User inputs (ticker, benchmark, period, MA windows)
  3. KPI summary (6 cards: period return, 1Y return, volatility,
     Sharpe Ratio, max drawdown, excess return vs benchmark)
  4. Price & moving averages chart
  5. Cumulative return vs benchmark | Drawdown (side by side)
  6. Rolling volatility chart
  7. Performance table (trailing + annualised, asset vs benchmark)
  8. Benchmark-relative diagnostics (Beta, Tracking Error, Information Ratio)
  9. Monthly returns heatmap
  10. Rule-based interpretation
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data.loader import download_prices
from src.analytics.returns import (
    cumulative_returns_series,
    total_return,
    period_return,
    ytd_return,
)
from src.analytics.risk import (
    drawdown_series,
    rolling_volatility,
    summary_stats,
    beta,
    tracking_error,
    information_ratio,
)
from src.visualization.charts import (
    plot_moving_averages,
    plot_cumulative_returns,
    plot_drawdown,
    plot_rolling_metric,
    plot_monthly_returns_heatmap,
)
from src.utils.formatting import format_pct, format_number, date_to_str, get_period_label
from src.i18n.translations import get_text


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_effective_dates(
    period: str,
    sidebar_start: str,
    sidebar_end: str,
) -> tuple[str, str]:
    """Translate a quick-period label into (start_str, end_str)."""
    end = pd.Timestamp(sidebar_end)
    offsets = {"1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365}
    if period in offsets:
        start = end - pd.Timedelta(days=offsets[period])
        return date_to_str(start.date()), sidebar_end
    return sidebar_start, sidebar_end  # "Max" or "Custom"


def _build_performance_table(
    prices: pd.DataFrame,
    tickers: list[str],
    rf: float,
    lang: str = "en",
) -> pd.DataFrame:
    """
    Trailing + annualised performance table for the given tickers.
    Returns rows for each ticker found in prices.
    """
    T = lambda key, **kw: get_text(key, lang, **kw)
    rows = []
    for t in tickers:
        if t not in prices.columns:
            continue
        p   = prices[t].dropna()
        ret = p.pct_change().dropna()
        if ret.empty:
            continue
        s = summary_stats(ret, rf)
        if not s:
            continue
        rows.append({
            T("col_ticker"):       t,
            T("col_1m"):           format_pct(period_return(p, 21)),
            T("col_3m"):           format_pct(period_return(p, 63)),
            T("col_6m"):           format_pct(period_return(p, 126)),
            T("col_ytd"):          format_pct(ytd_return(p)),
            T("col_1y"):           format_pct(period_return(p, 252)),
            T("col_total_return"): format_pct(s.get("Cumulative Return", 0)),
            T("col_ann_return"):   format_pct(s.get("Annualized Return", 0)),
            T("col_ann_vol"):      format_pct(s.get("Annualized Volatility", 0)),
            T("col_sharpe"):       format_number(s.get("Sharpe Ratio", 0)),
            T("col_max_dd"):       format_pct(s.get("Max Drawdown", 0)),
        })
    col_ticker = T("col_ticker")
    return pd.DataFrame(rows).set_index(col_ticker) if rows else pd.DataFrame()


def _generate_interpretation(
    ticker: str,
    benchmark: str,
    stats: dict,
    price: pd.Series,
    ma_short: int,
    ma_long: int,
    excess_return: float,
    period_label: str,
) -> str:
    """
    Rule-based interpretation for the Single Asset page.
    Covers trend, benchmark-relative performance, volatility, and drawdown.
    No LLM — fully deterministic logic.
    """
    if not stats:
        return "_Insufficient data to generate an interpretation._"

    lines: list[str] = []

    # ── Trend (price vs moving averages) ──────────────────────────────────────
    current_price = float(price.iloc[-1]) if not price.empty else None
    ma_long_val  = float(price.rolling(ma_long).mean().iloc[-1])  if len(price) >= ma_long  else None
    ma_short_val = float(price.rolling(ma_short).mean().iloc[-1]) if len(price) >= ma_short else None

    lines.append("**Trend**")
    if current_price and ma_long_val and ma_short_val:
        if current_price > ma_long_val:
            lines.append(
                f"- {ticker} is trading **above** its {ma_long}-day moving average "
                f"({format_number(ma_long_val)}), indicating a supportive long-term trend."
            )
        elif current_price > ma_short_val:
            lines.append(
                f"- {ticker} is above the {ma_short}-day MA but below the {ma_long}-day MA — "
                "a mixed signal: short-term recovery within a longer-term downtrend."
            )
        else:
            lines.append(
                f"- {ticker} is trading **below** both the {ma_short}-day and {ma_long}-day "
                "moving averages — near-term trend is bearish."
            )
    elif current_price and ma_short_val:
        direction = "above" if current_price > ma_short_val else "below"
        lines.append(
            f"- {ticker} is trading {direction} its {ma_short}-day moving average "
            f"(insufficient history for the {ma_long}-day MA)."
        )
    else:
        lines.append(f"- Insufficient price history to assess moving average trend for {ticker}.")

    # ── Performance vs benchmark ───────────────────────────────────────────────
    lines += ["", "**Performance vs Benchmark**"]
    if excess_return > 0.02:
        lines.append(
            f"- {ticker} **outperformed** {benchmark} by {format_pct(excess_return)} "
            f"over the {period_label} period."
        )
    elif excess_return < -0.02:
        lines.append(
            f"- {ticker} **underperformed** {benchmark} by {format_pct(abs(excess_return))} "
            f"over the {period_label} period."
        )
    else:
        lines.append(
            f"- {ticker} tracked {benchmark} closely, with an excess return of "
            f"{format_pct(excess_return)} over the {period_label} period."
        )

    # ── Volatility profile ─────────────────────────────────────────────────────
    ann_vol = stats.get("Annualized Volatility", 0)
    vol_label = (
        "high"     if ann_vol > 0.30 else
        "elevated" if ann_vol > 0.18 else
        "moderate" if ann_vol > 0.10 else
        "low"
    )
    lines += [
        "",
        "**Volatility Profile**",
        f"- Annualized volatility was **{format_pct(ann_vol)}** — a **{vol_label}** level "
        "relative to typical equity and fixed-income benchmarks.",
    ]

    # ── Drawdown behavior ──────────────────────────────────────────────────────
    max_dd = stats.get("Max Drawdown", 0)
    if max_dd < -0.30:
        dd_comment = "a severe drawdown that would have tested investor conviction significantly."
    elif max_dd < -0.15:
        dd_comment = "a significant drawdown, suggesting meaningful downside risk in the period."
    elif max_dd < -0.05:
        dd_comment = "a moderate drawdown within a typical range for risky assets."
    else:
        dd_comment = "a shallow drawdown, reflecting resilient price behavior."

    lines += [
        "",
        "**Drawdown**",
        f"- Max drawdown was **{format_pct(max_dd)}** — {dd_comment}",
        "",
        "_Rule-based summary. For analytical context only — not investment advice._",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Page entry point
# ═══════════════════════════════════════════════════════════════════════════════

def render_single_asset(
    cfg: dict,
    start_str: str,
    end_str: str,
    rf: float,
    lang: str = "en",
) -> None:
    """
    Render the Single Asset Analysis page.

    Args:
        cfg:       Loaded config dict.
        start_str: Start date string 'YYYY-MM-DD'.
        end_str:   End date string 'YYYY-MM-DD'.
        rf:        Annual risk-free rate.
        lang:      UI language code ("en" or "da"). Defaults to "en".
    """
    T = lambda key, **kw: get_text(key, lang, **kw)

    st.header(T("sa_header"))
    st.caption(T("sa_caption"))

    # ── 1. Controls ────────────────────────────────────────────────────────────
    col_t, col_b, col_p = st.columns([2, 1, 2])

    with col_t:
        ticker = st.text_input(
            T("sa_ticker_label"),
            value="SPY",
            help=T("sa_ticker_help"),
        ).strip().upper()

    with col_b:
        benchmark_options = cfg["tickers"].get("benchmarks", ["SPY"])
        benchmark = st.selectbox(
            T("sa_benchmark_label"),
            options=benchmark_options,
            index=0,
            help=T("sa_benchmark_help"),
            key="sa_benchmark",
        )

    with col_p:
        period = st.radio(
            T("sa_period_label"),
            ["1Y", "3Y", "5Y", "Max", "Custom"],
            index=0,
            horizontal=True,
            help=T("sa_period_help"),
            key="sa_period",
        )

    col_s, col_l, _ = st.columns([1, 1, 4])
    with col_s:
        ma_s = st.number_input(
            T("sa_short_ma_label"),
            value=cfg["settings"]["ma_short"],
            min_value=5, max_value=200, step=5,
            key="sa_ma_short",
        )
    with col_l:
        ma_l = st.number_input(
            T("sa_long_ma_label"),
            value=cfg["settings"]["ma_long"],
            min_value=20, max_value=500, step=10,
            key="sa_ma_long",
        )

    if not ticker:
        st.info(T("sa_no_ticker"))
        return

    # Resolve effective date range
    sa_start, sa_end = _compute_effective_dates(period, start_str, end_str)
    if period == "Custom":
        st.caption(T("sa_custom_range", start=start_str, end=end_str))

    # ── 2. Data download ───────────────────────────────────────────────────────
    download_set = list({ticker, benchmark})
    with st.spinner(T("sa_downloading", ticker=ticker)):
        prices = download_prices(tuple(download_set), sa_start, sa_end)

    if prices.empty or ticker not in prices.columns:
        st.error(T("sa_no_data", ticker=ticker))
        return

    price_s  = prices[ticker].dropna()
    ret_s    = price_s.pct_change().dropna()
    stats_s  = summary_stats(ret_s, rf)

    # Benchmark series (may equal ticker — still useful as a reference)
    has_bench = benchmark in prices.columns
    if has_bench:
        price_b  = prices[benchmark].dropna()
        ret_b    = price_b.pct_change().dropna()
        bench_tr = total_return(ret_b)
    else:
        ret_b    = None
        bench_tr = 0.0

    asset_tr    = total_return(ret_s)
    excess_ret  = asset_tr - bench_tr
    period_label = get_period_label(sa_start, sa_end)

    # ── 3. KPI Cards ───────────────────────────────────────────────────────────
    st.subheader(T("sa_kpi_header", ticker=ticker))
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric(T("sa_period_return"),                    format_pct(stats_s.get("Cumulative Return", 0)))
    m2.metric(T("sa_1y_return"),                        format_pct(period_return(price_s, 252)))
    m3.metric(T("sa_ann_vol"),                          format_pct(stats_s.get("Annualized Volatility", 0)))
    m4.metric(T("sa_sharpe"),                           format_number(stats_s.get("Sharpe Ratio", 0)))
    m5.metric(T("sa_max_dd"),                           format_pct(stats_s.get("Max Drawdown", 0)))
    m6.metric(T("sa_excess_return", benchmark=benchmark), format_pct(excess_ret))

    # ── 4. Price & Moving Averages ─────────────────────────────────────────────
    st.subheader(T("sa_price_ma_header"))
    st.plotly_chart(
        plot_moving_averages(price_s, ma_short=ma_s, ma_long=ma_l, ticker=ticker),
    )

    # ── 5. Cumulative Return vs Benchmark  |  Drawdown ─────────────────────────
    col_a, col_b_col = st.columns(2)

    with col_a:
        st.subheader(T("sa_cum_return_header"))
        cum_s = cumulative_returns_series(ret_s).rename(ticker)
        if has_bench and benchmark != ticker:
            cum_b  = cumulative_returns_series(ret_b).rename(benchmark)
            cum_df = pd.concat([cum_s, cum_b], axis=1).dropna()
        else:
            cum_df = cum_s
        st.plotly_chart(plot_cumulative_returns(cum_df), use_container_width=True)

    with col_b_col:
        st.subheader(T("sa_drawdown_header"))
        dd_s = drawdown_series(ret_s).rename(ticker)
        if has_bench and benchmark != ticker:
            dd_b  = drawdown_series(ret_b).rename(benchmark)
            dd_df = pd.concat([dd_s, dd_b], axis=1).dropna()
        else:
            dd_df = dd_s
        st.plotly_chart(plot_drawdown(dd_df), use_container_width=True)

    # ── 6. Rolling Volatility ──────────────────────────────────────────────────
    st.subheader(T("sa_rolling_vol_header"))
    roll_vol_s = rolling_volatility(ret_s, window=21).rename(ticker)
    if has_bench and benchmark != ticker:
        roll_vol_b = rolling_volatility(ret_b, window=21).rename(benchmark)
        rv_df = pd.concat([roll_vol_s, roll_vol_b], axis=1).dropna()
    else:
        rv_df = roll_vol_s
    st.plotly_chart(
        plot_rolling_metric(rv_df, as_pct=True, y_label="Annualized Volatility (%)"),
    )

    # ── 7. Performance Table ───────────────────────────────────────────────────
    st.subheader(T("sa_perf_table_header"))
    st.caption(T("sa_perf_table_caption"))
    table_tickers = [ticker] + ([benchmark] if has_bench and benchmark != ticker else [])
    perf_table = _build_performance_table(prices, table_tickers, rf, lang)
    if not perf_table.empty:
        st.dataframe(perf_table)

    # ── 8. Benchmark-Relative Diagnostics ─────────────────────────────────────
    if has_bench and benchmark != ticker:
        st.subheader(T("sa_bench_diag_header"))
        st.caption(T("sa_bench_diag_caption", benchmark=benchmark))

        combined       = pd.concat([ret_s, ret_b], axis=1).dropna()
        ret_s_aligned  = combined.iloc[:, 0]
        ret_b_aligned  = combined.iloc[:, 1]

        t_beta = beta(ret_s_aligned, ret_b_aligned)
        te     = tracking_error(ret_s_aligned, ret_b_aligned)
        ir     = information_ratio(ret_s_aligned, ret_b_aligned)

        d1, d2, d3 = st.columns(3)
        d1.metric(T("col_beta"),          format_number(t_beta) if not pd.isna(t_beta) else "N/A")
        d2.metric(T("col_tracking_error"), format_pct(te)        if not pd.isna(te)     else "N/A")
        d3.metric(T("col_info_ratio"),    format_number(ir)     if not pd.isna(ir)     else "N/A")

    # ── 9. Monthly Returns Heatmap ─────────────────────────────────────────────
    st.subheader(T("sa_heatmap_header"))
    st.plotly_chart(
        plot_monthly_returns_heatmap(ret_s, title=f"{ticker} — Monthly Returns (%)"),
    )

    # ── 10. Interpretation ─────────────────────────────────────────────────────
    st.subheader(T("sa_interpretation_header"))
    narrative = _generate_interpretation(
        ticker=ticker,
        benchmark=benchmark,
        stats=stats_s,
        price=price_s,
        ma_short=ma_s,
        ma_long=ma_l,
        excess_return=excess_ret,
        period_label=period_label,
    )
    st.markdown(narrative)
