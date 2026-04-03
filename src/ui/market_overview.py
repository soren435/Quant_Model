"""
Market Overview v3 — page rendering.

Page structure:
  1. Period selector (1Y / 3Y / 5Y / Max / Custom) + ticker + benchmark controls
  2. KPI snapshot cards
  3. Normalized price chart
  4. Drawdown + rolling volatility charts (side by side)
  5. Performance summary table (trailing + annualised metrics)
  6. Benchmark-relative analysis table
  7. Correlation matrix + diversification interpretation
  8. Market interpretation (rule-based narrative)
"""
from __future__ import annotations

from datetime import date

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
    annualized_volatility,
    drawdown_series,
    rolling_volatility,
    summary_stats,
    beta,
    tracking_error,
)
from src.visualization.charts import (
    plot_price_history,
    plot_drawdown,
    plot_rolling_metric,
    plot_correlation_heatmap,
)
from src.utils.formatting import format_pct, format_number, get_period_label, date_to_str
from src.i18n.translations import get_text

# ── Asset class membership (used for regime detection and interpretation) ──────

_EQUITY_PROXIES = {"SPY", "QQQ", "VTI", "IWM", "VGK", "EEM", "IWDA.AS", "EUNL.DE"}
_BOND_PROXIES   = {"TLT", "IEF", "AGG", "BND", "SHY", "LQD", "HYG"}
_CASH_PROXIES   = {"SHY", "BIL", "SGOV"}


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_effective_dates(
    period: str,
    sidebar_start: str,
    sidebar_end: str,
) -> tuple[str, str]:
    """
    Translate a quick-period label into (start_str, end_str).
    'Custom' falls back to the global sidebar dates.
    """
    end = pd.Timestamp(sidebar_end)
    offsets = {"1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365}

    if period in offsets:
        start = end - pd.Timedelta(days=offsets[period])
        return date_to_str(start.date()), sidebar_end
    else:  # "Max" or "Custom"
        return sidebar_start, sidebar_end


def _compute_kpis(stats_map: dict[str, dict]) -> dict:
    """Extract best / worst / highest-vol / deepest-drawdown from the stats map."""
    valid = {t: s for t, s in stats_map.items() if s}
    if not valid:
        return {}

    total_rets = {t: s["Cumulative Return"]       for t, s in valid.items()}
    ann_vols   = {t: s["Annualized Volatility"]    for t, s in valid.items()}
    max_dds    = {t: s["Max Drawdown"]             for t, s in valid.items()}

    return {
        "best":     (max(total_rets, key=total_rets.get), max(total_rets.values())),
        "worst":    (min(total_rets, key=total_rets.get), min(total_rets.values())),
        "high_vol": (max(ann_vols,   key=ann_vols.get),   max(ann_vols.values())),
        "deep_dd":  (min(max_dds,    key=max_dds.get),    min(max_dds.values())),
    }


def _detect_regime(stats_map: dict[str, dict], tickers: list[str]) -> str:
    """
    Rule-based market regime label.
    Uses relative performance of equity vs bond tickers in the selection.
    """
    eq_rets = [
        stats_map[t]["Cumulative Return"]
        for t in tickers
        if t in _EQUITY_PROXIES and stats_map.get(t)
    ]
    bd_rets = [
        stats_map[t]["Cumulative Return"]
        for t in tickers
        if t in _BOND_PROXIES and stats_map.get(t)
    ]

    avg_eq = sum(eq_rets) / len(eq_rets) if eq_rets else None
    avg_bd = sum(bd_rets) / len(bd_rets) if bd_rets else None

    if avg_eq is None and avg_bd is None:
        return "Insufficient data"

    if avg_eq is not None and avg_bd is not None:
        if avg_eq > 0.10 and avg_bd > 0:
            return "Risk-On — Broad Advance"
        if avg_eq > 0.05 and avg_eq > avg_bd + 0.05:
            return "Risk-On — Equities Leading"
        if avg_eq > 0 and avg_bd > 0 and abs(avg_eq - avg_bd) < 0.05:
            return "Broadly Positive — Mixed Leadership"
        if avg_bd > 0.03 and avg_eq < 0:
            return "Risk-Off — Flight to Safety"
        if avg_eq < -0.05 and avg_bd < -0.05:
            return "Broad Selloff"
        if avg_eq < 0 and avg_bd > 0:
            return "Defensive — Bonds Outperforming"
        if avg_eq > 0 and avg_bd < -0.05:
            return "Rising Rate Environment"
        return "Mixed / Transitional"

    if avg_eq is not None:
        if avg_eq > 0.15:   return "Strong Bull Market"
        if avg_eq > 0.05:   return "Risk-On"
        if avg_eq > -0.05:  return "Neutral / Consolidating"
        return "Equity Weakness"

    # bond-only selection
    if avg_bd > 0.05:   return "Bond Rally"
    if avg_bd < -0.05:  return "Rising Rates / Bond Selloff"
    return "Stable Rates"


def _build_performance_table(
    prices: pd.DataFrame,
    available: list[str],
    rf: float,
    lang: str = "en",
) -> pd.DataFrame:
    """
    Full performance table: trailing returns (1M, 3M, 6M, YTD, 1Y)
    plus annualised statistics (CAGR, vol, Sharpe, max drawdown).
    """
    T = lambda key, **kw: get_text(key, lang, **kw)
    rows = []
    for t in available:
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


def _build_benchmark_table(
    prices: pd.DataFrame,
    available: list[str],
    benchmark: str,
    rf: float,
    lang: str = "en",
) -> pd.DataFrame:
    """
    Benchmark-relative stats for each selected ticker:
    excess return, beta, and relative volatility.
    Returns an empty DataFrame if benchmark data is unavailable.
    """
    T = lambda key, **kw: get_text(key, lang, **kw)

    if benchmark not in prices.columns:
        return pd.DataFrame()

    bench_ret    = prices[benchmark].pct_change().dropna()
    bench_tr     = total_return(bench_ret)
    bench_vol    = annualized_volatility(bench_ret)

    rows = []
    for t in available:
        p   = prices[t].dropna()
        ret = p.pct_change().dropna()
        if ret.empty:
            continue

        t_tr     = total_return(ret)
        t_vol    = annualized_volatility(ret)
        excess   = t_tr - bench_tr
        t_beta   = beta(ret, bench_ret)
        rel_vol  = (t_vol / bench_vol) if bench_vol > 0 else float("nan")
        te       = tracking_error(ret, bench_ret)

        rows.append({
            T("col_ticker"):                          t,
            T("col_excess_return", benchmark=benchmark): format_pct(excess),
            T("col_beta"):                            format_number(t_beta) if not pd.isna(t_beta) else "N/A",
            T("col_rel_vol"):                         format_number(rel_vol) if not pd.isna(rel_vol) else "N/A",
            T("col_tracking_error"):                  format_pct(te) if not pd.isna(te) else "N/A",
        })
    col_ticker = T("col_ticker")
    return pd.DataFrame(rows).set_index(col_ticker) if rows else pd.DataFrame()


def _interpret_correlation(
    corr: pd.DataFrame,
    available: list[str],
) -> str:
    """
    Rule-based text summary of the correlation matrix.
    Comments on high/low pairs, bond diversification, and overall quality.
    """
    n = len(available)
    if n < 2:
        return "_Need at least 2 tickers for correlation interpretation._"

    high_corr     = []
    negative_corr = []
    abs_vals      = []

    for i in range(n):
        for j in range(i + 1, n):
            t1, t2 = available[i], available[j]
            if t1 not in corr.index or t2 not in corr.columns:
                continue
            c = corr.loc[t1, t2]
            abs_vals.append(abs(c))
            if c > 0.75:
                high_corr.append((t1, t2, c))
            elif c < -0.10:
                negative_corr.append((t1, t2, c))

    avg_abs = sum(abs_vals) / len(abs_vals) if abs_vals else 0.0
    div_quality = (
        "strong"   if avg_abs < 0.30 else
        "moderate" if avg_abs < 0.60 else
        "weak"
    )

    lines = [
        f"**Diversification quality: {div_quality.title()}**"
        f" — average pairwise |correlation|: **{avg_abs:.2f}**",
        "",
    ]

    if high_corr:
        pairs_str = ", ".join(
            f"{t1} / {t2} ({c:.2f})"
            for t1, t2, c in sorted(high_corr, key=lambda x: -x[2])[:4]
        )
        lines.append(
            f"- **Highly correlated (>0.75):** {pairs_str}. "
            "These assets move largely in tandem and add limited diversification benefit."
        )

    if negative_corr:
        pairs_str = ", ".join(
            f"{t1} / {t2} ({c:.2f})"
            for t1, t2, c in sorted(negative_corr, key=lambda x: x[2])[:4]
        )
        lines.append(
            f"- **Negatively correlated (<−0.10):** {pairs_str}. "
            "These pairs provide genuine portfolio diversification."
        )

    # Bond vs equity correlation commentary
    eq_t  = [t for t in available if t in _EQUITY_PROXIES]
    bd_t  = [t for t in available if t in _BOND_PROXIES]

    if eq_t and bd_t:
        be_corrs = [
            corr.loc[b, e]
            for b in bd_t for e in eq_t
            if b in corr.index and e in corr.columns
        ]
        if be_corrs:
            avg_be = sum(be_corrs) / len(be_corrs)
            bond_label = " / ".join(bd_t)
            if avg_be < -0.15:
                lines.append(
                    f"- **{bond_label}** was negatively correlated with equities "
                    f"(avg: {avg_be:.2f}), providing meaningful hedging value in this period."
                )
            elif avg_be < 0.20:
                lines.append(
                    f"- **{bond_label}** showed low correlation with equities "
                    f"(avg: {avg_be:.2f}), offering moderate diversification."
                )
            else:
                lines.append(
                    f"- **{bond_label}** was positively correlated with equities "
                    f"(avg: {avg_be:.2f}). Bonds provided limited diversification in this period — "
                    "a pattern typical of rising-rate or inflationary regimes."
                )

    if "SHY" in available and eq_t:
        shy_corrs = [
            corr.loc["SHY", e]
            for e in eq_t
            if "SHY" in corr.index and e in corr.columns
        ]
        if shy_corrs:
            avg_shy = sum(shy_corrs) / len(shy_corrs)
            anchor = "acted as a low-correlation defensive anchor" if avg_shy < 0.15 else "showed higher equity correlation than typical for a cash proxy"
            lines.append(f"- **SHY** {anchor} (avg equity correlation: {avg_shy:.2f}).")

    return "\n".join(lines)


def _generate_narrative(
    stats_map: dict[str, dict],
    tickers: list[str],
    regime: str,
    period_label: str,
    kpis: dict,
    benchmark: str,
    bench_stats: dict,
    avg_pairwise_corr: float | None = None,
) -> str:
    """
    Enhanced rule-based market narrative.
    Covers regime, leadership, volatility, bond behavior, and benchmark context.
    No LLM — all logic is deterministic.
    """
    if not kpis:
        return "_Insufficient data to generate a narrative._"

    best_t,   best_v   = kpis["best"]
    worst_t,  worst_v  = kpis["worst"]
    dd_t,     dd_v     = kpis["deep_dd"]
    vol_t,    vol_v    = kpis["high_vol"]

    eq_t = [t for t in tickers if t in _EQUITY_PROXIES and stats_map.get(t)]
    bd_t = [t for t in tickers if t in _BOND_PROXIES   and stats_map.get(t)]

    # ── Volatility environment ─────────────────────────────────────────────────
    all_vols = [s["Annualized Volatility"] for s in stats_map.values() if s]
    avg_vol  = sum(all_vols) / len(all_vols) if all_vols else 0.0
    vol_env  = (
        "high"     if avg_vol > 0.25 else
        "elevated" if avg_vol > 0.18 else
        "moderate" if avg_vol > 0.10 else
        "low"
    )

    # ── Performance spread ─────────────────────────────────────────────────────
    spread = best_v - worst_v
    spread_desc = (
        "wide dispersion" if spread > 0.20 else
        "moderate dispersion" if spread > 0.08 else
        "narrow dispersion"
    )

    lines = [
        f"**Regime: {regime}** — {period_label} period ending {pd.Timestamp('today').strftime('%d %b %Y')}",
        "",
        "**Performance leadership**",
    ]

    # Leadership by asset class
    if eq_t and bd_t:
        avg_eq_ret = sum(stats_map[t]["Cumulative Return"] for t in eq_t) / len(eq_t)
        avg_bd_ret = sum(stats_map[t]["Cumulative Return"] for t in bd_t) / len(bd_t)
        leader     = "equities" if avg_eq_ret > avg_bd_ret else "bonds"
        lines.append(
            f"- **{leader.title()}** led the cross-asset pack. "
            f"Equities averaged **{format_pct(avg_eq_ret)}** vs bonds at **{format_pct(avg_bd_ret)}**."
        )
    elif eq_t:
        avg_eq_ret = sum(stats_map[t]["Cumulative Return"] for t in eq_t) / len(eq_t)
        lines.append(f"- Equity ETFs averaged **{format_pct(avg_eq_ret)}** over the period.")
    elif bd_t:
        avg_bd_ret = sum(stats_map[t]["Cumulative Return"] for t in bd_t) / len(bd_t)
        lines.append(f"- Bond ETFs averaged **{format_pct(avg_bd_ret)}** over the period.")

    lines.append(
        f"- **{best_t}** was the top performer ({format_pct(best_v)}); "
        f"**{worst_t}** was the laggard ({format_pct(worst_v)}). "
        f"Cross-asset return spread: {spread_desc} ({format_pct(spread)})."
    )

    # ── Volatility ─────────────────────────────────────────────────────────────
    lines += [
        "",
        "**Risk environment**",
        f"- Volatility was **{vol_env}** across the basket (avg: {format_pct(avg_vol)} annualised). "
        f"**{vol_t}** was the most volatile asset at {format_pct(vol_v)} annualised vol.",
        f"- **{dd_t}** had the deepest drawdown at {format_pct(dd_v)} peak-to-trough.",
    ]

    # ── Bond behavior ──────────────────────────────────────────────────────────
    if eq_t and bd_t:
        avg_bd_ret = sum(stats_map[t]["Cumulative Return"] for t in bd_t) / len(bd_t)
        avg_eq_ret = sum(stats_map[t]["Cumulative Return"] for t in eq_t) / len(eq_t)
        lines.append("")
        lines.append("**Bond behavior**")
        if avg_bd_ret > 0 and avg_eq_ret < 0:
            lines.append(
                "- Bonds delivered positive returns while equities fell — "
                "a classic flight-to-safety pattern. The equity-bond diversification held."
            )
        elif avg_bd_ret < -0.05 and avg_eq_ret < 0:
            lines.append(
                "- Both equities and bonds declined — a 'no place to hide' environment "
                "consistent with rising rates or broad de-risking. "
                "Traditional diversification provided limited protection."
            )
        elif avg_bd_ret < -0.05 and avg_eq_ret > 0.05:
            lines.append(
                "- Rising-rate dynamics appear to have weighed on bonds while equities advanced — "
                "a regime where duration risk hurt balanced portfolios."
            )
        else:
            lines.append(
                f"- Bonds returned {format_pct(avg_bd_ret)} vs equities at {format_pct(avg_eq_ret)}. "
                "Diversification benefit was limited in this period."
            )

    # ── Benchmark context ──────────────────────────────────────────────────────
    if bench_stats and benchmark in tickers:
        bench_ret_val = bench_stats.get("Cumulative Return", 0)
        beaters = [
            t for t in tickers
            if t != benchmark and stats_map.get(t)
            and stats_map[t].get("Cumulative Return", 0) > bench_ret_val
        ]
        losers = [t for t in tickers if t != benchmark and t not in beaters and stats_map.get(t)]
        lines += [
            "",
            f"**Benchmark context ({benchmark}: {format_pct(bench_ret_val)})**",
            f"- {len(beaters)} of {len(tickers) - 1} assets outperformed the benchmark"
            + (f": {', '.join(beaters)}." if beaters else "."),
        ]
        if losers:
            lines.append(f"- Underperformers: {', '.join(losers)}.")

    # ── Diversification note ───────────────────────────────────────────────────
    if avg_pairwise_corr is not None:
        div = (
            "strong — assets moved with relatively low co-dependence" if avg_pairwise_corr < 0.30 else
            "moderate — some co-movement, but meaningful differentiation across assets" if avg_pairwise_corr < 0.60 else
            "weak — assets moved largely in tandem, limiting diversification benefit"
        )
        lines += [
            "",
            "**Diversification**",
            f"- Pairwise correlation averaged **{avg_pairwise_corr:.2f}**. "
            f"Portfolio diversification quality was **{div}**.",
        ]

    lines += [
        "",
        "_Rule-based summary. For analytical context only — not investment advice._",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Page entry point
# ═══════════════════════════════════════════════════════════════════════════════

def render_market_overview(
    cfg: dict,
    start_str: str,
    end_str: str,
    rf: float,
    lang: str = "en",
) -> None:
    """
    Render the Market Overview v3 page.

    Args:
        cfg:       Loaded config dict (from config.yml).
        start_str: Global sidebar start date 'YYYY-MM-DD' (used for Max/Custom).
        end_str:   Global sidebar end date 'YYYY-MM-DD'.
        rf:        Annual risk-free rate for Sharpe calculations.
        lang:      UI language code ("en" or "da"). Defaults to "en".
    """
    T = lambda key, **kw: get_text(key, lang, **kw)

    st.header(T("mo_header"))
    st.caption(T("mo_caption"))

    # ── 1. Controls row ────────────────────────────────────────────────────────
    all_options = (
        cfg["tickers"]["equities"]
        + cfg["tickers"]["bonds"]
        + cfg["tickers"].get("alternatives", [])
        + cfg["tickers"]["cash_proxy"]
    )
    # Deduplicate while preserving order
    seen: set[str] = set()
    all_options_unique = [t for t in all_options if not (t in seen or seen.add(t))]

    benchmark_options = cfg["tickers"].get("benchmarks", ["SPY"])

    period_col, ticker_col, bench_col = st.columns([2, 4, 1])

    with period_col:
        period = st.radio(
            T("mo_period_label"),
            ["1Y", "3Y", "5Y", "Max", "Custom"],
            index=0,
            horizontal=True,
            help=T("mo_period_help"),
            key="mo_period",
        )

    with ticker_col:
        selected = st.multiselect(
            T("mo_tickers_label"),
            options=all_options_unique,
            default=cfg["tickers"]["market_overview"],
            help=T("mo_tickers_help"),
            key="mo_tickers",
        )

    with bench_col:
        benchmark = st.selectbox(
            T("mo_benchmark_label"),
            options=benchmark_options,
            index=0,
            help=T("mo_benchmark_help"),
            key="mo_benchmark",
        )

    if not selected:
        st.info(T("mo_no_tickers"))
        return

    # Resolve effective date range for this page
    ov_start, ov_end = _compute_effective_dates(period, start_str, end_str)
    if period == "Custom":
        st.caption(T("mo_custom_range", start=start_str, end=end_str))

    # ── 2. Data download ───────────────────────────────────────────────────────
    download_set = list({*selected, benchmark})
    with st.spinner(T("mo_downloading")):
        prices = download_prices(tuple(download_set), ov_start, ov_end)

    if prices.empty:
        st.error(T("mo_no_data"))
        return

    available = [t for t in selected if t in prices.columns]
    missing   = [t for t in selected if t not in prices.columns]
    if missing:
        st.warning(T("mo_skipped", tickers=", ".join(missing)))
    if not available:
        st.error(T("mo_none_returned"))
        return

    # Compute stats once — all downstream helpers read from this map
    stats_map: dict[str, dict] = {
        t: summary_stats(prices[t].pct_change().dropna(), rf)
        for t in available
    }
    bench_stats = (
        summary_stats(prices[benchmark].pct_change().dropna(), rf)
        if benchmark in prices.columns else {}
    )

    kpis   = _compute_kpis(stats_map)
    regime = _detect_regime(stats_map, available)
    period_label = get_period_label(ov_start, ov_end)

    # ── 3. KPI snapshot ────────────────────────────────────────────────────────
    st.subheader(T("mo_snapshot_header"))
    k1, k2, k3, k4, k5 = st.columns(5)

    if kpis:
        best_t,  best_v  = kpis["best"]
        worst_t, worst_v = kpis["worst"]
        vol_t,   vol_v   = kpis["high_vol"]
        dd_t,    dd_v    = kpis["deep_dd"]

        k1.metric(T("mo_best_performer"),  best_t,  format_pct(best_v))
        k2.metric(T("mo_worst_performer"), worst_t, format_pct(worst_v))
        k3.metric(T("mo_highest_vol"),     vol_t,   format_pct(vol_v))
        k4.metric(T("mo_deepest_dd"),      dd_t,    format_pct(dd_v))
        k5.metric(T("mo_market_regime"),   regime)

    # ── 4. Normalized price chart ──────────────────────────────────────────────
    st.subheader(T("mo_price_header"))
    # Include benchmark as a reference line if it's not already in the selection
    chart_tickers = available[:]
    if benchmark in prices.columns and benchmark not in chart_tickers:
        chart_tickers.append(benchmark)
    st.plotly_chart(
        plot_price_history(prices[chart_tickers], normalize=True),
    )

    # ── 5. Drawdown + rolling vol ──────────────────────────────────────────────
    col_dd, col_rv = st.columns(2)

    with col_dd:
        st.subheader(T("mo_drawdown_header"))
        dd_df = pd.DataFrame({
            t: drawdown_series(prices[t].pct_change().dropna())
            for t in available
        })
        st.plotly_chart(plot_drawdown(dd_df), use_container_width=True)

    with col_rv:
        st.subheader(T("mo_rolling_vol_header"))
        rv_df = pd.DataFrame({
            t: rolling_volatility(prices[t].pct_change().dropna(), window=21)
            for t in available
        })
        st.plotly_chart(
            plot_rolling_metric(rv_df, as_pct=True, y_label="Annualized Volatility (%)"),
        )

    # ── 6. Performance summary table ───────────────────────────────────────────
    st.subheader(T("mo_perf_table_header"))
    st.caption(T("mo_perf_table_caption"))
    perf_table = _build_performance_table(prices, available, rf, lang)
    if not perf_table.empty:
        st.dataframe(perf_table)
    else:
        st.info(T("mo_perf_table_empty"))

    # ── 7. Benchmark-relative analysis ────────────────────────────────────────
    if benchmark in prices.columns:
        bench_tr = (
            bench_stats.get("Cumulative Return", 0) if bench_stats else 0.0
        )
        st.subheader(T("mo_bench_rel_header", benchmark=benchmark, bench_ret=format_pct(bench_tr)))
        st.caption(T("mo_bench_rel_caption"))
        bm_table = _build_benchmark_table(prices, available, benchmark, rf, lang)
        if not bm_table.empty:
            st.dataframe(bm_table)
        else:
            st.info(T("mo_bench_rel_empty"))

    # ── 8. Correlation matrix + interpretation ─────────────────────────────────
    if len(available) > 1:
        st.subheader(T("mo_corr_header"))
        returns_df = prices[available].pct_change().dropna()
        corr = returns_df.corr()
        st.plotly_chart(plot_correlation_heatmap(corr), use_container_width=True)

        # Compute average pairwise |corr| for narrative
        n = len(available)
        abs_vals = [
            abs(corr.loc[available[i], available[j]])
            for i in range(n)
            for j in range(i + 1, n)
            if available[i] in corr.index and available[j] in corr.columns
        ]
        avg_pairwise_corr: float | None = (
            sum(abs_vals) / len(abs_vals) if abs_vals else None
        )

        with st.expander(T("mo_corr_expander"), expanded=True):
            st.markdown(_interpret_correlation(corr, available))
    else:
        avg_pairwise_corr = None

    # ── 9. Market interpretation ───────────────────────────────────────────────
    st.subheader(T("mo_interpretation_header"))
    narrative = _generate_narrative(
        stats_map,
        available,
        regime,
        period_label,
        kpis,
        benchmark,
        bench_stats,
        avg_pairwise_corr,
    )
    st.markdown(narrative)
