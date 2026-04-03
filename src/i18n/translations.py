"""
Translation layer for the Portfolio Analyzer app.

Usage:
    from src.i18n.translations import get_text

    label = get_text("sa_header", lang)              # simple key
    label = get_text("sa_kpi_header", lang, ticker="SPY")  # with placeholders

Design rules:
  - English ("en") is the product default.
  - Danish ("da") is an optional UI layer; missing keys fall back to English.
  - Code, variable names, and internal function names remain in English.
  - Analytics terminology (Sharpe Ratio, Benchmark, Drawdown, Beta, Tracking Error,
    Information Ratio) is kept as-is in both languages.
"""
from __future__ import annotations

TRANSLATIONS: dict[str, dict[str, str]] = {
    # ══════════════════════════════════════════════════════════════════════════
    # English — product default
    # ══════════════════════════════════════════════════════════════════════════
    "en": {
        # ── Sidebar ────────────────────────────────────────────────────────────
        "sidebar_title":       "Portfolio Analyzer",
        "sidebar_subtitle":    "Professional investment analysis tool",
        "sidebar_date_range":  "Date Range",
        "sidebar_from":        "From",
        "sidebar_to":          "To",
        "sidebar_period":      "Period: **{label}**",
        "sidebar_data_source": "Data: Yahoo Finance via yfinance",
        "sidebar_disclaimer":  "For personal use only — not financial advice.",
        "sidebar_language":    "Language",
        "sidebar_date_error":  "Start date must be before end date.",

        # ── Navigation tabs ────────────────────────────────────────────────────
        "tab_market_overview": "📈 Market Overview",
        "tab_single_asset":    "🔍 Single Asset",
        "tab_portfolio":       "💼 Portfolio Analysis",
        "tab_backtest":        "🔄 Strategy Backtest",
        "tab_scenario":        "⚡ Scenario Analysis",

        # ── Market Overview ────────────────────────────────────────────────────
        "mo_header":               "Market Overview",
        "mo_caption":              "Compare ETFs and benchmarks. Track performance, risk, and cross-asset relationships across any time horizon.",
        "mo_period_label":         "Period",
        "mo_period_help":          "Quick period selection. 'Max' and 'Custom' use the sidebar date range.",
        "mo_tickers_label":        "Tickers",
        "mo_tickers_help":         "Select the ETFs to compare.",
        "mo_benchmark_label":      "Benchmark",
        "mo_benchmark_help":       "Reference index for benchmark-relative analysis.",
        "mo_no_tickers":           "Select at least one ticker to continue.",
        "mo_downloading":          "Downloading market data...",
        "mo_no_data":              "No data returned. Try a different period or ticker selection.",
        "mo_skipped":              "No data for: {tickers} — skipped.",
        "mo_none_returned":        "None of the selected tickers returned data.",
        "mo_custom_range":         "Custom range: **{start}** → **{end}** (set in sidebar)",
        "mo_snapshot_header":      "Market Snapshot",
        "mo_best_performer":       "Best Performer",
        "mo_worst_performer":      "Worst Performer",
        "mo_highest_vol":          "Highest Volatility",
        "mo_deepest_dd":           "Deepest Drawdown",
        "mo_market_regime":        "Market Regime",
        "mo_price_header":         "Normalized Price (Base = 100)",
        "mo_drawdown_header":      "Drawdown",
        "mo_rolling_vol_header":   "Rolling 21-Day Volatility (Ann.)",
        "mo_perf_table_header":    "Performance Summary",
        "mo_perf_table_caption":   "Trailing returns use price data within the selected period.",
        "mo_perf_table_empty":     "Not enough data to build the performance table.",
        "mo_bench_rel_header":     "Benchmark-Relative Analysis vs {benchmark} ({bench_ret})",
        "mo_bench_rel_caption":    "Excess return = total return minus benchmark total return. Beta and tracking error are computed on aligned daily returns.",
        "mo_bench_rel_empty":      "Could not compute benchmark-relative metrics.",
        "mo_corr_header":          "Correlation Matrix (Daily Returns)",
        "mo_corr_expander":        "Diversification & Correlation Interpretation",
        "mo_interpretation_header":"Market Interpretation",

        # ── Single Asset ───────────────────────────────────────────────────────
        "sa_header":               "Single Asset Analysis",
        "sa_caption":              "Deep-dive into any individual ETF or equity. Examine price history, risk profile, and benchmark-relative performance.",
        "sa_ticker_label":         "Ticker symbol",
        "sa_ticker_help":          "Any Yahoo Finance ticker, e.g. SPY, QQQ, TLT, IWDA.AS",
        "sa_benchmark_label":      "Benchmark",
        "sa_benchmark_help":       "Reference index for benchmark-relative analysis.",
        "sa_period_label":         "Period",
        "sa_period_help":          "Quick period selection. 'Max' and 'Custom' use the sidebar date range.",
        "sa_short_ma_label":       "Short MA",
        "sa_long_ma_label":        "Long MA",
        "sa_no_ticker":            "Enter a ticker symbol to continue.",
        "sa_downloading":          "Downloading {ticker}...",
        "sa_no_data":              "No data found for '{ticker}'. Check the symbol and date range.",
        "sa_custom_range":         "Custom range: **{start}** → **{end}** (set in sidebar)",
        "sa_kpi_header":           "{ticker} — Key Metrics",
        "sa_period_return":        "Period Return",
        "sa_1y_return":            "1Y Return",
        "sa_ann_vol":              "Ann. Volatility",
        "sa_sharpe":               "Sharpe Ratio",
        "sa_max_dd":               "Max Drawdown",
        "sa_excess_return":        "Excess Return vs {benchmark}",
        "sa_price_ma_header":      "Price & Moving Averages",
        "sa_cum_return_header":    "Cumulative Return vs Benchmark",
        "sa_drawdown_header":      "Drawdown",
        "sa_rolling_vol_header":   "Rolling 21-Day Volatility (Annualized)",
        "sa_perf_table_header":    "Performance Table",
        "sa_perf_table_caption":   "Trailing returns computed from price data within the selected period.",
        "sa_bench_diag_header":    "Benchmark-Relative Diagnostics",
        "sa_bench_diag_caption":   "Beta, Tracking Error, and Information Ratio vs {benchmark}.",
        "sa_heatmap_header":       "Monthly Returns Heatmap",
        "sa_interpretation_header":"Interpretation",

        # ── Performance table column names ─────────────────────────────────────
        "col_ticker":       "Ticker",
        "col_1m":           "1M",
        "col_3m":           "3M",
        "col_6m":           "6M",
        "col_ytd":          "YTD",
        "col_1y":           "1Y",
        "col_total_return": "Total Return",
        "col_ann_return":   "Ann. Return",
        "col_ann_vol":      "Ann. Vol",
        "col_sharpe":       "Sharpe",
        "col_max_dd":       "Max Drawdown",
        "col_beta":         "Beta",
        "col_tracking_error": "Tracking Error",
        "col_info_ratio":   "Information Ratio",
        "col_excess_return":"Excess Return vs {benchmark}",
        "col_rel_vol":      "Rel. Volatility",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # Danish — optional localization layer
    # Missing keys fall back to English automatically.
    # Analytics terminology (Sharpe Ratio, Benchmark, Drawdown, Beta,
    # Tracking Error, Information Ratio) is intentionally kept in English.
    # ══════════════════════════════════════════════════════════════════════════
    "da": {
        # ── Sidebar ────────────────────────────────────────────────────────────
        "sidebar_title":       "Porteføljeanalyse",
        "sidebar_subtitle":    "Professionelt investeringsanalyseværktøj",
        "sidebar_date_range":  "Datointerval",
        "sidebar_from":        "Fra",
        "sidebar_to":          "Til",
        "sidebar_period":      "Periode: **{label}**",
        "sidebar_data_source": "Data: Yahoo Finance via yfinance",
        "sidebar_disclaimer":  "Kun til personlig brug — ikke finansiel rådgivning.",
        "sidebar_language":    "Sprog",
        "sidebar_date_error":  "Startdato skal være før slutdato.",

        # ── Navigation tabs ────────────────────────────────────────────────────
        "tab_market_overview": "📈 Markedsoverblik",
        "tab_single_asset":    "🔍 Enkelt aktiv",
        "tab_portfolio":       "💼 Porteføljeanalyse",
        "tab_backtest":        "🔄 Strategi-backtest",
        "tab_scenario":        "⚡ Scenarieanalyse",

        # ── Market Overview ────────────────────────────────────────────────────
        "mo_header":               "Markedsoverblik",
        "mo_caption":              "Sammenlign ETF'er og benchmarks. Følg afkast, risiko og tværgående markedsrelationer over enhver tidshorisont.",
        "mo_period_label":         "Periode",
        "mo_period_help":          "Hurtig periodevalg. 'Max' og 'Tilpasset' bruger sidebjælkens datointerval.",
        "mo_tickers_label":        "Tickers",
        "mo_tickers_help":         "Vælg de ETF'er, du vil sammenligne.",
        "mo_benchmark_label":      "Benchmark",
        "mo_benchmark_help":       "Referenceindeks til benchmark-relativ analyse.",
        "mo_no_tickers":           "Vælg mindst én ticker for at fortsætte.",
        "mo_downloading":          "Downloader markedsdata...",
        "mo_no_data":              "Ingen data returneret. Prøv et andet interval eller en anden tickervalg.",
        "mo_skipped":              "Ingen data for: {tickers} — springet over.",
        "mo_none_returned":        "Ingen af de valgte tickers returnerede data.",
        "mo_custom_range":         "Tilpasset interval: **{start}** → **{end}** (angivet i sidebjælken)",
        "mo_snapshot_header":      "Markedsøjeblik",
        "mo_best_performer":       "Bedste afkast",
        "mo_worst_performer":      "Svageste afkast",
        "mo_highest_vol":          "Højeste volatilitet",
        "mo_deepest_dd":           "Dybeste drawdown",
        "mo_market_regime":        "Markedsregime",
        "mo_price_header":         "Normaliseret kurs (basis = 100)",
        "mo_drawdown_header":      "Drawdown",
        "mo_rolling_vol_header":   "Rullende 21-dages volatilitet (ann.)",
        "mo_perf_table_header":    "Afkastoversigt",
        "mo_perf_table_caption":   "Periodiske afkast er beregnet ud fra kursdata inden for den valgte periode.",
        "mo_perf_table_empty":     "Ikke tilstrækkeligt data til at opbygge afkasttabellen.",
        "mo_bench_rel_header":     "Benchmark-relativ analyse vs {benchmark} ({bench_ret})",
        "mo_bench_rel_caption":    "Merafkast = samlet afkast minus benchmarkafkast. Beta og tracking error er beregnet på daglige afkast.",
        "mo_bench_rel_empty":      "Kunne ikke beregne benchmark-relative nøgletal.",
        "mo_corr_header":          "Korrelationsmatrix (daglige afkast)",
        "mo_corr_expander":        "Diversificering og korrelationsfortolkning",
        "mo_interpretation_header":"Markedsfortolkning",

        # ── Single Asset ───────────────────────────────────────────────────────
        "sa_header":               "Enkelt aktiv",
        "sa_caption":              "Dybdegående analyse af en enkelt ETF eller aktie. Undersøg kurshistorik, risikoprofil og benchmark-relativt afkast.",
        "sa_ticker_label":         "Ticker-symbol",
        "sa_ticker_help":          "Ethvert Yahoo Finance-ticker, fx SPY, QQQ, TLT, IWDA.AS",
        "sa_benchmark_label":      "Benchmark",
        "sa_benchmark_help":       "Referenceindeks til benchmark-relativ analyse.",
        "sa_period_label":         "Periode",
        "sa_period_help":          "Hurtig periodevalg. 'Max' og 'Tilpasset' bruger sidebjælkens datointerval.",
        "sa_short_ma_label":       "Kort MA",
        "sa_long_ma_label":        "Lang MA",
        "sa_no_ticker":            "Angiv et ticker-symbol for at fortsætte.",
        "sa_downloading":          "Downloader {ticker}...",
        "sa_no_data":              "Ingen data fundet for '{ticker}'. Tjek symbolet og datointervallet.",
        "sa_custom_range":         "Tilpasset interval: **{start}** → **{end}** (angivet i sidebjælken)",
        "sa_kpi_header":           "{ticker} — Nøgletal",
        "sa_period_return":        "Periodens afkast",
        "sa_1y_return":            "1Å afkast",
        "sa_ann_vol":              "Ann. volatilitet",
        "sa_sharpe":               "Sharpe Ratio",
        "sa_max_dd":               "Max drawdown",
        "sa_excess_return":        "Merafkast vs {benchmark}",
        "sa_price_ma_header":      "Kurs og glidende gennemsnit",
        "sa_cum_return_header":    "Akkumuleret afkast vs benchmark",
        "sa_drawdown_header":      "Drawdown",
        "sa_rolling_vol_header":   "Rullende 21-dages volatilitet (annualiseret)",
        "sa_perf_table_header":    "Afkasttabel",
        "sa_perf_table_caption":   "Periodiske afkast beregnet ud fra kursdata inden for den valgte periode.",
        "sa_bench_diag_header":    "Benchmark-relative nøgletal",
        "sa_bench_diag_caption":   "Beta, Tracking Error og Information Ratio vs {benchmark}.",
        "sa_heatmap_header":       "Månedligt afkast — varmekort",
        "sa_interpretation_header":"Fortolkning",

        # ── Performance table column names ─────────────────────────────────────
        "col_ticker":       "Ticker",
        "col_1m":           "1M",
        "col_3m":           "3M",
        "col_6m":           "6M",
        "col_ytd":          "ÅTD",
        "col_1y":           "1Å",
        "col_total_return": "Samlet afkast",
        "col_ann_return":   "Ann. afkast",
        "col_ann_vol":      "Ann. vol",
        "col_sharpe":       "Sharpe",
        "col_max_dd":       "Max drawdown",
        "col_beta":         "Beta",
        "col_tracking_error": "Tracking Error",
        "col_info_ratio":   "Information Ratio",
        "col_excess_return":"Merafkast vs {benchmark}",
        "col_rel_vol":      "Rel. volatilitet",
    },
}


def get_text(key: str, lang: str = "en", **kwargs: str) -> str:
    """
    Retrieve a localized UI string by key.

    Falls back to English if:
      - the requested language is not registered, or
      - the key is missing in the requested language.

    Supports named format placeholders via kwargs, e.g.::

        get_text("sa_kpi_header", "da", ticker="SPY")
        # → "SPY — Nøgletal"

    Args:
        key:    Translation key (see TRANSLATIONS dict above).
        lang:   Language code, "en" or "da". Defaults to "en".
        **kwargs: Named placeholders to format into the resulting string.

    Returns:
        Localized string, or the raw key if not found anywhere.
    """
    text = TRANSLATIONS.get(lang, {}).get(key) or TRANSLATIONS["en"].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text
